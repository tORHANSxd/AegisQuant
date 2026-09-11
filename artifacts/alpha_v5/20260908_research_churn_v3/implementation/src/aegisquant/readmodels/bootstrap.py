"""Rebuild the P14 development Read Model from verified prior-phase artifacts."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import polars as pl
from pydantic import JsonValue

from aegisquant.data.hashing import canonical_sha256, sha256_file
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import ensure_utc
from aegisquant.readmodels.engine import ProjectionEngine
from aegisquant.readmodels.models import (
    AccountOverviewPayload,
    ClaimEvidencePayload,
    DailyPnLPayload,
    DataHealthPayload,
    EventImpactPayload,
    ModelPayload,
    NarrativePayload,
    OrderPayload,
    PositionPayload,
    ProjectionEvent,
    ProjectionKind,
    ProjectionSnapshot,
    QualityState,
    RiskSummaryPayload,
    SourcePolicyPayload,
    StrategyPayload,
    TimeValuePoint,
)

PROJECTED_AT = datetime(2026, 9, 1, 21, 50, tzinfo=UTC)


def _json(path: Path) -> dict[str, JsonValue]:
    return cast("dict[str, JsonValue]", json.loads(path.read_text(encoding="utf-8")))


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("artifact time must be an ISO-8601 string")
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _decimal(value: object) -> Decimal:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise TypeError("artifact decimal must be a string or integer")
    return Decimal(value)


def _risk_state(value: object) -> Literal["NORMAL", "CAUTION", "REDUCE_ONLY", "HALTED"]:
    if value not in {"NORMAL", "CAUTION", "REDUCE_ONLY", "HALTED"}:
        raise ValueError("unsupported risk state in source artifact")
    return cast('Literal["NORMAL", "CAUTION", "REDUCE_ONLY", "HALTED"]', value)


def _side(value: object) -> Literal["BUY", "SELL"]:
    if value not in {"BUY", "SELL"}:
        raise ValueError("unsupported order side in source artifact")
    return cast('Literal["BUY", "SELL"]', value)


def _event_status(
    value: object,
) -> Literal["FORMING", "CONFIRMED", "REFUTED", "RESOLVED"]:
    if value not in {"FORMING", "CONFIRMED", "REFUTED", "RESOLVED"}:
        raise ValueError("unsupported event status in source artifact")
    return cast('Literal["FORMING", "CONFIRMED", "REFUTED", "RESOLVED"]', value)


def _relation(value: object) -> Literal["SUPPORTS", "REFUTES"]:
    if value not in {"SUPPORTS", "REFUTES"}:
        raise ValueError("unsupported evidence relation in source artifact")
    return cast('Literal["SUPPORTS", "REFUTES"]', value)


def build_projection_events(root: Path) -> tuple[ProjectionEvent, ...]:
    """Translate existing audited artifacts into ordered projection facts."""
    root = root.resolve()
    events: list[ProjectionEvent] = []

    def add(
        *,
        projection: ProjectionKind,
        entity_id: str,
        as_of_time: datetime,
        source: Path,
        payload: DomainModel,
        quality: QualityState = QualityState.STALE,
        authoritative: bool = True,
        estimated: bool = False,
    ) -> None:
        relative = source.resolve().relative_to(root).as_posix()
        dumped = cast("dict[str, JsonValue]", payload.model_dump(mode="json"))
        sequence = len(events) + 1
        events.append(
            ProjectionEvent(
                event_id=f"p14:{projection.value}:{entity_id}",
                sequence=sequence,
                projection=projection,
                entity_id=entity_id,
                as_of_time=as_of_time,
                available_at=as_of_time,
                quality_state=quality,
                authoritative=authoritative,
                estimated=estimated,
                source_artifact=relative,
                source_sha256=sha256_file(source),
                payload=dumped,
                payload_sha256=canonical_sha256(dumped),
            )
        )

    backtest = root / "reports/backtests/p06-golden"
    equity_path = backtest / "equity_curve.parquet"
    equity_rows = pl.read_parquet(equity_path).to_dicts()
    if not equity_rows:
        raise ValueError("P06 equity artifact is empty")
    equity_curve = tuple(
        TimeValuePoint(time=_time(row["time"]), value=_decimal(row["equity"]))
        for row in equity_rows
    )
    final_equity = equity_rows[-1]
    final_time = _time(final_equity["time"])
    account_id = "paper-account"
    add(
        projection=ProjectionKind.ACCOUNT_OVERVIEW,
        entity_id=account_id,
        as_of_time=final_time,
        source=equity_path,
        payload=AccountOverviewPayload(
            account_id=account_id,
            environment="RESEARCH",
            reporting_asset_id=cast("str", final_equity["reporting_asset_id"]),
            equity=_decimal(final_equity["equity"]),
            cash=_decimal(final_equity["cash"]),
            gross_exposure=_decimal(0),
            net_exposure=_decimal(0),
            leverage=_decimal(0),
            margin_utilization=_decimal(0),
            open_order_count=0,
            unknown_order_count=0,
            last_reconciliation_at=final_time,
            live_trading_locked=True,
            equity_curve=equity_curve,
            source_scope="P06 deterministic historical replay",
        ),
    )

    attribution_path = backtest / "pnl_attribution.parquet"
    attribution_rows = pl.read_parquet(attribution_path).to_dicts()
    if len(attribution_rows) != 1:
        raise ValueError("P06 PnL attribution must contain exactly one aggregate row")
    attribution = attribution_rows[0]
    starting_equity = cast("str", equity_rows[0]["equity"])
    pnl_curve = tuple(
        TimeValuePoint(
            time=_time(row["time"]),
            value=Decimal(cast("str", row["equity"])) - Decimal(starting_equity),
        )
        for row in equity_rows
    )
    add(
        projection=ProjectionKind.DAILY_PNL,
        entity_id=f"{account_id}:2026-09-01",
        as_of_time=_time(attribution["time"]),
        source=attribution_path,
        payload=DailyPnLPayload(
            account_id=account_id,
            business_date=date(2026, 9, 1),
            reporting_asset_id="USDT",
            realized=_decimal(attribution["gross_trading_pnl"]),
            unrealized=_decimal(0),
            fees=_decimal(attribution["trading_fees"]),
            funding=_decimal(attribution["funding"]),
            net=_decimal(attribution["net_pnl"]),
            pnl_curve=pnl_curve,
            source_scope="P06 deterministic historical replay",
        ),
    )

    positions_path = backtest / "positions.parquet"
    for row in pl.read_parquet(positions_path).to_dicts():
        instrument_id = cast("str", row["instrument_id"])
        add(
            projection=ProjectionKind.POSITIONS_CURRENT,
            entity_id=f"{account_id}:{instrument_id}",
            as_of_time=_time(row["time"]),
            source=positions_path,
            payload=PositionPayload(
                position_id=f"{account_id}:{instrument_id}",
                account_id=account_id,
                instrument_id=instrument_id,
                strategy_id="p06-buy-hold",
                quantity=_decimal(row["quantity"]),
                average_entry_price=(
                    _decimal(row["average_entry_price"])
                    if row["average_entry_price"] is not None
                    else None
                ),
                mark_price=_decimal(row["mark_price"]),
                unrealized_pnl=_decimal(row["unrealized_pnl"]),
                reporting_asset_id="USDT",
                source_scope="P06 deterministic historical replay",
            ),
        )

    risk_path = root / "reports/data/P11_RISK_DECISION_EVIDENCE.json"
    risk_evidence = _json(risk_path)
    risk_snapshot = cast("dict[str, JsonValue]", risk_evidence["snapshot"])
    risk_decision = cast("dict[str, JsonValue]", risk_evidence["approved_decision"])
    add(
        projection=ProjectionKind.RISK_SUMMARY,
        entity_id=account_id,
        as_of_time=_time(risk_snapshot["as_of_time"]),
        source=risk_path,
        payload=RiskSummaryPayload(
            account_id=account_id,
            state=_risk_state(risk_decision["state"]),
            daily_pnl_fraction=_decimal(risk_snapshot["daily_pnl_fraction"]),
            drawdown_fraction=_decimal(risk_snapshot["drawdown_fraction"]),
            gross_weight=_decimal(risk_snapshot["portfolio_gross_weight"]),
            margin_utilization=_decimal(risk_snapshot["margin_utilization"]),
            liquidity_score=_decimal(risk_snapshot["liquidity_score"]),
            new_risk_allowed=cast("bool", risk_decision["new_risk_allowed"]),
            ledger_reconciled=cast("bool", risk_snapshot["ledger_reconciled"]),
            reason_codes=tuple(cast("list[str]", risk_decision["reason_codes"])),
            source_snapshot_sha256=cast("str", risk_snapshot["snapshot_sha256"]),
        ),
    )

    manifest_path = backtest / "run_manifest.json"
    metrics_path = backtest / "metrics.json"
    manifest = _json(manifest_path)
    metrics = _json(metrics_path)
    add(
        projection=ProjectionKind.STRATEGIES,
        entity_id=cast("str", manifest["strategy_id"]),
        as_of_time=_time(manifest["end_time"]),
        source=manifest_path,
        payload=StrategyPayload(
            strategy_id=cast("str", manifest["strategy_id"]),
            version=cast("str", manifest["strategy_version_id"]),
            status="RESEARCH",
            reporting_asset_id="USDT",
            net_pnl=_decimal(attribution["net_pnl"]),
            maximum_drawdown=_decimal(metrics["maximum_drawdown"]),
            turnover=_decimal(metrics["turnover"]),
            current_signal=_decimal(0),
            model_id="linear-fair",
            production_alpha_claimed=False,
        ),
    )

    model_path = root / "reports/data/P07_MODEL_EVIDENCE.json"
    model_evidence = _json(model_path)
    evaluation = cast(
        "dict[str, JsonValue]", cast("list[JsonValue]", model_evidence["fair_evaluations"])[0]
    )
    add(
        projection=ProjectionKind.MODELS,
        entity_id=cast("str", evaluation["model_id"]),
        as_of_time=final_time,
        source=model_path,
        payload=ModelPayload(
            model_id=cast("str", evaluation["model_id"]),
            family="LINEAR",
            version="p07-fair-v1",
            status="BASELINE",
            metric_name="mean_squared_error",
            metric_value=_decimal(evaluation["mean_squared_error"]),
            observations=cast("int", evaluation["observations"]),
            modality=cast("str", evaluation["modality"]),
            final_holdout_opened=False,
            live_calibration_claimed=False,
        ),
    )

    orders_path = backtest / "orders.parquet"
    for row in pl.read_parquet(orders_path).to_dicts():
        order_id = cast("str", row["backtest_order_id"])
        add(
            projection=ProjectionKind.ORDERS,
            entity_id=order_id,
            as_of_time=_time(row["completed_at"]),
            source=orders_path,
            payload=OrderPayload(
                order_id=order_id,
                account_id=account_id,
                strategy_id="p06-buy-hold",
                instrument_id=cast("str", row["instrument_id"]),
                venue_id=cast("str", row["venue_id"]),
                side=_side(row["side"]),
                order_type=cast("str", row["order_type"]),
                quantity=_decimal(row["quantity"]),
                filled_quantity=_decimal(row["cumulative_filled_quantity"]),
                average_fill_price=(
                    _decimal(row["average_fill_price"])
                    if row["average_fill_price"] is not None
                    else None
                ),
                status=cast("str", row["status"]),
                submitted_at=_time(row["submitted_at"]),
                completed_at=_time(row["completed_at"]),
                virtual=True,
            ),
        )

    intelligence_path = root / "reports/intelligence/P10_READ_MODELS.json"
    intelligence = _json(intelligence_path)
    intelligence_as_of = _time(intelligence["generated_as_of"])
    for source_state in cast("list[dict[str, JsonValue]]", intelligence["source_monitor"]):
        source_id = cast("str", source_state["source"])
        ready = source_state["runtime_state"] == "READY"
        data_state = "STALE" if ready else "DEGRADED"
        reasons = tuple(cast("list[str]", source_state["reason_codes"]))
        add(
            projection=ProjectionKind.DATA_HEALTH,
            entity_id=source_id,
            as_of_time=intelligence_as_of,
            source=intelligence_path,
            payload=DataHealthPayload(
                provider_id=source_id,
                state=data_state,
                last_success_at=(
                    _time(source_state["last_success_at"])
                    if source_state["last_success_at"] is not None
                    else None
                ),
                latency_ms=None,
                gap_count=cast("int", source_state["gap_count"]),
                policy_status=cast("str", source_state["disposition"]),
                reason_codes=reasons,
            ),
            quality=QualityState.STALE if ready else QualityState.DEGRADED,
        )
        add(
            projection=ProjectionKind.SOURCE_POLICY_STATUS,
            entity_id=source_id,
            as_of_time=intelligence_as_of,
            source=intelligence_path,
            payload=SourcePolicyPayload(
                source_id=source_id,
                runtime_state=cast("str", source_state["runtime_state"]),
                disposition=cast("str", source_state["disposition"]),
                policy_status="VERIFIED_FIXTURE_POLICY",
                last_success_at=(
                    _time(source_state["last_success_at"])
                    if source_state["last_success_at"] is not None
                    else None
                ),
                gap_count=cast("int", source_state["gap_count"]),
                reason_codes=reasons,
            ),
            quality=QualityState.STALE if ready else QualityState.DEGRADED,
        )

    fusion_path = root / "reports/data/P10_FUSION_EVIDENCE.json"
    fusion = _json(fusion_path)
    btc_impact = next(
        item
        for item in cast("list[dict[str, JsonValue]]", fusion["asset_impacts"])
        if item["asset_id"] == "BTC"
    )
    horizons = {
        cast("str", item["horizon"]): cast("str", item["expected_return"])
        for item in cast("list[dict[str, JsonValue]]", btc_impact["horizons"])
    }
    for event_state in cast("list[dict[str, JsonValue]]", intelligence["event_radar"]):
        event_id = cast("str", event_state["event_cluster_id"])
        add(
            projection=ProjectionKind.EVENT_CLUSTERS,
            entity_id=event_id,
            as_of_time=_time(event_state["as_of_time"]),
            source=fusion_path,
            payload=EventImpactPayload(
                event_cluster_id=event_id,
                status=_event_status(event_state["status"]),
                confidence=_decimal(event_state["confidence"]),
                impact_score=_decimal(event_state["impact_score"]),
                independent_family_count=cast("int", event_state["independent_family_count"]),
                evidence_ids=tuple(cast("list[str]", event_state["evidence_ids"])),
                affected_assets=("BTC", "ETH"),
                price_led_event=True,
                risk_action="CAUTION",
                impact_5m=_decimal(horizons["5m"]),
                impact_30m=_decimal(horizons["30m"]),
                impact_4h=_decimal(horizons["4h"]),
                impact_1d=_decimal(horizons["1d"]),
                impact_7d=_decimal(horizons["7d"]),
            ),
            authoritative=False,
            estimated=True,
            quality=QualityState.ESTIMATED,
        )

    for evidence in cast("list[dict[str, JsonValue]]", intelligence["evidence_graph"]):
        evidence_id = cast("str", evidence["evidence_id"])
        add(
            projection=ProjectionKind.EVENT_CLAIMS,
            entity_id=evidence_id,
            as_of_time=_time(evidence["available_at"]),
            source=intelligence_path,
            payload=ClaimEvidencePayload(
                evidence_id=evidence_id,
                event_cluster_id=cast("str", evidence["event_cluster_id"]),
                claim_id=cast("str", evidence["claim_id"]),
                relation=_relation(evidence["relation"]),
                source_family_id=cast("str", evidence["source_family_id"]),
                policy_id=cast("str", evidence["policy_id"]),
                model_version=cast("str", evidence["model_version"]),
                available_at=_time(evidence["available_at"]),
                lawful_excerpt_available=False,
            ),
        )

    for narrative in cast("list[dict[str, JsonValue]]", intelligence["narrative_monitor"]):
        narrative_id = cast("str", narrative["narrative_id"])
        add(
            projection=ProjectionKind.NARRATIVE_STATES,
            entity_id=narrative_id,
            as_of_time=_time(narrative["as_of_time"]),
            source=intelligence_path,
            payload=NarrativePayload(
                narrative_id=narrative_id,
                topic=cast("str", narrative["topic"]),
                propagation_stage=cast("str", narrative["propagation_stage"]),
                independent_author_count=cast("int", narrative["independent_author_count"]),
                coordination_risk=_decimal(narrative["coordination_risk"]),
                velocity=None,
                attention_half_life_minutes=None,
            ),
            authoritative=False,
            estimated=True,
            quality=QualityState.ESTIMATED,
        )
    return tuple(events)


def build_snapshot(root: Path) -> ProjectionSnapshot:
    engine = ProjectionEngine()
    return engine.rebuild(build_projection_events(root), projected_at=PROJECTED_AT)


def write_snapshot(root: Path, target: Path) -> ProjectionSnapshot:
    snapshot = build_snapshot(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return snapshot
