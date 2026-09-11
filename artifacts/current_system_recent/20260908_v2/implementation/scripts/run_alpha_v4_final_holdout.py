"""Record final-holdout eligibility without reopening previously used market data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aegisquant.data.hashing import canonical_sha256
from scripts.run_alpha_v4_walkforward import digest, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/alpha_v4/holdout"
    manifest_file = output / "frozen_holdout_manifest.json"
    if args.check:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        for name, expected in manifest["files_sha256"].items():
            candidate = (output / name).resolve()
            if not candidate.is_relative_to(output.resolve()) or digest(candidate) != expected:
                raise ValueError("holdout audit artifact changed")
        if manifest["actual_data_access_count"] != 0:
            raise ValueError("ineligible holdout data must not have been opened")
        print("holdout audit verified: no eligible unused 12-month dataset, zero final accesses")
        return 0
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("holdout audit already exists; use --check")
    development = json.loads((root / "artifacts/alpha_v4/walkforward/run_manifest.json").read_text(encoding="utf-8"))
    if development["status"] != "COMPLETED":
        raise ValueError("finish the registered development evaluation before final eligibility review")
    output.mkdir(parents=True, exist_ok=True)
    reason = (
        "The existing source dataset ends at 2026-01-01 and its proposed trailing 12 months "
        "overlap the original v5 development OOS through 2025-10-08. The source file has "
        "already been used. No previously unused >=12-month final holdout is available. "
        "No data loader was invoked for final evaluation."
    )
    entry = {
        "sequence": 1, "event": "NOT_OPENED_NO_ELIGIBLE_UNSEEN_TWELVE_MONTHS",
        "occurred_at": development["frozen_at"], "data_access_count": 0,
        "configuration_sha256": development["config_sha256"], "reason": reason,
        "previous_hash": "0" * 64,
    }
    entry["entry_hash"] = canonical_sha256(entry)
    log = output / "holdout_access_log.jsonl"
    log.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    write_json(output / "final_results.json", {
        "decision": "INSUFFICIENT_EVIDENCE", "evaluated": False, "metrics": None,
        "passed": False, "reason": reason, "actual_data_access_count": 0,
        "live_trading": False, "order_submission_enabled": False,
    })
    write_json(manifest_file, {
        "schema_version": "alpha-v4-holdout-v1", "status": "CONFIGURATION_FROZEN_DATA_INELIGIBLE",
        "research_configuration_sha256": development["config_sha256"],
        "research_code_sha256": development["code_sha256"],
        "known_source_data_sha256": development["data_sha256"],
        "minimum_holdout_months": 12, "eligible_dataset": None, "actual_data_access_count": 0,
        "frozen_components": ["features", "trend_formula", "model_families", "horizon", "cost_multipliers", "lambda_cost", "positioning", "risk_rules", "promotion_gates"],
        "reason": reason,
        "future_eligible_data_gate": "aegisquant.research.validation.persistent_holdout.open_persistent_holdout",
        "files_sha256": {name: digest(output / name) for name in ("holdout_access_log.jsonl", "final_results.json")},
    })
    print("INSUFFICIENT_EVIDENCE: final holdout not opened; access count 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
