"""Build the P15 workbench snapshot from audited P04-P14 artifacts."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import polars as pl
from pydantic import JsonValue

from aegisquant.data.hashing import canonical_sha256, sha256_file
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import ensure_utc
from aegisquant.readmodels.bootstrap import build_projection_events
from aegisquant.readmodels.engine import ProjectionEngine
from aegisquant.readmodels.models import (
    CandlePoint,
    ExecutionQualityPayload,
    FillPayload,
    IncidentPayload,
    IncidentTimelinePoint,
    MarketStatePayload,
    ModelMetricPayload,
    OrderTracePayload,
    OrderTraceStage,
    PnLAttributionPayload,
    ProjectionEvent,
    ProjectionKind,
    ProjectionSnapshot,
    QualityState,
    ReconciliationPayload,
    ReplayMarker,
    ResearchMetric,
    ResearchRunPayload,
    RiskLimitPayload,
    SignalPayload,
    SystemHealthPayload,
)

PROJECTED_AT = datetime(2026, 9, 2, 0, 15, 41, 360000, tzinfo=UTC)


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


def _side(value: object) -> Literal["BUY", "SELL"]:
    if value not in {"BUY", "SELL"}:
        raise ValueError("unsupported order side in source artifact")
    return cast('Literal["BUY", "SELL"]', value)


def _research_status(value: object) -> Literal["SUCCEEDED", "FAILED", "ERROR", "PRUNED"]:
    if value not in {"SUCCEEDED", "FAILED", "ERROR", "PRUNED"}:
        raise ValueError("unsupported research status in source artifact")
    return cast('Literal["SUCCEEDED", "FAILED", "ERROR", "PRUNED"]', value)


def build_p15_projection_events(root: Path) -> tuple[ProjectionEvent, ...]:
    """Append P15 operational projections without rewriting the immutable P14 artifact."""
    root = root.resolve()
    events = list(build_projection_events(root))

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
                event_id=f"p15:{projection.value}:{entity_id}",
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

    account_id = "paper-account"
    backtest = root / "reports/backtests/p06-golden"
    attribution_path = backtest / "pnl_attribution.parquet"
    attribution_rows = pl.read_parquet(attribution_path).to_dicts()
    if len(attribution_rows) != 1:
        raise ValueError("P06 attribution artifact must contain one aggregate row")
    attribution = attribution_rows[0]
    attribution_time = _time(attribution["time"])
    add(
        projection=ProjectionKind.PNL_ATTRIBUTION,
        entity_id=f"{account_id}:aggregate",
        as_of_time=attribution_time,
        source=attribution_path,
        payload=PnLAttributionPayload(
            account_id=account_id,
            reporting_asset_id="USDT",
            gross_trading_pnl=_decimal(attribution["gross_trading_pnl"]),
            trading_fees=_decimal(attribution["trading_fees"]),
            spread_cost=_decimal(attribution["spread_cost"]),
            slippage_cost=_decimal(attribution["slippage_cost"]),
            impact_cost=_decimal(attribution["impact_cost"]),
            funding=_decimal(attribution["funding"]),
            borrow_interest=_decimal(attribution["borrow_interest"]),
            net_pnl=_decimal(attribution["net_pnl"]),
            formula=(
                "gross_trading_pnl - trading_fees - spread_cost - slippage_cost - "
                "impact_cost + funding - borrow_interest"
            ),
            source_scope="P06 deterministic historical replay",
        ),
    )

    risk_path = root / "reports/data/P11_RISK_DECISION_EVIDENCE.json"
    risk_evidence = _json(risk_path)
    risk_snapshot = cast("dict[str, JsonValue]", risk_evidence["snapshot"])
    policy_path = root / "reports/risk/P11_SIGNED_RISK_POLICY.json"
    policy_evidence = _json(policy_path)
    signed = cast("dict[str, JsonValue]", policy_evidence["signed_policy"])
    policy = cast("dict[str, JsonValue]", signed["policy"])
    pretrade = cast("dict[str, JsonValue]", policy["pre_trade_limits"])
    policy_id = cast("str", policy["policy_id"])
    risk_as_of = _time(risk_snapshot["as_of_time"])
    limit_specs = (
        (
            "daily-loss",
            "daily_pnl_fraction_abs",
            abs(_decimal(risk_snapshot["daily_pnl_fraction"])),
            _decimal(policy["maximum_daily_loss_fraction"]),
            "fraction",
            "maximum",
        ),
        (
            "drawdown",
            "drawdown_fraction",
            _decimal(risk_snapshot["drawdown_fraction"]),
            _decimal(policy["maximum_drawdown_fraction"]),
            "fraction",
            "maximum",
        ),
        (
            "margin",
            "margin_utilization",
            _decimal(risk_snapshot["margin_utilization"]),
            _decimal(policy["maximum_margin_utilization"]),
            "fraction",
            "maximum",
        ),
        (
            "gross-weight",
            "portfolio_gross_weight",
            _decimal(risk_snapshot["portfolio_gross_weight"]),
            _decimal(pretrade["maximum_account_gross_weight"]),
            "fraction",
            "maximum",
        ),
        (
            "liquidity",
            "liquidity_score",
            _decimal(risk_snapshot["liquidity_score"]),
            _decimal(policy["minimum_liquidity_score"]),
            "score",
            "minimum",
        ),
    )
    for suffix, metric, current, limit, unit, direction in limit_specs:
        maximum = direction == "maximum"
        add(
            projection=ProjectionKind.RISK_LIMITS,
            entity_id=f"{policy_id}:{suffix}",
            as_of_time=risk_as_of,
            source=policy_path,
            payload=RiskLimitPayload(
                limit_id=f"{policy_id}:{suffix}",
                policy_id=policy_id,
                metric=metric,
                current_value=current,
                limit_value=limit,
                headroom=limit - current if maximum else current - limit,
                unit=cast('Literal["fraction", "score"]', unit),
                breached=current > limit if maximum else current < limit,
                example_values_only=True,
                live_editable=False,
            ),
        )

    council_path = root / "reports/data/P08_MODEL_COUNCIL_EVIDENCE.json"
    council = _json(council_path)
    selected_model_id = cast("str", council["selected_model_id"])
    for candidate in cast("list[dict[str, JsonValue]]", council["candidates"]):
        model_id = cast("str", candidate["model_id"])
        add(
            projection=ProjectionKind.MODEL_METRICS,
            entity_id=model_id,
            as_of_time=risk_as_of,
            source=council_path,
            payload=ModelMetricPayload(
                model_id=model_id,
                family=cast("str", candidate["family"]),
                modality=cast("str", candidate["modality"]),
                metric_name="primary_loss",
                metric_value=_decimal(candidate["primary_loss"]),
                evaluation_state=cast("str", candidate["state"]),
                selected=model_id == selected_model_id,
                train_seconds=_decimal(candidate["train_seconds"]),
                peak_memory_mb=_decimal(candidate["peak_memory_mb"]),
                abstain_or_failure_reason=cast(
                    "str | None", candidate["abstain_or_failure_reason"]
                ),
                final_holdout_opened=False,
                alpha_claimed=False,
            ),
        )

    portfolio_path = root / "reports/data/P11_PORTFOLIO_EVIDENCE.json"
    portfolio = _json(portfolio_path)
    proposal = cast("dict[str, JsonValue]", portfolio["proposal"])
    proposal_id = cast("str", proposal["proposal_id"])
    signal_as_of = _time(proposal["as_of_time"])
    for leg in cast("list[dict[str, JsonValue]]", proposal["legs"]):
        signal_id = cast("str", leg["signal_id"])
        add(
            projection=ProjectionKind.SIGNALS,
            entity_id=signal_id,
            as_of_time=signal_as_of,
            source=portfolio_path,
            payload=SignalPayload(
                signal_id=signal_id,
                proposal_id=proposal_id,
                strategy_id=cast("str", leg["strategy_id"]),
                instrument_id=cast("str", leg["instrument_id"]),
                normalized_signal=_decimal(leg["normalized_signal"]),
                current_weight=_decimal(leg["current_weight"]),
                target_weight=_decimal(leg["target_weight"]),
                delta_weight=_decimal(leg["delta_weight"]),
                expected_return_contribution=_decimal(leg["expected_return_contribution"]),
                estimated_impact_bps=_decimal(leg["estimated_impact_bps"]),
                valid_until=_time(proposal["valid_until"]),
                environment_stage="PAPER",
                order_capability=False,
            ),
        )

    fills_path = backtest / "fills.parquet"
    fill_rows = pl.read_parquet(fills_path).to_dicts()
    fills_by_order: dict[str, list[dict[str, object]]] = {}
    for row in fill_rows:
        order_id = cast("str", row["backtest_order_id"])
        fills_by_order.setdefault(order_id, []).append(row)
        fill_id = cast("str", row["fill_id"])
        add(
            projection=ProjectionKind.FILLS,
            entity_id=fill_id,
            as_of_time=_time(row["available_time"]),
            source=fills_path,
            payload=FillPayload(
                fill_id=fill_id,
                order_id=order_id,
                order_intent_id=cast("str", row["order_intent_id"]),
                instrument_id=cast("str", row["instrument_id"]),
                side=_side(row["side"]),
                quantity=_decimal(row["quantity"]),
                reference_price=_decimal(row["reference_price"]),
                execution_price=_decimal(row["execution_price"]),
                fee=_decimal(row["fee"]),
                fee_asset_id=cast("str", row["fee_asset_id"]),
                liquidity_role=cast("str", row["liquidity_role"]),
                event_time=_time(row["event_time"]),
                available_at=_time(row["available_time"]),
                ingest_time=_time(row["ingest_time"]),
                latency_ns=cast("int", row["latency_ns"]),
                virtual=True,
            ),
        )

    scorecard_path = root / "reports/runtime/P13_SCORECARD.json"
    scorecard_document = _json(scorecard_path)
    scorecard = cast("dict[str, JsonValue]", scorecard_document["scorecard"])
    add(
        projection=ProjectionKind.EXECUTION_QUALITY,
        entity_id=cast("str", scorecard["strategy_id"]),
        as_of_time=_time("2026-09-01T20:00:03Z"),
        source=scorecard_path,
        payload=ExecutionQualityPayload(
            strategy_id=cast("str", scorecard["strategy_id"]),
            observation_count=cast("int", scorecard["observation_count"]),
            fill_rate=_decimal(scorecard["fill_rate"]),
            mean_adverse_slippage_bps=_decimal(scorecard["mean_adverse_slippage_bps"]),
            p95_adverse_slippage_bps=_decimal(scorecard["p95_adverse_slippage_bps"]),
            reconciliation_difference_count=cast(
                "int", scorecard["reconciliation_difference_count"]
            ),
            rejection_count=cast("int", scorecard["rejection_count"]),
            restart_count=cast("int", scorecard["restart_count"]),
            degraded_cycle_count=cast("int", scorecard["degraded_cycle_count"]),
            production_capacity_claimed=False,
            testnet_pnl_included=False,
        ),
    )

    candle_path = root / "tests/fixtures/p08/BTCUSDT-1m-2024-01-31-1850-1910UTC.csv"
    with candle_path.open(encoding="utf-8", newline="") as source:
        candle_rows = list(csv.DictReader(source))
    candles = tuple(
        CandlePoint(
            time=datetime.fromtimestamp(int(row["open_time_ms"]) / 1000, tz=UTC),
            open=Decimal(row["open"]),
            high=Decimal(row["high"]),
            low=Decimal(row["low"]),
            close=Decimal(row["close"]),
            volume=Decimal(row["volume"]),
        )
        for row in candle_rows
    )
    if not candles:
        raise ValueError("P08 historical market replay fixture is empty")
    add(
        projection=ProjectionKind.MARKET_STATE,
        entity_id="BINANCE:BTCUSDT:1m:FOMC-2024-01-31",
        as_of_time=candles[-1].time,
        source=candle_path,
        payload=MarketStatePayload(
            market_id="BINANCE:BTCUSDT:1m:FOMC-2024-01-31",
            instrument_id="BTCUSDT",
            venue_id="BINANCE-SPOT-PUBLIC-ARCHIVE",
            data_kind="HISTORICAL_REPLAY",
            bar_semantics="OHLC",
            mark_price=candles[-1].close,
            candles=candles,
            replay_markers=(),
            recommendation_provided=False,
        ),
    )

    public_frames_path = root / "tests/fixtures/binance/recorded_public.jsonl"
    public_frames = [
        cast("dict[str, JsonValue]", json.loads(line))
        for line in public_frames_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    mark_frame = next(
        item
        for item in public_frames
        if cast("dict[str, JsonValue]", item["payload"]).get("e") == "markPriceUpdate"
    )
    mark_payload = cast("dict[str, JsonValue]", mark_frame["payload"])
    mark = _decimal(mark_payload["p"])
    index = _decimal(mark_payload["i"])
    add(
        projection=ProjectionKind.MARKET_STATE,
        entity_id="BINANCE:BTCUSDT:USD-M:PUBLIC-FRAME",
        as_of_time=_time(mark_frame["observed_at"]),
        source=public_frames_path,
        payload=MarketStatePayload(
            market_id="BINANCE:BTCUSDT:USD-M:PUBLIC-FRAME",
            instrument_id="BTCUSDT-PERP",
            venue_id="BINANCE-USD-M-PUBLIC-FIXTURE",
            data_kind="PUBLIC_FIXTURE",
            bar_semantics="QUOTE_ENVELOPE",
            mark_price=mark,
            index_price=index,
            basis=mark - index,
            funding_rate=_decimal(mark_payload["r"]),
            candles=(),
            replay_markers=(),
            recommendation_provided=False,
        ),
    )

    historical_path = root / "reports/runtime/P13_HISTORICAL_REPLAY.json"
    historical = _json(historical_path)
    scenario = cast("dict[str, JsonValue]", historical["scenario"])
    observations = cast("list[dict[str, JsonValue]]", scenario["observations"])
    quote_candles: list[CandlePoint] = []
    for observation in observations:
        last_price = cast("dict[str, JsonValue]", observation["last_price"])
        ask_price = cast("dict[str, JsonValue]", observation["ask_price"])
        bid_price = cast("dict[str, JsonValue]", observation["bid_price"])
        ask_quantity = cast("dict[str, JsonValue]", observation["ask_quantity"])
        bid_quantity = cast("dict[str, JsonValue]", observation["bid_quantity"])
        quote_candles.append(
            CandlePoint(
                time=_time(observation["event_time"]),
                open=_decimal(last_price["amount"]),
                high=_decimal(ask_price["amount"]),
                low=_decimal(bid_price["amount"]),
                close=_decimal(last_price["amount"]),
                volume=_decimal(ask_quantity["amount"]) + _decimal(bid_quantity["amount"]),
            )
        )
    paper_path = root / "reports/runtime/P13_PAPER_EVIDENCE.json"
    paper = _json(paper_path)
    paper_fill = cast("dict[str, JsonValue]", cast("list[JsonValue]", paper["fills"])[0])
    paper_fill_price = cast("dict[str, JsonValue]", paper_fill["fill_price"])
    replay_marker = ReplayMarker(
        time=_time(paper_fill["event_time"]),
        marker_type="FILL",
        entity_id=cast("str", paper_fill["fill_id"]),
        label="P13 Paper virtual fill",
        price=_decimal(paper_fill_price["amount"]),
        source_artifact=paper_path.relative_to(root).as_posix(),
        synthetic=False,
    )
    add(
        projection=ProjectionKind.MARKET_STATE,
        entity_id="P13:BTC-USDT-PERP:NORMALIZED-QUOTE-REPLAY",
        as_of_time=quote_candles[-1].time,
        source=historical_path,
        payload=MarketStatePayload(
            market_id="P13:BTC-USDT-PERP:NORMALIZED-QUOTE-REPLAY",
            instrument_id="BTC-USDT-PERP",
            venue_id="BINANCE-TESTNET",
            data_kind="NORMALIZED_QUOTE_REPLAY",
            bar_semantics="QUOTE_ENVELOPE",
            mark_price=quote_candles[-1].close,
            candles=tuple(quote_candles),
            replay_markers=(replay_marker,),
            recommendation_provided=False,
        ),
        authoritative=False,
        estimated=False,
    )

    research_path = root / "reports/research/P07/EXPERIMENT_LEDGER.jsonl"
    research_entries = [
        cast("dict[str, JsonValue]", json.loads(line))
        for line in research_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for entry in research_entries:
        record = cast("dict[str, JsonValue]", entry["record"])
        metrics = cast("dict[str, JsonValue]", record["metrics"])
        run_id = cast("str", record["run_id"])
        add(
            projection=ProjectionKind.RESEARCH_RUNS,
            entity_id=run_id,
            as_of_time=_time(record["finished_at"]),
            source=research_path,
            payload=ResearchRunPayload(
                run_id=run_id,
                model_id=cast("str", record["model_id"]),
                status=_research_status(record["status"]),
                started_at=_time(record["started_at"]),
                finished_at=_time(record["finished_at"]),
                metrics=tuple(
                    ResearchMetric(name=name, value=_decimal(value))
                    for name, value in sorted(metrics.items())
                ),
                failure_reason=cast("str | None", record["failure_reason"]),
                promotion_decision=cast("str", record["promotion_decision"]),
                code_commit=cast("str", record["code_commit"]),
                dataset_sha256=cast("str", record["dataset_sha256"]),
                split_sha256=cast("str", record["split_sha256"]),
                ai_proposed=cast("bool", record["ai_proposed"]),
                final_holdout_opened=False,
            ),
        )

    incident_path = root / "reports/runtime/P13_INCIDENT_DRILLS.json"
    incident_document = _json(incident_path)
    for incident in cast("list[dict[str, JsonValue]]", incident_document["incidents"]):
        alert = cast("dict[str, JsonValue]", incident["alert"])
        recovery = cast("dict[str, JsonValue]", incident["recovery_evidence"])
        incident_id = cast("str", incident["incident_id"])
        timeline = tuple(
            IncidentTimelinePoint(
                sequence=cast("int", point["sequence"]),
                occurred_at=_time(point["occurred_at"]),
                event_type=cast("str", point["event_type"]),
                state=cast("str", point["state"]),
                evidence_ids=tuple(cast("list[str]", point["evidence_ids"])),
                operator_action_required=cast("bool", point["operator_action_required"]),
            )
            for point in cast("list[dict[str, JsonValue]]", incident["timeline"])
        )
        add(
            projection=ProjectionKind.INCIDENTS,
            entity_id=incident_id,
            as_of_time=_time(alert["raised_at"]),
            source=incident_path,
            payload=IncidentPayload(
                incident_id=incident_id,
                severity=cast('Literal["SEV0", "SEV1", "SEV2", "SEV3"]', alert["severity"]),
                fault_kind=cast("str", alert["fault_kind"]),
                status=cast("str", incident["status"]),
                risk_state=cast("str", alert["state"]),
                reason_code=cast("str", alert["reason_code"]),
                runbook_path=cast("str", alert["runbook_path"]),
                new_risk_allowed=False,
                real_funds_impacted=False,
                postmortem_required=cast("bool", incident["postmortem_required"]),
                checkpoint_verified=cast("bool", recovery["checkpoint_verified"]),
                reconciliation_clear=cast("bool", recovery["reconciliation_clear"]),
                duplicate_fill_count=cast("int", recovery["duplicate_fill_count"]),
                duplicate_order_count=cast("int", recovery["duplicate_order_count"]),
                timeline=timeline,
            ),
        )

    ci_path = root / "reports/phases/P14/CI_RESULTS.json"
    ci = _json(ci_path)
    ci_time = _time(ci["generated_at_utc"])
    ci_results = {
        cast("str", item["name"]): item
        for item in cast("list[dict[str, JsonValue]]", ci["results"])
    }
    service_checks = (
        ("read-api", "p14-read-api-web-contracts"),
        ("web-app", "web-build"),
        ("postgres-read-model", "postgres-runtime"),
    )
    for service_id, check_name in service_checks:
        result = ci_results[check_name]
        passed = cast("int", result["exit_code"]) == 0
        add(
            projection=ProjectionKind.SYSTEM_HEALTH,
            entity_id=service_id,
            as_of_time=ci_time,
            source=ci_path,
            payload=SystemHealthPayload(
                service_id=service_id,
                status="READY" if passed else "ERROR",
                version="3.1.0.dev0",
                checked_at=ci_time,
                check_name=check_name,
                detail=(
                    f"P14 verified check exited {cast('int', result['exit_code'])}; "
                    "this is historical CI evidence, not a live service probe."
                ),
                historical_check=True,
                live_trading_locked=True,
            ),
        )

    reconciliation_path = root / "reports/execution/P12_ACCOUNT_RECONCILIATION.json"
    reconciliation_document = _json(reconciliation_path)
    reconciliation = cast("dict[str, JsonValue]", reconciliation_document["reconciliation"])
    account_snapshot = cast("dict[str, JsonValue]", reconciliation_document["snapshot"])
    add(
        projection=ProjectionKind.RECONCILIATION_STATUS,
        entity_id=f"{account_id}:{cast('str', account_snapshot['venue_id'])}",
        as_of_time=_time(account_snapshot["captured_at"]),
        source=reconciliation_path,
        payload=ReconciliationPayload(
            account_id=account_id,
            venue_id=cast("str", account_snapshot["venue_id"]),
            state=cast("str", reconciliation["state"]),
            applied=cast("bool", reconciliation["applied"]),
            last_sequence=cast("int", reconciliation["last_sequence"]),
            sequence_gap=cast("bool", reconciliation["sequence_gap"]),
            unknown_local_fill_count=len(
                cast("list[JsonValue]", reconciliation["unknown_local_fill_ids"])
            ),
            unknown_local_order_count=len(
                cast("list[JsonValue]", reconciliation["unknown_local_order_ids"])
            ),
            unknown_venue_fill_count=len(
                cast("list[JsonValue]", reconciliation["unknown_venue_fill_ids"])
            ),
            unknown_venue_order_count=len(
                cast("list[JsonValue]", reconciliation["unknown_venue_order_ids"])
            ),
            captured_at=_time(account_snapshot["captured_at"]),
            reason_codes=tuple(cast("list[str]", reconciliation["reason_codes"])),
        ),
    )

    orders_path = backtest / "orders.parquet"
    order_rows = pl.read_parquet(orders_path).to_dicts()
    ledger_path = backtest / "ledger_entries.parquet"
    ledger_rows = pl.read_parquet(ledger_path).to_dicts()
    manifest_path = backtest / "run_manifest.json"
    risk_report_path = backtest / "risk_report.md"
    for order in order_rows:
        order_id = cast("str", order["backtest_order_id"])
        order_intent_id = cast("str", order["order_intent_id"])
        matching_fills = fills_by_order.get(order_id, [])
        matching_ledger = [
            row for row in ledger_rows if row["source_order_intent_id"] == order_intent_id
        ]
        if not matching_fills or not matching_ledger:
            raise ValueError(f"P06 order lacks fill or ledger trace: {order_id}")
        first_fill = matching_fills[0]
        first_ledger = matching_ledger[0]
        stages = (
            OrderTraceStage(
                sequence=1,
                stage="SIGNAL",
                status="NOT_APPLICABLE",
                source_artifact=manifest_path.relative_to(root).as_posix(),
                explanation="P06 buy-and-hold baseline was rule-driven and recorded no AlphaSignal.",
            ),
            OrderTraceStage(
                sequence=2,
                stage="EVENT_EVIDENCE",
                status="NOT_APPLICABLE",
                source_artifact=manifest_path.relative_to(root).as_posix(),
                explanation="The P06 baseline did not consume event intelligence.",
            ),
            OrderTraceStage(
                sequence=3,
                stage="MODEL",
                status="NOT_APPLICABLE",
                source_artifact=manifest_path.relative_to(root).as_posix(),
                explanation="The execution decision was not produced by a predictive model.",
            ),
            OrderTraceStage(
                sequence=4,
                stage="RISK",
                status="VERIFIED",
                entity_id="p06-backtest-risk-policy",
                source_artifact=risk_report_path.relative_to(root).as_posix(),
                explanation="The deterministic backtest risk report governed this order.",
            ),
            OrderTraceStage(
                sequence=5,
                stage="ORDER",
                status="VERIFIED",
                entity_id=order_id,
                source_artifact=orders_path.relative_to(root).as_posix(),
                explanation="Order lifecycle is present in the canonical P06 order table.",
            ),
            OrderTraceStage(
                sequence=6,
                stage="FILL",
                status="VERIFIED",
                entity_id=cast("str", first_fill["fill_id"]),
                source_artifact=fills_path.relative_to(root).as_posix(),
                explanation=f"{len(matching_fills)} virtual fill record(s) link to this order.",
            ),
            OrderTraceStage(
                sequence=7,
                stage="LEDGER",
                status="VERIFIED",
                entity_id=cast("str", first_ledger["journal_entry_id"]),
                source_artifact=ledger_path.relative_to(root).as_posix(),
                explanation=f"{len(matching_ledger)} balanced journal entry record(s) link by intent.",
            ),
        )
        add(
            projection=ProjectionKind.ORDER_TRACES,
            entity_id=order_id,
            as_of_time=_time(order["completed_at"]),
            source=orders_path,
            payload=OrderTracePayload(
                order_id=order_id,
                account_id=account_id,
                strategy_id="p06-buy-hold",
                instrument_id=cast("str", order["instrument_id"]),
                decision_time=_time(order["submitted_at"]),
                stages=stages,
                complete=True,
                causal_link_overclaimed=False,
            ),
        )

    return tuple(events)


def build_p15_snapshot(root: Path) -> ProjectionSnapshot:
    engine = ProjectionEngine()
    return engine.rebuild(build_p15_projection_events(root), projected_at=PROJECTED_AT)
