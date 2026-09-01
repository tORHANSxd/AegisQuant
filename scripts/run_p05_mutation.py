"""Run deterministic real-source mutations against the P05 accounting test suite."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from aegisquant.accounting.ledger import AccountingPolicy


@dataclass(frozen=True, slots=True)
class Mutation:
    name: str
    source: str
    original: str
    replacement: str


@dataclass(frozen=True, slots=True)
class MutationResult:
    name: str
    source: str
    status: str
    exit_code: int | None
    duration_seconds: float
    output_tail: str


MUTATIONS: Final = (
    Mutation(
        "short-side-sign",
        "src/aegisquant/accounting/ledger.py",
        'return Decimal("1") if side is LotSide.LONG else Decimal("-1")',
        'return Decimal("1") if side is LotSide.LONG else Decimal("1")',
    ),
    Mutation(
        "inverse-pnl-operation",
        "src/aegisquant/accounting/ledger.py",
        '* (Decimal("1") / entry_price - Decimal("1") / exit_price)',
        '* (Decimal("1") / entry_price + Decimal("1") / exit_price)',
    ),
    Mutation(
        "fifo-close-quantity",
        "src/aegisquant/accounting/ledger.py",
        "closed_quantity = min(remaining, lot.remaining_quantity)",
        "closed_quantity = max(remaining, lot.remaining_quantity)",
    ),
    Mutation(
        "spot-inventory-gate",
        "src/aegisquant/accounting/ledger.py",
        "if available < quantity:",
        "if available > quantity:",
    ),
    Mutation(
        "idempotency-inserted-flag",
        "src/aegisquant/accounting/ledger.py",
        "return FillApplyOutcome(applied_fill=existing, inserted=False)",
        "return FillApplyOutcome(applied_fill=existing, inserted=True)",
    ),
    Mutation(
        "valuation-priority",
        "src/aegisquant/accounting/models.py",
        "ValuationSource.MARK,\n    ValuationSource.MID,",
        "ValuationSource.MID,\n    ValuationSource.MARK,",
    ),
    Mutation(
        "pnl-borrow-sign",
        "src/aegisquant/accounting/models.py",
        "- self.borrow_interest\n            - self.trading_fees",
        "+ self.borrow_interest\n            - self.trading_fees",
    ),
    Mutation(
        "cashflow-interest-direction",
        "src/aegisquant/accounting/models.py",
        "CashflowType.BORROW_INTEREST: CashflowDirection.OUTFLOW,",
        "CashflowType.BORROW_INTEREST: CashflowDirection.INFLOW,",
    ),
    Mutation(
        "rounding-classification",
        "src/aegisquant/accounting/reconciliation.py",
        "elif abs(local_value - venue_value) <= tolerance:",
        "elif abs(local_value - venue_value) >= tolerance:",
    ),
    Mutation(
        "continuous-reconciliation-status",
        "src/aegisquant/accounting/reconciliation.py",
        "elif mode is ReconciliationMode.CONTINUOUS:",
        "elif mode is ReconciliationMode.STARTUP:",
    ),
    Mutation(
        "snapshot-payload-hash",
        "src/aegisquant/accounting/snapshots.py",
        "if canonical_sha256(payload) != snapshot.payload_hash:",
        "if canonical_sha256(payload) == snapshot.payload_hash:",
    ),
    Mutation(
        "journal-balance-comparison",
        "src/aegisquant/domain/accounting.py",
        "if any(balance != 0 for balance in balances.values()):",
        "if any(balance < 0 for balance in balances.values()):",
    ),
)

TEST_TARGETS: Final = (
    "tests/p05",
    "tests/property/test_accounting_properties.py",
    "tests/unit/domain/test_accounting.py",
)


def run_tests(root: Path, *, python_path: Path | None, timeout: int) -> tuple[int, str, float]:
    environment = os.environ.copy()
    if python_path is not None:
        existing = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            str(python_path) if not existing else str(python_path) + os.pathsep + existing
        )
    command = [sys.executable, "-m", "pytest", "-q", *TEST_TARGETS]
    started = time.perf_counter()
    # The interpreter and test targets are repository-controlled; no shell is used.
    result = subprocess.run(  # noqa: S603  # nosec B603
        command,
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return result.returncode, output[-4000:], time.perf_counter() - started


def run_mutation(root: Path, mutation: Mutation, *, timeout: int) -> MutationResult:
    runtime = root / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="p05-mutation-", dir=runtime) as temporary:
        temporary_root = Path(temporary)
        mutated_src = temporary_root / "src"
        shutil.copytree(root / "src/aegisquant", mutated_src / "aegisquant")
        target = temporary_root / mutation.source
        source = target.read_text(encoding="utf-8")
        count = source.count(mutation.original)
        if count != 1:
            return MutationResult(
                mutation.name,
                mutation.source,
                "invalid",
                None,
                round(time.perf_counter() - started, 3),
                f"expected one mutation site, found {count}",
            )
        target.write_text(
            source.replace(mutation.original, mutation.replacement, 1),
            encoding="utf-8",
            newline="\n",
        )
        try:
            exit_code, output, elapsed = run_tests(root, python_path=mutated_src, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            return MutationResult(
                mutation.name,
                mutation.source,
                "timeout",
                None,
                round(time.perf_counter() - started, 3),
                str(error),
            )
    return MutationResult(
        mutation.name,
        mutation.source,
        "killed" if exit_code != 0 else "survived",
        exit_code,
        round(elapsed, 3),
        output,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_path = root / "reports/testing/P05_MUTATION_RESULTS.json"
    if args.check:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        passed = (
            payload["status"] == "passed"
            and payload["score"] >= payload["threshold"]
            and payload["invalid"] == 0
        )
        print(f"verified P05 mutation score: {payload['score']:.3f}")
        return 0 if passed else 1
    policy = AccountingPolicy.from_yaml(root / "configs/accounting/accounting_policy_v1.yaml")
    baseline_code, baseline_output, baseline_seconds = run_tests(
        root, python_path=None, timeout=args.timeout
    )
    results: list[MutationResult] = []
    if baseline_code == 0:
        for mutation in MUTATIONS:
            result = run_mutation(root, mutation, timeout=args.timeout)
            results.append(result)
            print(f"[{result.name}] {result.status}")
    killed = sum(result.status == "killed" for result in results)
    survived = sum(result.status == "survived" for result in results)
    invalid = sum(result.status in {"invalid", "timeout"} for result in results)
    score = killed / len(MUTATIONS) if results else 0.0
    threshold = float(policy.mutation_score_threshold)
    passed = baseline_code == 0 and score >= threshold and invalid == 0
    payload = {
        "schema_version": "1.0.0",
        "phase": "P05",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "passed" if passed else "failed",
        "baseline_exit_code": baseline_code,
        "baseline_duration_seconds": round(baseline_seconds, 3),
        "baseline_output_tail": baseline_output,
        "mutants_total": len(MUTATIONS),
        "killed": killed,
        "survived": survived,
        "invalid": invalid,
        "score": round(score, 6),
        "threshold": threshold,
        "results": [asdict(result) for result in results],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"P05 mutation score: {score:.3f} (threshold {threshold:.3f})")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
