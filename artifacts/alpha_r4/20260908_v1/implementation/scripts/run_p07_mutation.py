"""Run targeted real-source mutations against P07 leakage and research gates."""

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
        "future-availability-direction",
        "src/aegisquant/research/validation/leakage.py",
        "access.available_time > access.decision_time",
        "access.available_time < access.decision_time",
    ),
    Mutation(
        "label-as-feature-detection",
        "src/aegisquant/research/validation/leakage.py",
        "access.source_kind is FeatureSourceKind.LABEL",
        "access.source_kind is FeatureSourceKind.FEATURE",
    ),
    Mutation(
        "full-sample-normalization-detection",
        "src/aegisquant/research/validation/leakage.py",
        "access.normalization_scope is NormalizationScope.FULL_SAMPLE",
        "access.normalization_scope is NormalizationScope.TRAIN_ONLY",
    ),
    Mutation(
        "random-time-split-gate",
        "src/aegisquant/research/validation/splits.py",
        "if self.shuffle:",
        "if not self.shuffle:",
    ),
    Mutation(
        "holdout-open-once-state",
        "src/aegisquant/research/validation/holdout.py",
        "if self._state is not HoldoutState.FROZEN or self._freeze is None:",
        "if self._state is not HoldoutState.FROZEN and self._freeze is None:",
    ),
    Mutation(
        "strategy-net-cost-direction",
        "src/aegisquant/research/baselines.py",
        "net_return=canonical_result(gross - cost),",
        "net_return=canonical_result(gross + cost),",
    ),
    Mutation(
        "model-temporal-boundary",
        "src/aegisquant/research/models/baselines.py",
        "if train.timestamps[-1] >= test.timestamps[0]:",
        "if train.timestamps[-1] < test.timestamps[0]:",
    ),
    Mutation(
        "universe-availability-direction",
        "src/aegisquant/research/datasets/universe.py",
        "if membership.available_time > as_of_time:",
        "if membership.available_time < as_of_time:",
    ),
    Mutation(
        "event-claim-snapshot-completeness",
        "src/aegisquant/features/events.py",
        "if expected_claims != observed_claims:",
        "if expected_claims == observed_claims:",
    ),
    Mutation(
        "incremental-feature-time-order",
        "src/aegisquant/features/market.py",
        "if history and observation.available_time <= history[-1].available_time:",
        "if history and observation.available_time > history[-1].available_time:",
    ),
)

TEST_TARGETS: Final = (
    "tests/unit/features",
    "tests/property/pit",
    "tests/research",
    "tests/architecture/test_research_boundaries.py",
)
THRESHOLD: Final = 0.90


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
    with tempfile.TemporaryDirectory(prefix="p07-mutation-", dir=runtime) as temporary:
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
    output_path = root / "reports/testing/P07_MUTATION_RESULTS.json"
    if arguments.check:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        passed = (
            payload["status"] == "passed"
            and payload["score"] >= payload["threshold"]
            and payload["invalid"] == 0
        )
        print(f"verified P07 mutation score: {payload['score']:.3f}")
        return 0 if passed else 1

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
    passed = baseline_code == 0 and score >= THRESHOLD and invalid == 0
    payload = {
        "schema_version": "1.0.0",
        "phase": "P07",
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
    print(f"P07 mutation score: {score:.3f} (threshold {THRESHOLD:.3f})")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
