"""R4 ledger-derived attribution and paired development statistics; no strategy selection."""

from __future__ import annotations

import argparse
import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

from aegisquant.backtest.metrics import resample_equity
from aegisquant.backtest.models import BacktestFill, BacktestResult
from aegisquant.research.validation.paired_bootstrap import holm_adjust, paired_block_bootstrap
from scripts.run_alpha_r4 import BASELINE, read_result
from scripts.run_alpha_v4_audit import SYMBOLS, inputs, read_json
from scripts.run_alpha_v4_walkforward import path_metrics, table, write_json

FloatArray = NDArray[np.float64]
KEYS = ["arm", "mode", "cost_multiplier"]
ZERO = Decimal("0")


def metrics(frame: pl.DataFrame) -> dict[str, Any]:
    values = frame["equity"].to_numpy()
    returns = values[1:] / values[:-1] - 1
    exposure = frame["position_value"].to_numpy() / values
    underwater = values < np.maximum.accumulate(values)
    longest = current = 0
    for item in underwater:
        current = current + 1 if item else 0
        longest = max(longest, current)
    threshold = np.quantile(returns, 0.05)
    return {
        **path_metrics(returns),
        "initial_equity": float(values[0]),
        "final_equity": float(values[-1]),
        "net_profit": float(values[-1] - values[0]),
        "annualized_volatility": float(np.std(returns) * np.sqrt(2191.5)),
        "cvar_95_4h": float(np.mean(returns[returns <= threshold])),
        "worst_4h_return": float(np.min(returns)),
        "drawdown_duration_days": longest / 6,
        "underwater_fraction": float(np.mean(underwater)),
        "capital_weighted_exposure": float(np.mean(exposure)),
        "holding_clock_fraction": float(np.mean(exposure > 0)),
        "exposure_conditional_on_holding": float(np.mean(exposure[exposure > 0]))
        if np.any(exposure > 0)
        else 0,
        "clock_points": len(values),
    }


def execution_reason(row: dict[str, Any]) -> str:
    reason = row["reason"]
    if reason == "TREND_ENTRY_PASSED_ENABLED_GATES":
        return "FIRST_TREND_ENTRY"
    if reason == "CONFIRMED_TREND_EXIT":
        return "TREND_EXIT"
    if reason in {"COST_AWARE_RISK_REBALANCE", "DAILY_VOLATILITY_CAP"}:
        return (
            "ORDINARY_RISK_REDUCE"
            if Decimal(row["target_quantity"]) < Decimal(row["current_quantity"])
            else "ORDINARY_RISK_RESTORE"
        )
    if reason == "PREREGISTERED_FOLD_END_NEXT_OPEN_EXIT":
        return "QUARTER_EXIT"
    if reason == "EVALUATION_END_NEXT_OPEN_EXIT":
        return "EVALUATION_END"
    if reason in {"RISK_OR_DATA_VETO", "EVENT_RISK_POSITION_CAP"}:
        return "HARD_RISK_OR_DATA_EXIT"
    return reason


def fill_attribution(
    result: BacktestResult, trace: list[dict[str, Any]], arm: str, symbol: str
) -> list[dict[str, Any]]:
    by_order = {r["order_id"]: r for r in trace if r.get("order_id")}
    rows: list[dict[str, Any]] = []
    quantity = ZERO
    episode = 0
    for fill in result.fills:
        if quantity == 0:
            episode += 1
        key = str(fill.backtest_order_id)
        row = by_order[key]
        signed = fill.quantity.amount if fill.side.value == "BUY" else -fill.quantity.amount
        costs = fill.cost_breakdown
        reasons = [execution_reason(row), row["reason"]]
        if row.get("buffer_reason"):
            reasons.append(row["buffer_reason"])
        if Decimal(row.get("unexecuted_target_residual", "0")) != 0:
            reasons.append("RULE_PRECISION_OR_BUDGET_RESIDUAL")
        if row.get("cancel_pending_first"):
            reasons.append("PENDING_ORDER_RECONCILIATION")
        rows.append(
            {
                "arm": arm,
                "symbol": symbol,
                "event_time": fill.event_time,
                "decision_id": key,
                "order_id": key,
                "fill_id": str(fill.fill_id),
                "episode_id": f"{result.spec.run_id}-episode-{episode}",
                "reason_primary": reasons[0],
                "reasons_all": reasons,
                "current_qty": row["current_quantity"],
                "raw_target_qty": row.get("raw_target_quantity", row["target_quantity"]),
                "submitted_qty": row["signed_planned_quantity"],
                "filled_qty": str(signed),
                "filled_notional": str(costs.gross_notional),
                "fee_paid": str(costs.fee),
                "spread_cost": str(costs.spread),
                "slippage_cost": str(costs.slippage),
                "impact_cost": str(costs.impact),
                "total_cost": str(costs.total),
                "risk_vol_estimate": row.get("risk_vol_estimate"),
                "risk_target": row.get("risk_target"),
                "raw_risk_weight": row.get("raw_risk_weight"),
                "final_target_weight": row["final_weight"],
                "current_weight": row["current_weight"],
                "pending_qty": row["pending_quantity"],
                "calendar_review_due": row.get("rebalance_permitted"),
                "buffer_lower": row.get("buffer_lower"),
                "buffer_upper": row.get("buffer_upper"),
                "target_change_notional": str(
                    (Decimal(row["target_quantity"]) - Decimal(row["current_quantity"]))
                    * Decimal(row["known_close"])
                ),
            }
        )
        quantity += signed
        if quantity < 0:
            raise ValueError("attribution encountered a short position")
    if episode != len(result.closed_trades):
        raise ValueError("fill-derived episode count differs from the authoritative closed cycles")
    return rows


