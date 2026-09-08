"""Run focused P12 mutations against execution safety and recovery gates."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from scripts.run_p09_mutation import Mutation, MutationResult, run_mutation, run_test

MUTATIONS: Final = (
    Mutation(
        "risk-decision-gate",
        "src/aegisquant/execution/commands.py",
        "if decision.status not in {RiskDecisionStatus.APPROVED, RiskDecisionStatus.REDUCE_ONLY}:",
        "if decision.status in {RiskDecisionStatus.APPROVED, RiskDecisionStatus.REDUCE_ONLY}:",
        "tests/execution/test_commands.py",
    ),
    Mutation(
        "intent-risk-expiry",
        "src/aegisquant/execution/commands.py",
        "if issued_at > intent.valid_until or issued_at > decision.valid_until:",
        "if issued_at < intent.valid_until or issued_at > decision.valid_until:",
        "tests/execution/test_commands.py",
    ),
    Mutation(
        "stale-instrument-rules",
        "src/aegisquant/execution/rules.py",
        "if decision_time > rules.valid_until:",
        "if decision_time < rules.valid_until:",
        "tests/execution/test_rules.py",
    ),
    Mutation(
        "quantity-precision",
        "src/aegisquant/execution/rules.py",
        "if reject_precision_change and quantity_amount != intent.quantity.amount:",
        "if reject_precision_change and quantity_amount == intent.quantity.amount:",
        "tests/execution/test_rules.py",
    ),
    Mutation(
        "order-sequence-gap",
        "src/aegisquant/execution/state_machine.py",
        "and event.venue_sequence > record.last_venue_sequence + 1",
        "and event.venue_sequence < record.last_venue_sequence + 1",
        "tests/execution/test_state_machine.py",
    ),
    Mutation(
        "order-overfill",
        "src/aegisquant/execution/state_machine.py",
        "if event.venue_cumulative_filled.amount > record.total_quantity.amount:",
        "if event.venue_cumulative_filled.amount < record.total_quantity.amount:",
        "tests/execution/test_state_machine.py",
    ),
    Mutation(
        "adapter-idempotent-submit",
        "src/aegisquant/execution/adapter.py",
        "if existing is not None:",
        "if existing is None:",
        "tests/execution/test_adapter_recovery.py",
    ),
    Mutation(
        "adapter-economic-idempotency",
        "src/aegisquant/execution/adapter.py",
        "if bound_client_id is not None and bound_client_id != key:",
        "if False and bound_client_id != key:",
        "tests/execution/test_adapter_recovery.py",
    ),
    Mutation(
        "unknown-submit-evidence",
        "src/aegisquant/execution/recovery.py",
        "if matching_open:",
        "if not matching_open:",
        "tests/execution/test_adapter_recovery.py",
    ),
    Mutation(
        "execution-group-overfill",
        "src/aegisquant/execution/groups.py",
        "if cumulative > leg.target_notional:",
        "if cumulative < leg.target_notional:",
        "tests/execution/test_groups.py",
    ),
    Mutation(
        "cancel-priority",
        "src/aegisquant/execution/rate_limit.py",
        "RISK_OR_CANCEL = 0",
        "RISK_OR_CANCEL = 4",
        "tests/execution/test_rate_limit.py",
    ),
    Mutation(
        "fill-outbox-atomicity",
        "src/aegisquant/execution/atomic.py",
        "if ledger_inserted != event_inserted:",
        "if ledger_inserted == event_inserted:",
        "tests/integration/test_p12_atomic_fill.py",
    ),
    Mutation(
        "account-sequence-gap",
        "src/aegisquant/execution/accounts.py",
        "gap = self.last_sequence > 0 and event.sequence != self.last_sequence + 1",
        "gap = self.last_sequence > 0 and event.sequence == self.last_sequence + 1",
        "tests/execution/test_accounts.py",
    ),
    Mutation(
        "production-domain-capability",
        "src/aegisquant/execution/models.py",
        "or self.live_domain_available",
        "and self.live_domain_available",
        "tests/security/test_p12_testnet_only.py",
    ),
    Mutation(
        "lifecycle-submit-gate",
        "src/aegisquant/execution/lifecycle.py",
        "if self.state is not ExecutionEngineState.RUNNING:",
        "if self.state is ExecutionEngineState.RUNNING:",
        "tests/execution/test_lifecycle.py",
    ),
)
THRESHOLD: Final = 0.90


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--timeout", type=int, default=90)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_path = root / "reports/testing/P12_MUTATION_RESULTS.json"
    if arguments.check:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        passed = (
            payload["status"] == "passed"
            and payload["score"] >= payload["threshold"]
            and payload["invalid"] == 0
            and payload["survived"] == 0
        )
        print(f"verified P12 mutation score: {payload['score']:.3f}")
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
        "phase": "P12",
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
    print(f"P12 mutation score: {score:.3f} (threshold {THRESHOLD:.3f})")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
