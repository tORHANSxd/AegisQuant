"""Independent check of every saved curve before paired research statistics."""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

output = Path(__file__).resolve().parent.parent
manifest = json.loads((output / "preregistration.json").read_text(encoding="utf-8"))
development = manifest["config"]["development"]
start = datetime.fromisoformat(development["test_start"])
end = datetime.fromisoformat(development["end_exclusive"])
expected = [start + timedelta(hours=4 * i) for i in range((end - start).days * 6 + 1)]
daily_expected = [start + timedelta(days=i) for i in range((end - start).days + 1)]
checked = []


def check(frame, identity):
    assert frame.schema["time"] == pl.Datetime("us", "UTC"), identity
    times = frame["time"].to_list()
    assert times == expected, f"missing, repeated, shifted or unordered 4h observations: {identity}"
    daily = [t for t in times if t.hour == 0]
    assert daily == daily_expected, f"incomplete exact UTC midnight calendar: {identity}"
    balances = frame.select("equity", "cash", "position_value").cast(pl.Float64).to_numpy()
    assert np.isfinite(balances).all(), f"non-finite balance: {identity}"
    assert (balances[:, 0] > 0).all(), f"non-positive equity: {identity}"
    assert (balances[:, 1:] >= -1e-8).all(), f"negative funded balance: {identity}"
    residual = np.max(np.abs(balances[:, 0] - balances[:, 1] - balances[:, 2]))
    assert residual < 1e-6, f"cash plus marked holdings does not equal equity: {identity}"
    checked.append({"curve": identity, "points_4h": len(times), "points_daily": len(daily),
                    "maximum_accounting_residual_usdt": float(residual)})


file_hashes = {}
for trial in manifest["planned_runs"]:
    arm, symbol, cost = (trial[k] for k in ("arm", "symbol", "cost"))
    path = output / "runs" / arm / symbol / cost / "equity.parquet"
    check(pl.read_parquet(path), f"{arm}/{symbol}/{cost}")
    file_hashes[path.relative_to(output).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()

legacy_path = output.parents[2] / "artifacts/alpha_r4/20260908_v1/portfolio_equity.parquet"
legacy = pl.read_parquet(legacy_path).filter(
    (pl.col("mode") == "REDECIDE_FUNDED") & (pl.col("cost_multiplier") == "1")
)
for (arm,), frame in legacy.partition_by("arm", as_dict=True).items():
    check(frame, f"legacy/{arm}/portfolio/1")
assert len(checked) == len(manifest["planned_runs"]) + 6
file_hashes[str(legacy_path)] = hashlib.sha256(legacy_path.read_bytes()).hexdigest()
result = {
    "status": "PASS",
    "generation": manifest["config"]["generation"],
    "scope": "55 registered sleeves plus 6 frozen R4 comparison portfolios; every 4h and daily UTC point",
    "first_point": start.isoformat(),
    "last_point": end.isoformat(),
    "terminal_point_interpretation": "closing MTM for end-exclusive development interval",
    "curves": checked,
    "files_sha256": file_hashes,
    "validator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
}
(output / "validation/clock_integrity.json").write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8"
)
print(f"PASS: {len(checked)} curves, each {len(expected)} exact 4h UTC and {len(daily_expected)} daily points")