def shadow_cost(fill: BacktestFill, multiplier: Decimal) -> Decimal:
    cost = fill.cost_breakdown
    adverse = cost.spread + cost.slippage + cost.impact
    side = 1 if fill.side.value == "BUY" else -1
    rate = cost.fee / (fill.execution_price.amount * fill.quantity.amount)
    return (
        adverse * multiplier
        + (cost.gross_notional + side * adverse * multiplier) * rate * multiplier
    )


def collect(output: Path) -> tuple[pl.DataFrame, pl.DataFrame, list[dict[str, Any]]]:
    registry = read_json(output / "experiment_registry.json")
    equity_rows: list[dict[str, Any]] = []
    attributes: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    trial_totals: list[dict[str, Any]] = []
    for trial in registry["trials"]:
        if trial["status"] != "REPLAYED":
            continue
        tags = {k: trial[k] for k in (*KEYS, "symbol")}
        costs = notional = ZERO
        orders = fills = trades = rejected = 0
        mechanical = {m: ZERO for m in ("1", "1.5", "2")}
        for segment in trial["segments"]:
            folder = output / trial["output"] / segment["segment"]
            result = read_result(folder)
            curve = resample_equity(result.equity_curve, 14400)
            equity_rows.extend(
                {
                    **tags,
                    "time": p.time,
                    "cash": str(p.cash),
                    "equity": str(p.equity),
                    "position_value": str(p.position_value),
                }
                for p in curve
            )
            costs += sum((f.cost_breakdown.total for f in result.fills), ZERO)
            notional += sum((f.cost_breakdown.gross_notional for f in result.fills), ZERO)
            orders += len(result.orders)
            fills += len(result.fills)
            trades += len(result.closed_trades)
            rejected += sum(bool(o.rejection_code) for o in result.orders)
            if trial["mode"] == "REDECIDE_FUNDED" and trial["cost_multiplier"] == "1":
                trace = pl.read_parquet(folder / "decision_trace.parquet").to_dicts()
                traces.extend({"arm": trial["arm"], "symbol": trial["symbol"], **r} for r in trace)
                attributes.extend(fill_attribution(result, trace, trial["arm"], trial["symbol"]))
                for m in mechanical:
                    mechanical[m] += sum((shadow_cost(f, Decimal(m)) for f in result.fills), ZERO)
        total = {
            **tags,
            "total_cost": str(costs),
            "traded_notional": str(notional),
            "orders": orders,
            "fills": fills,
            "closed_trades": trades,
            "rejections": rejected,
            "final_cash": trial["final_cash"],
        }
        trial_totals.append(total)
        if trial["mode"] == "REDECIDE_FUNDED" and trial["cost_multiplier"] == "1":
            for multiplier, stressed_cost in mechanical.items():
                if stressed_cost < costs - Decimal("1e-8"):
                    raise ValueError("same-fill cost sensitivity improved wealth")
                trial_totals.append(
                    {
                        **total,
                        "mode": "SAME_FILL_SHADOW",
                        "cost_multiplier": multiplier,
                        "final_cash": str(Decimal(trial["final_cash"]) + costs - stressed_cost),
                        "total_cost": str(stressed_cost),
                        "funded": False,
                        "quantity_identity": "same chronological fill quantities and reference prices; no reinvestment of mechanical cost differences",
                    }
                )
    table(output / "execution_reason_attribution.parquet", attributes)
    table(output / "decision_trace.parquet", traces)
    table(output / "sleeve_results.parquet", trial_totals)
    frame = pl.DataFrame(equity_rows, infer_schema_length=None)
    duplicates = frame.group_by(*KEYS, "symbol", "time").agg(
        pl.col("equity").n_unique().alias("n"), pl.col("cash").n_unique().alias("c")
    )
    if duplicates.filter((pl.col("n") > 1) | (pl.col("c") > 1)).height:
        raise ValueError("quarter boundary has conflicting cash/MTM")
    frame = (
        frame.unique([*KEYS, "symbol", "time"])
        .with_columns(*(pl.col(k).cast(pl.Float64) for k in ("cash", "equity", "position_value")))
        .sort(*KEYS, "symbol", "time")
    )
    combined = (
        frame.group_by(*KEYS, "time")
        .agg(
            pl.col("equity").sum(),
            pl.col("cash").sum(),
            pl.col("position_value").sum(),
            pl.col("symbol").sort().alias("symbols"),
        )
        .sort(*KEYS, "time")
    )
    if any(s != sorted(SYMBOLS) for s in combined["symbols"].to_list()):
        raise ValueError("portfolio must contain exactly five independent funded sleeves")
    table(output / "portfolio_equity.parquet", combined.to_dicts())
    table(output / "sleeve_equity.parquet", frame.to_dicts())
    return frame, combined, trial_totals


