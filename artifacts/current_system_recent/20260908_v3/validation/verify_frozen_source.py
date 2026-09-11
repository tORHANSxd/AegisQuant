"""Isolated imports of the frozen R4 snapshot; compare every complete result."""

import json
import shutil
import sys
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1]
FROZEN = OUTPUT / "implementation"
sys.path[:0] = [str(FROZEN), str(FROZEN / "src")]

from scripts import run_recent_multi_asset_backtest as runner
from scripts.run_alpha_r4 import read_result
from scripts.run_alpha_v4_walkforward import write_json

verification = OUTPUT / "validation" / "frozen_reproduction"
verification.mkdir()
shutil.copyfile(OUTPUT / "effective_config.json", verification / "effective_config.json")
shutil.copyfile(OUTPUT / "source_manifest.json", verification / "source_manifest.json")
shutil.copytree(OUTPUT / "data", verification / "data")
checks = []


def compare_saved(folder, result, trace):
    original = OUTPUT / folder.relative_to(verification)
    expected = read_result(original)
    if result.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise ValueError(f"Frozen-source complete result mismatch: {original}")
    checks.append({"path": original.relative_to(OUTPUT).as_posix(),
                   "status": "EXACT_COMPLETE_RESULT_MATCH",
                   "economic_event_hash": result.economic_event_hash})


def read_original(folder):
    return read_result(OUTPUT / folder.relative_to(verification))


runner.save_run = compare_saved
runner.read_result = read_original
runner.run(verification)
if len(checks) != 180:
    raise ValueError("Incomplete frozen source verification")
write_json(OUTPUT / "validation" / "frozen_source_verification.json", {
    "status": "PASS", "matched_complete_results": len(checks),
    "new_research_trials": 0, "additional_verification_engine_runs": 180,
    "imported_runner": str(Path(runner.__file__).resolve()),
    "imported_replay": str(Path(sys.modules["aegisquant.research.validation.cat_replay"].__file__).resolve()),
    "checks": checks,
})
print(json.dumps({"frozen_verification": "PASS", "matched": len(checks)}), flush=True)
