"""Carry actual cash through costed quarterly exits; causal covariance is a separate arm."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import numpy as np

from aegisquant.research.validation.calendar_walkforward import CalendarFold
from aegisquant.research.validation.cat_contract import audit_arms
from aegisquant.research.validation.cat_replay import replay_cat
from scripts.export_alpha_v4_audit_bundle import digest
from scripts.run_alpha_v4_audit import (
    OUTPUT,
    ROOT,
    SYMBOLS,
    AuditInputs,
    inputs,
    make_spec,
    read_json,
    save_result,
    trial_collections,
)
from scripts.run_alpha_v4_walkforward import table, write_json


def covariance_caps(
    data: dict[str, AuditInputs], fold: CalendarFold, capital: dict[str, Decimal]
) -> tuple[dict[str, Decimal], dict[str, Any]]:
    changes: dict[str, dict[datetime, float]] = {}
    for symbol, (_, _, bars, *_) in data.items():
        changes[symbol] = {
            bars[i].available_time: float(bars[i].close / bars[i - 1].close - 1)
            for i in range(1, len(bars))
            if bars[i].available_time < fold.test_start
            and (bars[i].event_time - bars[i - 1].event_time).total_seconds() == 14400
        }
    clock = sorted(
        set(changes[SYMBOLS[0]]).intersection(*(set(values) for values in changes.values()))
    )[-180:]
    if len(clock) < 180:
        raise ValueError("insufficient common mature covariance history")
    matrix = np.column_stack([[changes[symbol][time] for time in clock] for symbol in SYMBOLS])
    sample = np.cov(matrix, rowvar=False, ddof=1) * 2191.5
    covariance = 0.5 * sample + 0.5 * np.diag(np.diag(sample))
    inverse_vol = 1 / np.sqrt(np.maximum(np.diag(covariance), 1e-12))
    weights = inverse_vol / np.sum(inverse_vol)
    risk = float(np.sqrt(weights @ covariance @ weights))
    allocation = weights * min(1.0, 0.20 / risk)
    total = sum(capital.values())
    caps = {
        symbol: min(Decimal("1"), Decimal(str(allocation[i])) * total / capital[symbol])
        for i, symbol in enumerate(SYMBOLS)
    }
    return caps, {
        "fold_id": fold.fold_id,
        "known_through": clock[-1],
        "observations": 180,
        "shrinkage": 0.5,
        "covariance_annual": covariance.tolist(),
        "initial_cash_weights": {s: str(capital[s] / total) for s in SYMBOLS},
        "maximum_sleeve_weights": {s: str(caps[s]) for s in SYMBOLS},
        "risk_before_local_band_controls": float(np.sqrt(allocation @ covariance @ allocation)),
        "assumption": "quarter-start covariance cap; realized equity drifts, no claim of continuously enforced covariance target",
    }


def main() -> None:
    output = OUTPUT / "continuous"
    if output.exists():
        raise FileExistsError("continuous audit is already recorded")
    output.mkdir()
    config = read_json(OUTPUT / "preregistration.json")
    data = {symbol: inputs(symbol) for symbol in SYMBOLS}
    collection = trial_collections()
    transitions: list[dict[str, Any]] = []
    covariance_records: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    capital = {
        arm: {symbol: Decimal("10000") for symbol in SYMBOLS}
        for arm in ("A1_CONTINUOUS", "A1_COVARIANCE")
    }
    for number, fold in enumerate(data[SYMBOLS[0]][6], 1):
        print(f"continuous money {number}/14 {fold.fold_id}", flush=True)
        caps, covariance_record = covariance_caps(data, fold, capital["A1_COVARIANCE"])
        covariance_records.append(covariance_record)
        for arm in capital:
            for symbol in SYMBOLS:
                source, market, bars, features, _, _, folds, indices, trend = data[symbol]
                local_fold = folds[number - 1]
                if local_fold.fold_id != fold.fold_id:
                    raise ValueError("cross-asset calendar mismatch")
                selected = tuple(b for b in bars if fold.test_start <= b.event_time < fold.test_end)
                allowed = set(local_fold.test_indices)
                targets = {
                    time: value and indices[time] in allowed for time, value in trend.items()
                }
                initial = capital[arm][symbol]
                result, trace = replay_cat(
                    root=ROOT,
                    spec=make_spec(symbol, fold, arm, source, config, initial),
                    bars=selected,
                    features=features,
                    feature_indices=indices,
                    trend_by_time=targets,
                    forecasts={},
                    level=arm,
                    audit_policy=audit_arms()["A1"],
                    market_spec=market,
                    risk_weight_caps={b.available_time: caps[symbol] for b in selected}
                    if arm == "A1_COVARIANCE"
                    else None,
                )
                if result.positions[-1].quantity != 0:
                    raise ValueError(
                        "continuous cash transition requires a real costed flat position"
                    )
                save_result(collection, result, fold, arm)
                # append_result keys omit symbol; attach it only to newly appended records.
                for rows in collection.values():
                    for row in rows:
                        if "symbol" not in row:
                            row["symbol"] = symbol
                final = result.mark_to_market_final_equity
                if final is None:
                    raise ValueError("continuous account has no terminal valuation")
                capital[arm][symbol] = final
                transitions.append(
                    {
                        "symbol": symbol,
                        "fold_id": fold.fold_id,
                        "arm": arm,
                        "initial_actual_cash": str(initial),
                        "final_actual_cash": str(final),
                        "external_flows": "0",
                        "cross_sleeve_transfers": "0",
                        "flat_after_costed_exit": True,
                        "total_cost": str(
                            result.pnl_attribution[-1].gross_trading_pnl
                            - result.pnl_attribution[-1].net_pnl
                        ),
                        "cost_identity_residual": str(result.cost_identity_residual),
                        "maximum_fill_participation": str(
                            max(
                                (f.quantity.amount / f.available_liquidity for f in result.fills),
                                default=Decimal("0"),
                            )
                        ),
                    }
                )
                traces.extend(
                    {"symbol": symbol, "fold_id": fold.fold_id, "arm": arm, **row} for row in trace
                )
    for name, rows in collection.items():
        table(output / f"{name}.parquet", rows)
    table(output / "cash_transitions.parquet", transitions)
    table(output / "decision_trace.parquet", traces)
    write_json(output / "covariance_budget.json", covariance_records)
    write_json(
        output / "completion.json",
        {
            "status": "COMPLETE_RESEARCH_ONLY",
            "initial_total_cash": "50000",
            "terminal_actual_cash": {
                arm: str(sum(values.values())) for arm, values in capital.items()
            },
            "files": {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file()},
            "quarter_liquidation": "paid; next quarter uses actual remaining money, not reset/reweighted returns",
            "capacity": "participation proxy recomputed for actual current cash; no larger-capital proof",
        },
    )


if __name__ == "__main__":
    main()
