"""Create one B3 contract report; no run/replay mode or historical matrix input."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from aegisquant.research.validation.benchmark_contract import run_contract_job
from aegisquant.research.validation.evidence_contract import checked_path
from scripts.export_alpha_v4_audit_bundle import git

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--preflight-dir", required=True, type=Path)
    args = parser.parse_args()
    config = yaml.safe_load(checked_path(ROOT, args.config.as_posix()).read_text(encoding="utf-8"))
    output = run_contract_job(
        ROOT,
        config,
        args.preflight_dir,
        {"head": git(ROOT, "rev-parse", "HEAD"), "branch": git(ROOT, "branch", "--show-current")},
    )
    print(f"B3 contract report: {output}; historical matrix NOT_COLLECTED", flush=True)


if __name__ == "__main__":
    main()
