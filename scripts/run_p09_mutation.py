"""Run focused real-source mutations against P09 knowledge-safety gates."""

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
    test_target: str


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
        "rights-public-export",
        "src/aegisquant/intelligence/static_analysis/models.py",
        "self.status is not RightsStatus.PUBLIC_LICENSE",
        "self.status is RightsStatus.PUBLIC_LICENSE",
        "tests/intelligence/test_knowledge_models.py",
    ),
    Mutation(
        "zip-compression-ratio",
        "src/aegisquant/intelligence/static_analysis/archive.py",
        "info.file_size / info.compress_size > limits.maximum_compression_ratio",
        "info.file_size / info.compress_size < limits.maximum_compression_ratio",
        "tests/intelligence/test_safe_importer.py",
    ),
    Mutation(
        "directory-symlink",
        "src/aegisquant/intelligence/static_analysis/archive.py",
        "if any((current / name).is_symlink() for name in directory_names):",
        "if False and any((current / name).is_symlink() for name in directory_names):",
        "tests/intelligence/test_safe_importer.py",
    ),
    Mutation(
        "dynamic-execution",
        "src/aegisquant/intelligence/static_analysis/scanner.py",
        "if name in DYNAMIC_EXECUTION_CALLS or base in DYNAMIC_EXECUTION_CALLS:",
        "if False and (name in DYNAMIC_EXECUTION_CALLS or base in DYNAMIC_EXECUTION_CALLS):",
        "tests/security/static_analysis/test_python_scanner.py",
    ),
    Mutation(
        "negative-shift",
        "src/aegisquant/intelligence/static_analysis/scanner.py",
        "if isinstance(first, ast.UnaryOp) and isinstance(first.op, ast.USub):",
        "if isinstance(first, ast.UnaryOp) and isinstance(first.op, ast.UAdd):",
        "tests/security/static_analysis/test_python_scanner.py",
    ),
    Mutation(
        "ai-evidence-subset",
        "src/aegisquant/intelligence/static_analysis/extraction.py",
        "if claimed != referenced or not claimed.issubset(available):",
        "if claimed != referenced and claimed.issubset(available):",
        "tests/intelligence/test_strategy_ir.py",
    ),
    Mutation(
        "behavioral-dedupe-correlation",
        "src/aegisquant/intelligence/static_analysis/dedupe.py",
        "if abs(_correlation(first, second)) >= correlation_threshold:",
        "if abs(_correlation(first, second)) < correlation_threshold:",
        "tests/intelligence/test_dedupe.py",
    ),
    Mutation(
        "live-trading-lock",
        "src/aegisquant/intelligence/static_analysis/translation.py",
        "live_trading_locked: Literal[True] = True",
        "live_trading_locked: Literal[True] = False",
        "tests/intelligence/test_translation.py",
    ),
)
THRESHOLD: Final = 0.90


def _run_test(
    root: Path, *, target: str, python_path: Path | None, timeout: int
) -> tuple[int, str, float]:
    environment = os.environ.copy()
    if python_path is not None:
        existing = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            str(python_path) if not existing else str(python_path) + os.pathsep + existing
        )
    started = time.perf_counter()
    result = subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-m", "pytest", "-q", target],
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


def _run_mutation(root: Path, mutation: Mutation, *, timeout: int) -> MutationResult:
    runtime = root / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="p09-mutation-", dir=runtime) as temporary:
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
            exit_code, output, elapsed = _run_test(
                root,
                target=mutation.test_target,
                python_path=mutated_src,
                timeout=timeout,
            )
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
    output_path = root / "reports/testing/P09_MUTATION_RESULTS.json"
    if arguments.check:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        passed = (
            payload["status"] == "passed"
            and payload["score"] >= payload["threshold"]
            and payload["invalid"] == 0
        )
        print(f"verified P09 mutation score: {payload['score']:.3f}")
        return 0 if passed else 1
    baseline_targets = sorted({mutation.test_target for mutation in MUTATIONS})
    baseline_results = [
        _run_test(root, target=target, python_path=None, timeout=arguments.timeout)
        for target in baseline_targets
    ]
    baseline_code = max(result[0] for result in baseline_results)
    baseline_output = "\n".join(result[1] for result in baseline_results)[-4000:]
    baseline_seconds = sum(result[2] for result in baseline_results)
    results: list[MutationResult] = []
    if baseline_code == 0:
        for mutation in MUTATIONS:
            result = _run_mutation(root, mutation, timeout=arguments.timeout)
            results.append(result)
            print(f"[{result.name}] {result.status}")
    killed = sum(result.status == "killed" for result in results)
    invalid = sum(result.status in {"invalid", "timeout"} for result in results)
    survived = sum(result.status == "survived" for result in results)
    score = killed / len(MUTATIONS) if results else 0.0
    passed = baseline_code == 0 and score >= THRESHOLD and invalid == 0
    payload = {
        "schema_version": "1.0.0",
        "phase": "P09",
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
    print(f"P09 mutation score: {score:.3f} (threshold {THRESHOLD:.3f})")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
