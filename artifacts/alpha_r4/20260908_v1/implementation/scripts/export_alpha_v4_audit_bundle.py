"""Allowlisted, local-only evidence export. Never fits or replays a strategy."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOTS = (
    "artifacts/alpha_v4/before",
    "artifacts/alpha_v4/walkforward",
    "artifacts/alpha_v4/reports",
    "artifacts/alpha_v4_multi_asset",
)
NAMES = {
    "run_manifest.json",
    "source_manifest.json",
    "evidence_manifest.json",
    "asset_manifest.json",
    "preregistration.json",
    "completion.json",
    "fold_manifest.json",
    "summary_manifest.json",
    "validation.json",
    "metric_lineage.json",
    "resolved_config.yaml",
    "current_failure_report.md",
    "report.md",
    "final_go_no_go.md",
    "strategy_card.md",
    "model_card.md",
    "backtest_correctness_report.md",
    "economic_attribution_report.md",
    "frozen_predictions.parquet",
    "predictions.parquet",
    "decisions.parquet",
    "orders.parquet",
    "fills.parquet",
    "positions.parquet",
    "mtm_equity.parquet",
    "trades.parquet",
    "cost_waterfall.parquet",
    "terminal_attribution.parquet",
    "fold_manifest.parquet",
    "fold_stability.parquet",
    "all_trials.parquet",
    "ablation_results.parquet",
    "neighborhood_stability.parquet",
    "aggregate_stress.parquet",
    "sample_coverage.parquet",
    "return_intervals.parquet",
    "portfolio_mtm_equity.parquet",
    "base_equity.parquet",
    "cost_identity.parquet",
    "bootstrap_results.json",
    "dsr_pbo.json",
}
CONFIGS = (
    "configs/strategies/aegisalpha_cat_v1.yaml",
    "configs/research/aegis_alpha_v4.yaml",
    "configs/research/alpha_v4_multi_asset.yaml",
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(root: Path, *args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("git is required to record source identity")
    return subprocess.check_output(  # noqa: S603 -- fixed git commands; no shell
        [executable, "-C", str(root), *args], text=True, encoding="utf-8"
    ).strip()


def export(root: Path, output: Path, *, copy_limit: int = 1_000_000) -> dict[str, Any]:
    root, output = root.resolve(), output.resolve()
    if copy_limit < 0 or not output.is_relative_to(root / "artifacts/alpha_v4_audit"):
        raise ValueError("export destination must be a new artifacts/alpha_v4_audit directory")
    if output.exists():
        raise FileExistsError("audit evidence exists; use --check, never replace it")
    if git(root, "branch", "--show-current") != "main":
        raise ValueError("audit export requires existing main; no branch mutation")
    paths = [root / name for name in CONFIGS]
    missing: list[str] = []
    for name in RUN_ROOTS:
        folder = root / name
        if not folder.is_dir():
            missing.append(name)
            continue
        paths.extend(p for p in folder.rglob("*") if p.is_file() and p.name in NAMES)
    output.mkdir(parents=True)
    records: list[dict[str, Any]] = []
    for path in sorted(set(paths)):
        if not path.exists():
            missing.append(path.relative_to(root).as_posix())
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("evidence links outside the project are forbidden")
        relative = path.relative_to(root).as_posix()
        record: dict[str, Any] = {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        }
        if record["bytes"] <= copy_limit:
            destination = output / "files" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            record["export_sha256"] = digest(destination)
            record["export_mode"] = "BYTE_COPY"
        else:
            record["export_mode"] = "HASHED_PARTITION_INDEX_ORIGINAL_RETAINED"
        if path.suffix == ".parquet":
            import pyarrow.parquet as pq

            metadata = pq.ParquetFile(path)
            record["rows"] = metadata.metadata.num_rows
            record["fields"] = metadata.schema_arrow.names
        records.append(record)
    source_path = root / "artifacts/alpha_v4_multi_asset/source_manifest.json"
    datasets = json.loads(source_path.read_text(encoding="utf-8"))["datasets"]
    data_hashes = {}
    for row in datasets:
        path = (root / row["path"]).resolve()
        if not path.is_relative_to(root / "data/bronze") or path.suffix != ".csv":
            raise ValueError("only declared public bronze CSV identity may be read")
        data_hashes[path.relative_to(root).as_posix()] = digest(path)
        if data_hashes[path.relative_to(root).as_posix()] != row["sha256"]:
            raise ValueError(f"source evidence changed: {row['symbol']}")
    manifest = {
        "version": "alpha-v4-audit-evidence-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "git_sha": git(root, "rev-parse", "HEAD"),
        "branch": "main",
        "worktree_status": git(root, "status", "--porcelain=v1", "--untracked-files=normal"),
        "python": sys.version,
        "lock_sha256": digest(root / "uv.lock"),
        "files": records,
        "public_dataset_hashes": data_hashes,
        "missing_files": missing,
        "source_hashes": {
            p.relative_to(root).as_posix(): digest(p)
            for p in sorted((root / "src/aegisquant").rglob("*.py"))
        },
        "evidence_tier": "PREVIOUSLY_USED_DEVELOPMENT_DATA",
        "known_missing": [
            "raw_prediction",
            "mean_bias",
            "persisted_fitted_coefficients",
            "historical_orderbook_fee_tiers",
            "verified_unused_12_month_holdout",
        ],
        "model_fits_triggered": 0,
        "replays_triggered": 0,
        "final_holdout_access_count": 0,
        "secrets_or_accounts_accessed": False,
    }
    (output / "audit_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def check(root: Path, output: Path) -> dict[str, Any]:
    manifest = json.loads((output / "audit_manifest.json").read_text(encoding="utf-8"))
    changed: list[str] = []
    for row in manifest["files"]:
        if digest(root / row["path"]) != row["sha256"]:
            changed.append(row["path"])
        if (
            "export_sha256" in row
            and digest(output / "files" / row["path"]) != row["export_sha256"]
        ):
            changed.append("EXPORT:" + row["path"])
    for name, expected in manifest["public_dataset_hashes"].items():
        if digest(root / name) != expected:
            changed.append(name)
    if changed:
        raise ValueError(f"frozen evidence changed: {changed}")
    return {"status": "PASS", "files": len(manifest["files"]), "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = check(ROOT, args.output) if args.check else export(ROOT, args.output)
    print(json.dumps({k: v for k, v in result.items() if k in {"status", "git_sha", "changed"}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
