"""Run the already registered F4/F5 sleeves in two isolated Python processes."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from scripts.export_alpha_v4_audit_bundle import digest
from scripts.run_alpha_r4 import run_sleeve
from scripts.run_alpha_v4_audit import ROOT, SYMBOLS, inputs, read_json
from scripts.run_alpha_v4_walkforward import write_json


def run_symbol(output: Path, symbol: str) -> list[dict[str, Any]]:
    data = inputs(symbol)
    rows: list[dict[str, Any]] = []
    for arm in ("F4", "F5"):
        for mode, multiplier in [
            ("REDECIDE_FUNDED", "1"),
            *[
                (mode, m)
                for m in ("1.5", "2")
                for mode in ("FROZEN_ORDERS_FUNDED", "REDECIDE_FUNDED")
            ],
        ]:
            rows.append(run_sleeve(output, arm, symbol, data, mode, multiplier))
            write_json(output / f"challenger_trials_{symbol}.json", {"trials": rows})
    return rows


def run(output: Path) -> None:
    registry = read_json(output / "experiment_registry.json")
    core = registry["trials"]
    if len(core) != 100 or any(r["status"] != "REPLAYED" for r in core):
        raise ValueError("all 100 core funded sleeve scenarios must finish first")
    if read_json(output / "boundary_state_checks.json")["status"] != "PASS":
        raise ValueError("state recovery must pass before challengers")
    if read_json(output / "validation/full_pytest_execution.json")["exit_code"] != 0:
        raise ValueError("full engineering tests must pass before challengers")
    config = read_json(output / "effective_config.json")
    for name, expected in config["integrated_source"].items():
        if name.startswith("src/") and digest(ROOT / name) != expected:
            raise ValueError(f"frozen strategy changed: {name}")
    write_json(
        output / "challenger_execution_manifest.json",
        {
            "dispatcher_sha256": digest(Path(__file__)),
            "workers": 2,
            "engine_and_strategy_source": config["integrated_source_sha256"],
            "arms": ["F4", "F5"],
            "new_parameter_selection": False,
            "isolation": "one independent symbol per process, no shared account or registry writes",
        },
    )
    with ProcessPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(run_symbol, output, symbol): symbol for symbol in SYMBOLS}
        for future in as_completed(futures):
            registry["trials"].extend(future.result())
            write_json(output / "experiment_registry.json", registry)
    registry["status"] = "REPLAYED"
    write_json(output / "experiment_registry.json", registry)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output.resolve())
