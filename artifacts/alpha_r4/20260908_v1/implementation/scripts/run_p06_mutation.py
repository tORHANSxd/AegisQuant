"""Run deterministic real-source mutations against the P06 backtest tests."""

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

from aegisquant.backtest.policy import load_backtest_policy


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
        "sell-cost-direction",
        "src/aegisquant/backtest/costs.py",
        'direction = Decimal("1") if order.side is OrderSide.BUY else Decimal("-1")',
        'direction = Decimal("1") if order.side is OrderSide.BUY else Decimal("1")',
    ),
    Mutation(
        "impact-cap-minimum",
        "src/aegisquant/backtest/costs.py",
        "impact_bps = min(",
        "impact_bps = max(",
    ),
    Mutation(
        "maker-taker-fee-selection",
        "src/aegisquant/backtest/costs.py",
        "schedule.maker_fee_bps\n        if fill_slice.liquidity_role is LiquidityRole.MAKER\n        else schedule.taker_fee_bps",
        "schedule.taker_fee_bps\n        if fill_slice.liquidity_role is LiquidityRole.MAKER\n        else schedule.maker_fee_bps",
    ),
    Mutation(
        "funding-sign",
        "src/aegisquant/backtest/costs.py",
        "signed_quantity * mark_price * funding_rate",
        "signed_quantity * mark_price * -funding_rate",
    ),
    Mutation(
        "borrow-year-denominator",
        "src/aegisquant/backtest/costs.py",
        "/ SECONDS_PER_YEAR",
        '/ Decimal("1")',
    ),
    Mutation(
        "trading-enabled-gate",
        "src/aegisquant/backtest/rules.py",
        "if not rule.trading_enabled:",
        "if rule.trading_enabled:",
    ),
    Mutation(
        "step-size-legality",
        "src/aegisquant/backtest/rules.py",
        "elif quantity % rule.step_size != 0:",
        "elif quantity % rule.step_size == 0:",
    ),
    Mutation(
        "liquidity-cap",
        "src/aegisquant/backtest/fills.py",
        "return min(remaining, available * participation_cap)",
        "return max(remaining, available * participation_cap)",
    ),
    Mutation(
        "equal-time-cancel-precedence",
        "src/aegisquant/backtest/engine.py",
        "if cancel_time is not None and cancel_time < event.available_time:",
        "if cancel_time is not None and cancel_time <= event.available_time:",
    ),
    Mutation(
        "request-timeout-ack-state",
        "src/aegisquant/backtest/engine.py",
        "arrival_fault.fault_type is FaultType.REQUEST_TIMEOUT",
        "arrival_fault.fault_type is FaultType.DISCONNECT",
    ),
    Mutation(
        "liquidation-threshold",
        "src/aegisquant/backtest/margin.py",
        "liquidation_required=signed_quantity != 0 and equity <= buffered,",
        "liquidation_required=signed_quantity != 0 and equity >= buffered,",
    ),
    Mutation(
        "vector-asof-direction",
        "src/aegisquant/backtest/vector.py",
        'strategy="forward",',
        'strategy="backward",',
    ),
)

TEST_TARGETS: Final = (
    "tests/p06",
    "tests/property/test_backtest_properties.py",
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
    with tempfile.TemporaryDirectory(prefix="p06-mutation-", dir=runtime) as temporary:
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
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_path = root / "reports/testing/P06_MUTATION_RESULTS.json"
    if arguments.check:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        passed = (
            payload["status"] == "passed"
            and payload["score"] >= payload["threshold"]
            and payload["invalid"] == 0
        )
        print(f"verified P06 mutation score: {payload['score']:.3f}")
        return 0 if passed else 1

    selected = load_backtest_policy(root / "configs/backtest/backtest_policy_v1.yaml")
    baseline_code, baseline_output, baseline_seconds = run_tests(
        root, python_path=None, timeout=arguments.timeout
    )
    results: list[MutationResult] = []
    if baseline_code == 0:
        for mutation in MUTATIONS:
            result = run_mutation(root, mutation, timeout=arguments.timeout)
            results.append(result)
            print(f"[{result.name}] {result.status}")
    killed = sum(result.status == "killed" for result in results)
    survived = sum(result.status == "survived" for result in results)
    invalid = sum(result.status in {"invalid", "timeout"} for result in results)
    score = killed / len(MUTATIONS) if results else 0.0
    threshold = float(selected.mutation_score_threshold)
    passed = baseline_code == 0 and score >= threshold and invalid == 0
    payload = {
        "schema_version": "1.0.0",
        "phase": "P06",
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
    print(f"P06 mutation score: {score:.3f} (threshold {threshold:.3f})")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
