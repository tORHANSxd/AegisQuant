"""Run focused P11 mutations against portfolio, signature, state, and pre-trade gates."""

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
        "no-trade-zone-direction",
        "src/aegisquant/portfolio/optimizer.py",
        "in_zone = abs(robust) < policy.no_trade_zone",
        "in_zone = abs(robust) > policy.no_trade_zone",
        "tests/portfolio/test_signals_optimizer.py",
    ),
    Mutation(
        "future-covariance-availability",
        "src/aegisquant/portfolio/optimizer.py",
        "if covariance.available_at > as_of_time:",
        "if covariance.available_at < as_of_time:",
        "tests/portfolio/test_signals_optimizer.py",
    ),
    Mutation(
        "group-constraint-projection",
        "src/aegisquant/portfolio/optimizer.py",
        "if gross <= constraint.maximum_absolute_weight:",
        "if gross >= constraint.maximum_absolute_weight:",
        "tests/portfolio/test_constraints.py",
    ),
    Mutation(
        "stale-risk-data",
        "src/aegisquant/risk/engine.py",
        "if decision_time - snapshot.data_last_available_at > maximum_age:",
        "if decision_time - snapshot.data_last_available_at < maximum_age:",
        "tests/risk/test_decision_engine.py",
    ),
    Mutation(
        "pretrade-amplification",
        "src/aegisquant/risk/engine.py",
        "or abs(request.requested_delta_weight) > abs(approved_delta)",
        "or abs(request.requested_delta_weight) < abs(approved_delta)",
        "tests/risk/test_pretrade.py",
    ),
    Mutation(
        "automatic-safer-only",
        "src/aegisquant/risk/state_machine.py",
        "if SAFETY_RANK[target] < SAFETY_RANK[current]:",
        "if SAFETY_RANK[target] > SAFETY_RANK[current]:",
        "tests/risk/test_state_machine.py",
    ),
    Mutation(
        "rumor-reduction-cap",
        "src/aegisquant/risk/playbooks.py",
        "if event.requested_reduction_fraction > policy.maximum_rumor_reduction_fraction:",
        "if event.requested_reduction_fraction < policy.maximum_rumor_reduction_fraction:",
        "tests/risk/test_playbooks.py",
    ),
    Mutation(
        "paper-only-policy",
        "src/aegisquant/risk/policy.py",
        "if self.allowed_stages != (DeploymentStage.PAPER,) or not self.example_values_only:",
        "if self.allowed_stages == (DeploymentStage.PAPER,) or not self.example_values_only:",
        "tests/risk/test_policy_signature.py",
    ),
    Mutation(
        "signed-policy-hash",
        "src/aegisquant/risk/policy.py",
        "if envelope.policy_sha256 != expected_hash:",
        "if envelope.policy_sha256 == expected_hash:",
        "tests/risk/test_policy_signature.py",
    ),
    Mutation(
        "reduce-only-toward-zero",
        "src/aegisquant/risk/engine.py",
        "abs(post_weight) >= abs(target.current_weight)",
        "abs(post_weight) <= abs(target.current_weight)",
        "tests/risk/test_pretrade.py",
    ),
    Mutation(
        "proposal-order-capability",
        "src/aegisquant/portfolio/models.py",
        "if self.order_capability:",
        "if not self.order_capability:",
        "tests/portfolio/test_signals_optimizer.py",
    ),
)
THRESHOLD: Final = 0.90


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_path = root / "reports/testing/P11_MUTATION_RESULTS.json"
    if arguments.check:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        passed = (
            payload["status"] == "passed"
            and payload["score"] >= payload["threshold"]
            and payload["invalid"] == 0
        )
        print(f"verified P11 mutation score: {payload['score']:.3f}")
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
    passed = baseline_code == 0 and score >= THRESHOLD and invalid == 0
    payload = {
        "schema_version": "1.0.0",
        "phase": "P11",
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
    print(f"P11 mutation score: {score:.3f} (threshold {THRESHOLD:.3f})")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
