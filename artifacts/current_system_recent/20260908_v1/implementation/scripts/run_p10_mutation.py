"""Run focused mutations against P10 time, rights, evidence, and execution gates."""

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
        "unknown-rights-sensitive-use",
        "src/aegisquant/intelligence/world/models.py",
        "if self.rights_state in {RightsState.UNKNOWN, RightsState.PROHIBITED}:",
        "if self.rights_state is RightsState.PROHIBITED:",
        "tests/intelligence/world/test_source_policy.py",
    ),
    Mutation(
        "repost-family-one-witness",
        "src/aegisquant/intelligence/world/events.py",
        "if self.independent_evidence_count != 1:",
        "if self.independent_evidence_count == 1:",
        "tests/intelligence/world/test_event_graph.py",
    ),
    Mutation(
        "committee-proposal-only",
        "src/aegisquant/intelligence/world/events.py",
        'if self.action != "RESEARCH_PROPOSAL_ONLY":',
        'if self.action == "RESEARCH_PROPOSAL_ONLY":',
        "tests/intelligence/world/test_committee_paths.py",
    ),
    Mutation(
        "event-future-evidence",
        "src/aegisquant/intelligence/world/events.py",
        "if any(item.available_at > self.as_of_time for item in self.evidence):",
        "if any(item.available_at < self.as_of_time for item in self.evidence):",
        "tests/intelligence/world/test_event_graph.py",
    ),
    Mutation(
        "fusion-future-feature",
        "src/aegisquant/intelligence/world/fusion.py",
        "if any(item.available_at > self.as_of_time for item in self.features):",
        "if any(item.available_at < self.as_of_time for item in self.features):",
        "tests/intelligence/world/test_impact_fusion.py",
    ),
    Mutation(
        "ablation-identical-samples",
        "src/aegisquant/intelligence/world/fusion.py",
        "any(samples != first_samples for samples in sample_sets.values())",
        "any(samples == first_samples for samples in sample_sets.values())",
        "tests/intelligence/world/test_impact_fusion.py",
    ),
    Mutation(
        "plaintext-credential-guard",
        "src/aegisquant/intelligence/world/sources.py",
        "if any(key.casefold() in forbidden for key in normalized):",
        "if False and any(key.casefold() in forbidden for key in normalized):",
        "tests/intelligence/world/test_macro_onchain_sources.py",
    ),
    Mutation(
        "alfred-vintage-availability",
        "src/aegisquant/intelligence/world/sources.py",
        "if available is None:",
        "if False and available is None:",
        "tests/intelligence/world/test_macro_onchain_sources.py",
    ),
    Mutation(
        "dune-read-only-sql",
        "src/aegisquant/intelligence/world/sources.py",
        "if _SQL_WRITE_RE.search(without_comments) or",
        "if False and _SQL_WRITE_RE.search(without_comments) or",
        "tests/intelligence/world/test_macro_onchain_sources.py",
    ),
    Mutation(
        "revision-as-of-selection",
        "src/aegisquant/intelligence/world/replay.py",
        "eligible_revisions = [item for item in revisions if item.available_at <= as_of]",
        "eligible_revisions = [item for item in revisions if item.available_at >= as_of]",
        "tests/intelligence/world/test_event_replay.py",
    ),
)
THRESHOLD: Final = 0.90


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_path = root / "reports/testing/P10_MUTATION_RESULTS.json"
    if arguments.check:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        passed = (
            payload["status"] == "passed"
            and payload["score"] >= payload["threshold"]
            and payload["invalid"] == 0
        )
        print(f"verified P10 mutation score: {payload['score']:.3f}")
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
        "phase": "P10",
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
    print(f"P10 mutation score: {score:.3f} (threshold {THRESHOLD:.3f})")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
