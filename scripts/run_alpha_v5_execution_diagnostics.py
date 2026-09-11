"""B4 execution protocol report only; real calibration and replay are disabled."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from aegisquant.research.validation.evidence_contract import (
    checked_path,
    run_zero_research_contract,
)
from aegisquant.research.validation.execution_contract import (
    FILES,
    build_documents,
    validate_config,
)
from scripts.export_alpha_v4_audit_bundle import git

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--preflight-dir", required=True, type=Path)
    args = parser.parse_args()
    config = yaml.safe_load(checked_path(ROOT, args.config.as_posix()).read_text(encoding="utf-8"))
    validate_config(config)
    output = run_zero_research_contract(
        root=ROOT,
        config=config,
        stage=args.preflight_dir,
        git_state={
            "head": git(ROOT, "rev-parse", "HEAD"),
            "branch": git(ROOT, "branch", "--show-current"),
        },
        files=FILES,
        build_documents=build_documents,
    )
    print(f"B4 execution protocol: {output}; empirical calibration NOT_COLLECTED", flush=True)


if __name__ == "__main__":
    main()
