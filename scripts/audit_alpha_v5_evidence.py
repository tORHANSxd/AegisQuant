"""One exclusively claimed read-only report over saved evidence; no old pipeline imports."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import yaml

from aegisquant.research.validation.evidence_contract import checked_path, run_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/research/alpha_v5_review_contract.yaml")
    parser.add_argument("--preflight-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load(checked_path(root, args.config).read_text(encoding="utf-8"))

    def git(*arguments: str) -> str:
        return subprocess.check_output(["git", *arguments], cwd=root).decode("utf-8").strip()  # noqa: S603,S607

    git_state = {
        "head": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "status": git("-c", "core.quotepath=false", "status", "--porcelain=v1"),
    }
    output = run_report(root, config, args.preflight_dir, git_state)
    print(f"Completed read-only evidence report: {output}")


if __name__ == "__main__":
    main()
