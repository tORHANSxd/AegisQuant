"""Public funding data audit and fixed carry value screen; no trading or model search."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from aegisquant.research.models.funding_forecast import FundingObservation, forecast_funding
from aegisquant.research.strategies.funding_basis_carry import (
    CarryAdmissionEvidence,
    CarryCosts,
    evaluate_carry,
)
from scripts.run_alpha_v4_walkforward import digest, table, write_json

DOCS = "https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/alpha_v4/funding_basis"
    if args.check:
        manifest = json.loads((output / "admission_report.json").read_text(encoding="utf-8"))
        for name, expected in manifest["files_sha256"].items():
            candidate = (output / name).resolve()
            if not candidate.is_relative_to(output.resolve()) or digest(candidate) != expected:
                raise ValueError("carry source or screen changed")
        print("carry evidence verified; independent OOS and combined sleeve remain unapproved")
        return 0
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("funding audit already exists; use --check")
    output.mkdir(parents=True, exist_ok=True)
    start = int(datetime(2022, 3, 25, tzinfo=UTC).timestamp() * 1000)
    end = int(datetime(2025, 10, 1, tzinfo=UTC).timestamp() * 1000)
    rows: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    with httpx.Client(timeout=20) as client:
        for _ in range(10):
            response = client.get(
                "https://fapi.binance.com/fapi/v1/fundingRate",
                params={"symbol": "BTCUSDT", "startTime": start, "endTime": end, "limit": 1000},
            )
            requests.append({"url": str(response.url), "status": response.status_code})
            response.raise_for_status()
            page: list[dict[str, Any]] = response.json()
            if not page:
                break
            if any(
                row["symbol"] != "BTCUSDT" or not start <= int(row["fundingTime"]) <= end
                for row in page
            ):
                raise ValueError("funding source returned unexpected symbol or time range")
            rows.extend(page)
            start = max(int(row["fundingTime"]) for row in page) + 1
            if start > end:
                break
        else:
            raise ValueError("public funding pagination exceeded declared request budget")
    write_json(
        output / "public_funding_source.json", {"source": DOCS, "requests": requests, "data": rows}
    )
    observed: list[FundingObservation] = []
    screens: list[dict[str, Any]] = []
    costs = CarryCosts(
        spot_entry_exit=Decimal("0.0028"),
        perp_entry_exit=Decimal("0.0028"),
        borrow_financing=Decimal("0"),
        legging=Decimal("0.0002"),
        capital_charge=Decimal("0.0001"),
        tail_risk_buffer=Decimal("0.001"),
        uncertainty_buffer=Decimal("0.0002"),
    )
    for row in rows:
        time = datetime.fromtimestamp(int(row["fundingTime"]) / 1000, UTC)
        # A delayed availability assumption, explicitly weaker than publication-time evidence.
        as_of = time + timedelta(hours=4)
        observed.append(
            FundingObservation(
                settlement_time=time,
                available_time=as_of,
                rate=Decimal(row["fundingRate"]),
                calendar_version="ASSUMED_8H_UNVERIFIED_HISTORY",
            )
        )
        if len(observed) < 21 or as_of >= datetime(2025, 10, 1, tzinfo=UTC):
            continue
        forecast = forecast_funding(
            tuple(observed[-21:]), as_of=as_of, calendar_version="ASSUMED_8H_UNVERIFIED_HISTORY"
        )
        decision = evaluate_carry(
            forecast=forecast,
            costs=costs,
            expected_basis_convergence=Decimal("0"),
            decision_time=as_of,
            evidence=CarryAdmissionEvidence(
                evidence_reference="historical two-leg execution, fees, margin and calendar evidence unavailable"
            ),
        )
        screens.append(
            {
                "decision_time": as_of,
                "expected_funding_rate_48h": forecast.expected_received_by_short,
                "expected_net_carry": decision.expected_net_carry,
                "entry_hurdle": decision.entry_hurdle,
                "economic_value_passed": decision.expected_net_carry > decision.entry_hurdle,
                "action": decision.action,
            }
        )
    table(output / "value_screen.parquet", screens)
    write_json(
        output / "admission_report.json",
        {
            "decision": "INSUFFICIENT_EVIDENCE",
            "phase_f": "INDEPENDENT_VALUE_AND_EXECUTION_GATES_IMPLEMENTED_NOT_ADMITTED",
            "public_funding_records": len(rows),
            "missing_settlement_mark": sum(not row.get("markPrice") for row in rows),
            "screened_decisions": len(screens),
            "economic_value_passes": sum(row["economic_value_passed"] for row in screens),
            "executed_orders": 0,
            "oos_profit": None,
            "independent_oos_passed": False,
            "combined_B9_run": False,
            "forecast": "fixed median of 21 settled payments, six future payments; no optimization",
            "costs": costs.model_dump(mode="json"),
            "basis_convergence_assumption": "0; no future basis profit invented",
            "limits": [
                "Funding publication latency is assumed settlement +4h, not verified historical availability.",
                "Historical margin brackets, fee tier, funding calendars and two-instrument capacity are unverified.",
                "The documented basis endpoint retains only 30 days; it cannot provide the 2022-2025 basis history.",
                "This rate-unit value screen is not a funded spot/perpetual OOS backtest; no realized profit is claimed.",
            ],
            "official_source": DOCS,
            "live_trading": False,
            "order_submission_enabled": False,
            "files_sha256": {
                name: digest(output / name)
                for name in ("public_funding_source.json", "value_screen.parquet")
            },
        },
    )
    print(f"funding records {len(rows)}, value screens {len(screens)}, admitted 0; no combination")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