def summarize_paths(
    output: Path, sleeves: pl.DataFrame, portfolio: pl.DataFrame, totals: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    annual: list[dict[str, Any]] = []
    quarters: list[dict[str, Any]] = []
    regimes: list[dict[str, Any]] = []
    for key, frame in portfolio.partition_by(KEYS, as_dict=True, maintain_order=True).items():
        arm, mode, multiplier = key
        local = [r for r in totals if (r["arm"], r["mode"], r["cost_multiplier"]) == key]
        expected = sum((Decimal(r["final_cash"]) for r in local), ZERO)
        if frame["equity"][0] != 50000 or abs(frame["equity"][-1] - float(expected)) > 1e-8:
            raise ValueError("portfolio endpoints differ from actual sleeve cash")
        row = {
            "arm": arm,
            "mode": mode,
            "cost_multiplier": multiplier,
            **metrics(frame),
            "exact_final_cash": str(expected),
            "total_cost": str(sum((Decimal(r["total_cost"]) for r in local), ZERO)),
            "traded_notional": str(sum((Decimal(r["traded_notional"]) for r in local), ZERO)),
            **{
                k: sum(r[k] for r in local)
                for k in ("orders", "fills", "closed_trades", "rejections")
            },
        }
        summaries.append(row)
        previous = 50000.0
        for (year,), part in (
            frame.with_columns(
                (pl.col("time") - pl.duration(microseconds=1)).dt.year().alias("year")
            )
            .partition_by("year", as_dict=True, maintain_order=True)
            .items()
        ):
            final = float(part["equity"][-1])
            annual.append(
                {
                    "arm": arm,
                    "mode": mode,
                    "cost_multiplier": multiplier,
                    "year": year,
                    "net_profit": final - previous,
                    "net_return": final / previous - 1,
                }
            )
            previous = final
        previous = 50000.0
        dated = frame.with_columns(
            (pl.col("time") - pl.duration(microseconds=1)).dt.strftime("%Y").alias("year"),
            ((pl.col("time") - pl.duration(microseconds=1)).dt.quarter()).alias("quarter"),
        )
        # The initial sample belongs to the first evaluation quarter, not its preceding day.
        dated = dated.filter(pl.col("time") > frame["time"][0])
        for (year, quarter), part in dated.partition_by(
            "year", "quarter", as_dict=True, maintain_order=True
        ).items():
            final = float(part["equity"][-1])
            quarters.append(
                {
                    "arm": arm,
                    "mode": mode,
                    "cost_multiplier": multiplier,
                    "year": year,
                    "quarter": quarter,
                    "net_profit": final - previous,
                    "net_return": final / previous - 1,
                }
            )
            previous = final
    for key, frame in (
        sleeves.filter((pl.col("mode") == "REDECIDE_FUNDED") & (pl.col("cost_multiplier") == "1"))
        .partition_by("arm", "symbol", as_dict=True, maintain_order=True)
        .items()
    ):
        assets.append({"arm": key[0], "symbol": key[1], **metrics(frame)})
    base = [r for r in summaries if r["mode"] == "REDECIDE_FUNDED" and r["cost_multiplier"] == "1"]
    for row in base:
        q = [
            r
            for r in quarters
            if r["arm"] == row["arm"]
            and r["mode"] == "REDECIDE_FUNDED"
            and r["cost_multiplier"] == "1"
        ]
        row["positive_quarters"] = sum(r["net_return"] > 0 for r in q)
        row["quarter_count"] = len(q)
        row["median_quarter_return"] = float(np.median([r["net_return"] for r in q]))
    # Market stages are descriptive calendar bins fixed before attribution,
    # independent of candidate winners. No asset/stage changes to any strategy.
    for row in annual:
        if row["mode"] == "REDECIDE_FUNDED" and row["cost_multiplier"] == "1":
            regimes.append(
                {
                    **row,
                    "stage": {
                        2022: "2022_DECLINE",
                        2023: "2023_RECOVERY",
                        2024: "2024_EXPANSION",
                        2025: "2025_PARTIAL_YEAR",
                    }.get(row["year"], "OTHER"),
                    "scope": "EXPLORATORY_DESCRIPTIVE_CALENDAR_ONLY",
                }
            )
    write_json(
        output / "all_results.json",
        {
            "status": "REPLAYED",
            "evidence_tier": "RETROSPECTIVE_DEVELOPMENT",
            "portfolio": summaries,
            "assets": assets,
            "annual": annual,
            "new_model_fits": 0,
            "new_calibration_fits": 0,
            "research_decision": "NO_PROVEN_ALPHA",
        },
    )
    table(output / "quarter_results.parquet", quarters)
    table(output / "market_stage_results.parquet", regimes)
    stress: list[dict[str, Any]] = []
    for key in sorted({tuple(r[k] for k in KEYS) for r in totals}):
        rows = [r for r in totals if tuple(r[k] for k in KEYS) == key]
        if len(rows) != 5:
            raise ValueError("cost scenario does not have all five sleeves")
        stress.append(
            {
                **dict(zip(KEYS, key, strict=True)),
                "final_equity": str(sum((Decimal(r["final_cash"]) for r in rows), ZERO)),
                "total_cost": str(sum((Decimal(r["total_cost"]) for r in rows), ZERO)),
                "fills": sum(r["fills"] for r in rows),
                "rejections": sum(r["rejections"] for r in rows),
                "tradeable": key[1] != "SAME_FILL_SHADOW",
            }
        )
    write_json(
        output / "cost_stress_results.json",
        {
            "scenarios": stress,
            "scope": "same-fill mechanical shadow is distinct from funded frozen-order and redecision paths",
            "identity": "fees use stressed execution notional, spread/slippage/impact use each actual fill reference notional",
        },
    )
    return base


def capital_use(output: Path, sleeves: pl.DataFrame, portfolio: pl.DataFrame) -> None:
    trace = pl.read_parquet(output / "decision_trace.parquet")
    old_trace = pl.read_parquet(BASELINE / "decision_trace.parquet").filter(
        pl.col("arm").is_in(["A3", "A7"])
    )
    trace = pl.concat([trace, old_trace], how="diagonal_relaxed")
    old_equity = (
        pl.read_parquet(BASELINE / "mtm_equity.parquet")
        .filter(pl.col("level").is_in(["A3", "A7"]))
        .rename({"level": "arm"})
        .unique(["arm", "symbol", "time"])
        .with_columns(*(pl.col(k).cast(pl.Float64) for k in ("equity", "cash", "position_value")))
    )
    base_sleeves = sleeves.filter(
        (pl.col("mode") == "REDECIDE_FUNDED") & (pl.col("cost_multiplier") == "1")
    )
    clocks = pl.concat(
        [
            base_sleeves.select("arm", "symbol", "time", "equity", "cash", "position_value"),
            old_equity.select("arm", "symbol", "time", "equity", "cash", "position_value"),
        ]
    ).sort("arm", "symbol", "time")
    rows: list[dict[str, Any]] = []
    for (arm, symbol), frame in clocks.partition_by(
        "arm", "symbol", as_dict=True, maintain_order=True
    ).items():
        local = trace.filter((pl.col("arm") == arm) & (pl.col("symbol") == symbol)).sort("time")
        candidate = local.filter(pl.col("trend_state") == "LONG")
        flat = current = longest = 0
        for value in frame["position_value"]:
            current = current + 1 if value == 0 else 0
            longest = max(longest, current)
            flat += value == 0
        row: dict[str, Any] = {
            "arm": arm,
            "symbol": symbol,
            **metrics(frame),
            "longest_flat_days": longest / 6,
            "trend_candidate_numerator": candidate.height,
            "trend_candidate_denominator": local.height,
            "model_available_numerator": candidate.filter(
                pl.col("forecast_status") != "MISSING_FORECAST"
            ).height,
            "model_available_denominator": candidate.height,
            "model_available_denominator_scope": "LONG candidate decisions, not all clock rows",
            "model_required": arm in {"A3", "A7"},
            "flat_clock_points": flat,
            "data_multiplier": 1,
            "data_multiplier_contract": "binary veto, not probabilistic rescaling",
        }
        for name in (
            "signal_filter_pass",
            "cost_filter_pass",
            "probability_filter_pass",
            "uncertainty_filter_pass",
        ):
            measurable = candidate.filter(pl.col(name).is_not_null())
            row[f"{name}_numerator"] = measurable.filter(pl.col(name)).height
            row[f"{name}_denominator"] = measurable.height
        for source, dest in (
            ("risk_only_weight", "mean_raw_risk_weight"),
            ("confidence_multiplier", "mean_probability_multiplier"),
            ("final_weight", "mean_final_target_weight"),
            ("current_weight", "mean_actual_weight_at_decision"),
        ):
            value = candidate[source].cast(pl.Float64).mean() if candidate.height else None
            row[dest] = value
        means = (
            local.select(
                (
                    pl.col("current_weight").cast(pl.Float64)
                    * pl.col("risk_vol_estimate").cast(pl.Float64)
                ).mean()
            ).item()
            if "risk_vol_estimate" in candidate.columns
            else None
        )
        row["mean_estimated_sleeve_risk_on_observed_decisions"] = means
        row["realized_minus_mean_estimated_sleeve_vol_descriptive"] = (
            row["annualized_volatility"] - means if means is not None else None
        )
        row["risk_diagnostic_limit"] = (
            "mean decision-time weight * sleeve vol versus full-clock realized sleeve vol; descriptive, not a calibrated risk forecast or portfolio covariance estimate"
        )
        row["filter_interactions"] = (
            "individual conditional rates, no product-of-means causal decomposition"
        )
        rows.append(row)
    combined = (
        clocks.group_by("arm", "time")
        .agg(pl.col("equity").sum(), pl.col("cash").sum(), pl.col("position_value").sum())
        .sort("arm", "time")
    )
    for (arm,), frame in combined.partition_by("arm", as_dict=True, maintain_order=True).items():
        rows.append(
            {
                "arm": arm,
                "symbol": "PORTFOLIO",
                **metrics(frame),
                "filter_interactions": "full-clock sum(position value)/sum(equity), never mean sleeve percentages",
            }
        )
    table(output / "capital_use_decomposition.parquet", rows)


def reason_audit(output: Path) -> dict[str, Any]:
    data = pl.read_parquet(output / "execution_reason_attribution.parquet").with_columns(
        *(pl.col(k).cast(pl.Float64) for k in ("filled_notional", "total_cost", "filled_qty"))
    )
    rows: list[dict[str, Any]] = []
    for (arm, reason), part in data.partition_by("arm", "reason_primary", as_dict=True).items():
        amounts = part["filled_notional"].to_numpy()
        rows.append(
            {
                "arm": arm,
                "reason_primary": reason,
                "orders": part["order_id"].n_unique(),
                "fills": part.height,
                "episodes_touched": part["episode_id"].n_unique(),
                "notional": float(np.sum(amounts)),
                "cost": float(part["total_cost"].sum()),
                "order_notional_p10_p50_p90": np.quantile(amounts, [0.1, 0.5, 0.9]).tolist(),
            }
        )
    reverse: list[dict[str, Any]] = []
    for (arm, symbol), part in (
        data.filter(
            pl.col("reason_primary").is_in(["ORDINARY_RISK_REDUCE", "ORDINARY_RISK_RESTORE"])
        )
        .sort("event_time")
        .partition_by("arm", "symbol", as_dict=True, maintain_order=True)
        .items()
    ):
        orders = part.to_dicts()
        for horizon in (24, 48):
            # Each later order counted once; this is a diagnostic amount, not
            # an allegation that every nearby reversal was avoidable.
            notional = sum(
                r["filled_notional"]
                for i, r in enumerate(orders)
                if any(
                    0 <= (r["event_time"] - earlier["event_time"]).total_seconds() <= horizon * 3600
                    and r["filled_qty"] * earlier["filled_qty"] < 0
                    for earlier in orders[:i]
                )
            )
            reverse.append(
                {
                    "arm": arm,
                    "symbol": symbol,
                    "hours": horizon,
                    "later_opposing_order_notional": notional,
                }
            )
    table(output / "execution_reason_summary.parquet", rows)
    table(output / "risk_resize_reversals.parquet", reverse)
    status = {
        "status": "AUDITED",
        "bugfix_bridge_required": False,
        "findings": {
            "hold_quantity": "HOLD uses actual quantity; no repeated 0.99 in audited path",
            "double_risk_scaling": "not observed; reserve clamps affordability once",
            "clock": "86400s since last submitted order; preserved",
            "pending": "original signed-pending manager retained; IOC completes or cancels at each market event",
            "precision_residual": "logged, minimum-notional dust escalated; never booked as flat",
            "partial_fill_episode": "fill-derived episodes exactly matched engine closed cycles",
        },
        "limits": "no historical orderbook evidence; reversal amount is descriptive, not a confirmed bug",
    }
    write_json(output / "risk_rebalance_audit.json", status)
    return status


def automatic_block(values: FloatArray) -> float:
    """Stationary length from tapered autocovariances (Politis/White correction).

    Uses the formula documented by arch, with an explicit constant-series guard.
    The existing paired circular sampler consumes the conservatively rounded max.
    """
    x = values - np.mean(values)
    count = len(x)
    if count < 20 or float(x @ x) < 1e-24:
        return 2.0
    quiet = max(5, int(np.log10(count)))
    maximum = min(count - 2, int(np.ceil(np.sqrt(count))) + quiet)
    covariance = np.array([float(x[k:] @ x[: count - k]) / count for k in range(maximum + 1)])
    correlation = np.array(
        [
            abs(float(x[k:] @ x[: count - k]))
            / max(
                1e-30, float(np.sqrt((x[k + 1 :] @ x[k + 1 :]) * (x[: -(k + 1)] @ x[: -(k + 1)])))
            )
            for k in range(maximum + 1)
        ]
    )
    cutoff = 2 * np.sqrt(np.log10(count) / count)
    silent = next(
        (
            i - quiet
            for i in range(quiet, maximum + 1)
            if np.all(correlation[i - quiet : i] < cutoff)
        ),
        None,
    )
    span = min(maximum, 2 * max(1, silent)) if silent is not None else maximum
    lag = np.arange(1, span + 1)
    taper = np.minimum(1.0, 2 * (1 - lag / span))
    long_variance = covariance[0] + 2 * float(taper @ covariance[1 : span + 1])
    weighted = 2 * float((lag * taper) @ covariance[1 : span + 1])
    estimate = (count * weighted**2 / max(long_variance**2, 1e-30)) ** (1 / 3)
    return min(max(2.0, estimate), float(np.ceil(min(3 * np.sqrt(count), count / 3))))


def paired_statistics(output: Path, portfolio: pl.DataFrame) -> dict[str, Any]:
    config = read_json(output / "effective_config.json")["bootstrap"]
    selected = portfolio.filter(
        (pl.col("mode") == "REDECIDE_FUNDED")
        & (pl.col("cost_multiplier") == "1")
        & (pl.col("time").dt.hour() == 0)
    ).sort("arm", "time")
    frame = selected.pivot(on="arm", index="time", values="equity").sort("time")
    arms = sorted(c for c in frame.columns if c != "time")
    if frame.select(pl.any_horizontal(pl.all().is_null())).to_series().any():
        raise ValueError("paired statistics require a common complete daily clock")
    wealth = frame.select(arms).to_numpy()
    returns = wealth[1:] / wealth[:-1] - 1
    dollars = np.diff(wealth, axis=0)
    rules = {
        arm: {
            "return": automatic_block(returns[:, i]),
            "squared_return": automatic_block(returns[:, i] ** 2),
        }
        for i, arm in enumerate(arms)
    }
    length = min(len(returns) // 4, math.ceil(max(v for r in rules.values() for v in r.values())))
    draw = paired_block_bootstrap(
        returns, repetitions=config["repetitions"], block_bars=length, seed=config["seed"]
    )
    # Reuse the exact same draw indices by rerunning the deterministic sampler.
    # Scale dollars only to satisfy its > -1 numerical domain; means are linear.
    scale = max(50000.0, 2 * float(np.max(np.abs(dollars))))
    dollar_draw = paired_block_bootstrap(
        dollars / scale, repetitions=config["repetitions"], block_bars=length, seed=config["seed"]
    )
    comparisons: dict[str, Any] = {}
    daily: list[dict[str, Any]] = []
    for name in config["comparisons"]:
        candidate, base = name.split("-")
        if candidate not in arms or base not in arms:
            continue
        i, j = arms.index(candidate), arms.index(base)
        delta_samples = (
            (dollar_draw.mean_returns[:, i] - dollar_draw.mean_returns[:, j]) * scale * len(dollars)
        )
        comparisons[name] = {
            **draw.difference(i, j),
            "final_dollar_difference": float(wealth[-1, i] - wealth[-1, j]),
            "paired_sum_daily_dollar_ci95": np.quantile(delta_samples, [0.025, 0.975]).tolist(),
        }
        daily.extend(
            {
                "comparison": name,
                "time": t,
                "net_pnl_difference_usdt": float(a - b),
                "return_difference": float(ra - rb),
            }
            for t, a, b, ra, rb in zip(
                frame["time"].to_list()[1:],
                dollars[:, i],
                dollars[:, j],
                returns[:, i],
                returns[:, j],
                strict=True,
            )
        )
    p_values = holm_adjust({k: v["one_sided_mean_p_value"] for k, v in comparisons.items()})
    for name, adjusted in p_values.items():
        comparisons[name]["holm_adjusted_p_value"] = adjusted
    interaction = None
    if all(a in arms for a in ("F0", "F1", "F2", "F3")):
        a, b, c, d = (arms.index(n) for n in ("F0", "F1", "F2", "F3"))
        sampled = (
            (
                dollar_draw.mean_returns[:, d]
                - dollar_draw.mean_returns[:, c]
                - dollar_draw.mean_returns[:, b]
                + dollar_draw.mean_returns[:, a]
            )
            * scale
            * len(dollars)
        )
        interaction = {
            "definition": "F3-F2-F1+F0, paired daily dollar differences",
            "observed_usdt": float(wealth[-1, d] - wealth[-1, c] - wealth[-1, b] + wealth[-1, a]),
            "ci95_usdt": np.quantile(sampled, [0.025, 0.975]).tolist(),
        }
    result = {
        "status": "DEVELOPMENT_UNCERTAINTY_ONLY",
        "method": "common-index circular block bootstrap; maximum automatically estimated stationary length across returns and squared returns",
        "reference": "https://arch.readthedocs.io/en/latest/bootstrap/generated/arch.bootstrap.optimal_block_length.html",
        "block_length_days": length,
        "automatic_estimates": rules,
        "repetitions": config["repetitions"],
        "seed": config["seed"],
        "comparisons": comparisons,
        "factor_interaction": interaction,
        "dsr_pbo": "INSUFFICIENT_EVIDENCE_COMPLETE_INDEPENDENT_TRIAL_HISTORY_UNAVAILABLE",
        "holdout": "NOT_ALLOCATED_NOT_ACCESSED",
        "resampling_scope": "joint portfolio strategy columns formed from five same-clock sleeves; cross-asset and cross-strategy co-movement retained",
    }
    write_json(output / "paired_statistics.json", result)
    table(output / "paired_daily_differences.parquet", daily)
    return result


def opportunities(output: Path) -> None:
    traces = pl.read_parquet(BASELINE / "decision_trace.parquet")
    equity = pl.read_parquet(BASELINE / "mtm_equity.parquet")
    rows: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        _, _, bars, features, _, _, _, indices, _ = inputs(symbol)
        a1 = (
            traces.filter((pl.col("arm") == "A1") & (pl.col("symbol") == symbol))
            .sort("time")
            .to_dicts()
        )
        by_time = {
            arm: {
                r["time"]: r
                for r in traces.filter(
                    (pl.col("arm") == arm) & (pl.col("symbol") == symbol)
                ).to_dicts()
            }
            for arm in ("A3", "A7")
        }
        clocks = {
            arm: equity.filter((pl.col("level") == arm) & (pl.col("symbol") == symbol))
            .unique("time")
            .sort("time")
            for arm in ("A1", "A3", "A7")
        }
        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for r in a1:
            if r["trend_state"] == "LONG":
                current.append(r)
            elif current:
                groups.append([*current, r])
                current = []
        if current:
            groups.append(current)
        for number, group in enumerate(groups, 1):
            first, last = group[0], group[-1]
            begin = indices[first["time"]] + 1
            end = min(indices[last["time"]] + 1, len(bars) - 1)
            if begin >= len(bars) or end <= begin:
                continue
            entry, exit_price = bars[begin].open, bars[end].open
            # Same 1,000-USDT notional on each primary opportunity. Actual next
            # opens are hindsight outcomes; costs remain explicitly proxy-based.
            cost_rate = Decimal("0")
            for i in (begin, end):
                natr = Decimal(str(float(features.values[max(i - 1, 0), 9])))
                participation = Decimal("1000") / (bars[i].open * bars[i].volume)
                cost_rate += (
                    Decimal("14") + 100 * natr + 25 * min(Decimal("1"), participation)
                ) / 10000
            shadow = Decimal("1000") * (exit_price / entry - 1 - cost_rate)
            outcomes = {}
            for arm, frame in clocks.items():
                selected = frame.filter(
                    (pl.col("time") >= bars[begin].event_time)
                    & (pl.col("time") <= bars[end].event_time)
                )
                outcomes[arm] = (
                    float(Decimal(selected["equity"][-1]) - Decimal(selected["equity"][0]))
                    if selected.height > 1
                    else None
                )
            for arm in ("A3", "A7"):
                observed = [by_time[arm][r["time"]] for r in group if r["time"] in by_time[arm]]
                entries = [
                    r
                    for r in observed
                    if Decimal(r["signed_planned_quantity"]) > 0
                    and Decimal(r["actual_fill_notional"]) > 0
                    and Decimal(r["current_quantity"]) == 0
                ]
                missing = sum(r["forecast_status"] == "MISSING_FORECAST" for r in observed)
                accepted = bool(entries)
                delay = (
                    (entries[0]["time"] - first["time"]).total_seconds() / 3600 if entries else None
                )
                classification = (
                    "ACCEPTED"
                    if accepted and delay == 0
                    else "DELAYED"
                    if accepted
                    else "SKIPPED_UNAVAILABLE"
                    if missing == len(observed)
                    else "REJECTED_ENTIRE_OPPORTUNITY"
                )
                rows.append(
                    {
                        "symbol": symbol,
                        "arm": arm,
                        "episode_id": f"{symbol}-A1-opportunity-{number}",
                        "start": first["time"],
                        "end": last["time"],
                        "classification": classification,
                        "entry_delay_hours": delay,
                        "model_missing_numerator": missing,
                        "model_missing_denominator": len(observed),
                        "primary_shadow_notional": "1000",
                        "primary_shadow_net_pnl": str(shadow),
                        "shadow_cost_identity": "two causal proxy rates at observed 1,000-USDT order notionals, arithmetic attribution only; not a funded engine trade",
                        "missed_positive_shadow": str(max(ZERO, shadow)) if not accepted else "0",
                        "avoided_negative_shadow": str(max(ZERO, -shadow)) if not accepted else "0",
                        "funded_a1_interval_pnl": outcomes["A1"],
                        "funded_comparator_interval_pnl": outcomes[arm],
                        "funded_interval_pnl_difference": outcomes[arm] - outcomes["A1"]
                        if outcomes[arm] is not None and outcomes["A1"] is not None
                        else None,
                        "a1_holding_decisions": sum(
                            Decimal(r["current_quantity"]) > 0 for r in group
                        ),
                        "comparator_holding_decisions": sum(
                            Decimal(r["current_quantity"]) > 0 for r in observed
                        ),
                        "mean_comparator_actual_weight": float(
                            np.mean([float(r["current_weight"]) for r in observed])
                        ),
                        "attribution_limit": "mixed ML entry/cost changes plus delay, exposure and compounding; not isolated XGBoost effect",
                    }
                )
    table(output / "opportunity_attribution.parquet", rows)


def readiness_diagnostics(output: Path, sleeves: pl.DataFrame) -> None:
    rows: list[dict[str, Any]] = []
    intervals: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        file = output / "runs/F4" / symbol / "REDECIDE_FUNDED_1/signal_readiness.parquet"
        if not file.exists():
            continue
        readiness = pl.read_parquet(file).sort("time")
        local = (
            sleeves.filter(
                (pl.col("symbol") == symbol)
                & (pl.col("mode") == "REDECIDE_FUNDED")
                & (pl.col("cost_multiplier") == "1")
                & pl.col("arm").is_in(["F3", "F4"])
            )
            .pivot(on="arm", index="time", values="equity")
            .sort("time")
        )
        if "F3" not in local.columns or "F4" not in local.columns:
            continue
        # An outcome over (t, t+4h] is grouped by readiness already known at t.
        local = local.with_columns(
            pl.col("F3").diff().alias("f3_pnl"),
            pl.col("F4").diff().alias("f4_pnl"),
            pl.col("time").shift(1).alias("interval_start"),
        ).drop_nulls("interval_start")
        aligned = local.join_asof(
            readiness,
            left_on="interval_start",
            right_on="time",
            strategy="backward",
            suffix="_readiness",
        )
        for available in (True, False):
            group = aligned.filter(pl.col("all_ready").fill_null(False) == available)
            rows.append(
                {
                    "symbol": symbol,
                    "all_signals_ready_at_interval_start": available,
                    "intervals": group.height,
                    "denominator_all_intervals": aligned.height,
                    "f3_actual_pnl_usdt": float(group["f3_pnl"].sum()),
                    "f4_actual_pnl_usdt": float(group["f4_pnl"].sum()),
                    "paired_actual_pnl_difference_usdt": float(
                        (group["f4_pnl"] - group["f3_pnl"]).sum()
                    ),
                    "interpretation": "descriptive common-ready opportunity axis of actual funded paths; no capital reset or truncated strategy rerun",
                }
            )
        intervals.extend(
            {
                "symbol": symbol,
                "time": r["time"],
                "interval_start": r["interval_start"],
                "all_ready": r["all_ready"],
                "f3_pnl": r["f3_pnl"],
                "f4_pnl": r["f4_pnl"],
            }
            for r in aligned.to_dicts()
        )
        for name in ("ready_10_40", "ready_20_80", "ready_40_160"):
            rows.append(
                {
                    "symbol": symbol,
                    "component": name,
                    "ready_numerator": int(readiness[name].sum()),
                    "ready_denominator": readiness.height,
                    "policy": "all three must be ready; missing longest window does not reallocate budget to shorter windows",
                }
            )
    table(output / "signal_readiness_diagnostics.parquet", rows)
    table(output / "common_ready_intervals.parquet", intervals)


def run(output: Path) -> None:
    sleeves, portfolio, totals = collect(output)
    base = summarize_paths(output, sleeves, portfolio, totals)
    capital_use(output, sleeves, portfolio)
    reason_audit(output)
    paired_statistics(output, portfolio)
    opportunities(output)
    readiness_diagnostics(output, sleeves)
    print(json.dumps(base, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output.resolve())
