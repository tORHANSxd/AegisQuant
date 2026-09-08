"""Run focused P13 mutations against runtime safety and recovery gates."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

from scripts.run_p09_mutation import Mutation, MutationResult, run_mutation, run_test

MUTATIONS: Final = (
    Mutation(
        "paper-economic-idempotency",
        "src/aegisquant/runtime/paper.py",
        "if bound is not None:",
        "if bound is None:",
        "tests/runtime/test_paper.py",
    ),
    Mutation(
        "paper-market-event-dedupe",
        "src/aegisquant/runtime/paper.py",
        "if observation.event_id in state.processed_event_ids:",
        "if observation.event_id not in state.processed_event_ids:",
        "tests/runtime/test_paper.py",
    ),
    Mutation(
        "paper-fill-or-kill",
        "src/aegisquant/runtime/paper.py",
        "and quantity_amount < state.remaining_quantity.amount",
        "and quantity_amount > state.remaining_quantity.amount",
        "tests/runtime/test_paper.py",
    ),
    Mutation(
        "paper-taker-slippage",
        "src/aegisquant/runtime/paper.py",
        "passive_touched = not crosses and (",
        "passive_touched = crosses and (",
        "tests/runtime/test_paper.py",
    ),
    Mutation(
        "paper-checkpoint-hash",
        "src/aegisquant/runtime/paper.py",
        "if expected != self.payload_sha256:",
        "if expected == self.payload_sha256:",
        "tests/runtime/test_paper.py",
    ),
    Mutation(
        "shadow-account-read-only",
        "src/aegisquant/runtime/shadow.py",
        "if self.write_permissions or self.credential_values_accessed:",
        "if self.write_permissions and self.credential_values_accessed:",
        "tests/runtime/test_shadow.py",
    ),
    Mutation(
        "shadow-decision-dedupe",
        "src/aegisquant/runtime/shadow.py",
        "if existing is not None:",
        "if existing is None:",
        "tests/runtime/test_shadow.py",
    ),
    Mutation(
        "market-crossed-book",
        "src/aegisquant/runtime/models.py",
        "if self.bid_price.amount > self.ask_price.amount:",
        "if self.bid_price.amount < self.ask_price.amount:",
        "tests/runtime/test_paper.py",
    ),
    Mutation(
        "cross-mode-identity",
        "src/aegisquant/runtime/comparison.py",
        "if len({repr(getattr(item, field)) for item in ordered}) != 1",
        "if len({repr(getattr(item, field)) for item in ordered}) == 1",
        "tests/runtime/test_comparison.py",
    ),
    Mutation(
        "reconciliation-status",
        "src/aegisquant/runtime/reconciliation.py",
        "status = ReconciliationStatus.HALTED if has_difference else ReconciliationStatus.CLEAR",
        "status = ReconciliationStatus.CLEAR if has_difference else ReconciliationStatus.HALTED",
        "tests/integration/test_p13_runtime_e2e.py",
    ),
    Mutation(
        "reconciliation-new-risk",
        "src/aegisquant/runtime/reconciliation.py",
        "new_risk_allowed=not has_difference,",
        "new_risk_allowed=has_difference,",
        "tests/integration/test_p13_runtime_e2e.py",
    ),
    Mutation(
        "supervisor-clock-threshold",
        "src/aegisquant/runtime/supervisor.py",
        "if clock_drift_ms > self.policy.maximum_clock_drift_ms:",
        "if clock_drift_ms < self.policy.maximum_clock_drift_ms:",
        "tests/runtime/test_supervisor.py",
    ),
    Mutation(
        "supervisor-data-age",
        "src/aegisquant/runtime/supervisor.py",
        "elif data_age_seconds > self.policy.maximum_data_age_seconds:",
        "elif data_age_seconds < self.policy.maximum_data_age_seconds:",
        "tests/runtime/test_supervisor.py",
    ),
    Mutation(
        "supervisor-manual-halt-release",
        "src/aegisquant/runtime/supervisor.py",
        "if self.state is RuntimeState.HALTED and not operator_authorized:",
        "if self.state is RuntimeState.HALTED and operator_authorized:",
        "tests/runtime/test_supervisor.py",
    ),
    Mutation(
        "stability-wall-clock-qualification",
        "src/aegisquant/runtime/supervisor.py",
        "if self.qualifying_wall_clock_acceptance and (",
        "if not self.qualifying_wall_clock_acceptance and (",
        "tests/performance/test_p13_stability.py",
    ),
)
THRESHOLD: Final = 0.90


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--timeout", type=int, default=90)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_path = root / "reports/testing/P13_MUTATION_RESULTS.json"
    if arguments.check:
        payload = cast(
            "dict[str, object]",
            json.loads(output_path.read_text(encoding="utf-8")),
        )
        score = cast("float", payload["score"])
        threshold = cast("float", payload["threshold"])
        passed = (
            payload["status"] == "passed"
            and score >= threshold
            and payload["invalid"] == 0
            and payload["survived"] == 0
        )
        print(f"verified P13 mutation score: {score:.3f}")
        return 0 if passed else 1
    baseline_targets = sorted({mutation.test_target for mutation in MUTATIONS})
    baseline_results = [
        run_test(root, target=target, python_path=None, timeout=arguments.timeout)
        for target in baseline_targets
    ]
    baseline_code = max(result[0] for result in baseline_results)
    baseline_output = "\n".join(result[1] for result in baseline_results)[-4000:]
    baseline_seconds = sum(result[2] for result in baseline_results)
    results: list[MutationResult] = []
    if baseline_code == 0:
        for mutation in MUTATIONS:
            result = run_mutation(root, mutation, timeout=arguments.timeout)
            results.append(result)
            print(f"[{result.name}] {result.status}")
    killed = sum(result.status == "killed" for result in results)
    invalid = sum(result.status in {"invalid", "timeout"} for result in results)
    survived = sum(result.status == "survived" for result in results)
    score = killed / len(MUTATIONS) if results else 0.0
    passed = baseline_code == 0 and score >= THRESHOLD and invalid == 0 and survived == 0
    payload = {
        "schema_version": "1.0.0",
        "phase": "P13",
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
        "threshold": THRESHOLD,
        "results": [asdict(result) for result in results],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"P13 mutation score: {score:.3f} (threshold {THRESHOLD:.3f})")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
