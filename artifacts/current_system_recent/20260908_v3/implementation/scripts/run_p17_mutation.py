"""Run focused P17 mutations against procurement and provider-safety gates."""

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
        "net-increment-after-all-costs",
        "src/aegisquant/research/provider_bakeoff/evaluation.py",
        "measurement.net_incremental_bps >= criteria.min_net_incremental_bps",
        "measurement.net_incremental_bps < criteria.min_net_incremental_bps",
        "tests/research/provider_bakeoff/test_decisions.py",
    ),
    Mutation(
        "unapproved-budget-reason",
        "src/aegisquant/research/provider_bakeoff/evaluation.py",
        "if not plan.budget.user_budget_approved:",
        "if plan.budget.user_budget_approved:",
        "tests/research/provider_bakeoff/test_decisions.py",
    ),
    Mutation(
        "one-primary-per-group",
        "src/aegisquant/research/provider_bakeoff/evaluation.py",
        "if count > 1",
        "if count > 2",
        "tests/research/provider_bakeoff/test_decisions.py",
    ),
    Mutation(
        "provider-outage-free-baseline",
        "src/aegisquant/research/provider_bakeoff/evaluation.py",
        "use_candidate = candidate_approved and provider_available",
        "use_candidate = candidate_approved or provider_available",
        "tests/research/provider_bakeoff/test_news_authority_degradation.py",
    ),
    Mutation(
        "official-trading-fact-authority",
        "src/aegisquant/research/provider_bakeoff/evaluation.py",
        "record.source_authority is not SourceAuthority.OFFICIAL_EXCHANGE",
        "record.source_authority is SourceAuthority.OFFICIAL_EXCHANGE",
        "tests/research/provider_bakeoff/test_news_authority_degradation.py",
    ),
    Mutation(
        "news-matched-event-count",
        "src/aegisquant/research/provider_bakeoff/evaluation.py",
        "matched_event_count=len(matched),",
        "matched_event_count=len(detections),",
        "tests/research/provider_bakeoff/test_news_authority_degradation.py",
    ),
)
THRESHOLD: Final = 1.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--timeout", type=int, default=120)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_path = root / "reports/testing/P17_MUTATION_RESULTS.json"
    if arguments.check:
        payload = cast("dict[str, object]", json.loads(output_path.read_text(encoding="utf-8")))
        score = cast("float", payload["score"])
        threshold = cast("float", payload["threshold"])
        passed = (
            payload["status"] == "passed"
            and score >= threshold
            and payload["invalid"] == 0
            and payload["survived"] == 0
        )
        print(f"verified P17 mutation score: {score:.3f}")
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
        "phase": "P17",
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
    print(f"P17 mutation score: {score:.3f} (threshold {THRESHOLD:.3f})")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
