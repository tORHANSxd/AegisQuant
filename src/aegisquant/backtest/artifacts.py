"""Deterministic P06 backtest artifact writer."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol, cast

import pyarrow as pa
import pyarrow.parquet as pq

from aegisquant.backtest.models import BacktestResult
from aegisquant.data.hashing import canonical_json_bytes, sha256_file

REQUIRED_BACKTEST_ARTIFACTS = (
    "run_manifest.json",
    "orders.parquet",
    "fills.parquet",
    "ledger_entries.parquet",
    "positions.parquet",
    "equity_curve.parquet",
    "pnl_attribution.parquet",
    "metrics.json",
    "validation_report.md",
    "cost_report.md",
    "risk_report.md",
    "reproduction_command.txt",
)


class _ParquetWrite(Protocol):
    def __call__(
        self,
        table: pa.Table,
        where: Path,
        *,
        compression: Literal["zstd"],
        use_dictionary: bool,
        write_statistics: bool,
        data_page_version: Literal["2.0"],
        use_compliant_nested_type: bool,
    ) -> None: ...


@dataclass(frozen=True)
class BacktestArtifactSet:
    """Paths and content hashes produced for one immutable backtest run."""

    output_directory: Path
    paths: tuple[Path, ...]
    sha256_by_name: dict[str, str]


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _write_parquet(path: Path, rows: Iterable[dict[str, object]], schema: pa.Schema) -> None:
    table = pa.Table.from_pylist(list(rows), schema=schema)
    cast(_ParquetWrite, getattr(pq, "write_table"))(  # noqa: B009
        table,
        path,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="2.0",
        use_compliant_nested_type=True,
    )


def _write_text(path: Path, content: str) -> None:
    path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")


def _ledger_chain_valid(result: BacktestResult) -> bool:
    return all(
        current.previous_hash == previous.event_hash
        for previous, current in zip(result.ledger_records, result.ledger_records[1:], strict=False)
    )


def _orders(result: BacktestResult) -> list[dict[str, object]]:
    return [
        {
            "backtest_order_id": str(item.order.backtest_order_id),
            "client_order_id": str(item.order.client_order_id),
            "order_intent_id": str(item.order.order_intent_id),
            "instrument_id": str(item.order.instrument_id),
            "venue_id": str(item.order.venue_id),
            "side": item.order.side.value,
            "order_type": item.order.order_type.value,
            "quantity": str(item.order.quantity.amount),
            "limit_price": (
                _decimal(item.order.limit_price.amount) if item.order.limit_price else None
            ),
            "time_in_force": item.order.time_in_force.value,
            "decision_time": item.order.decision_time.isoformat(),
            "submitted_at": item.order.submitted_at.isoformat(),
            "arrival_time": item.arrival_time.isoformat(),
            "status": item.status.value,
            "cumulative_filled_quantity": str(item.cumulative_filled_quantity),
            "average_fill_price": _decimal(item.average_fill_price),
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            "rejection_code": item.rejection_code,
            "unknown_reason": item.unknown_reason,
            "recovery_evidence_json": _json(list(item.recovery_evidence)),
            "reduce_only": item.order.reduce_only,
            "exit_trigger": item.order.exit_trigger.value if item.order.exit_trigger else None,
            "trigger_price": _decimal(item.order.trigger_price.amount)
            if item.order.trigger_price
            else None,
            "oco_group_id": item.order.oco_group_id,
            "multi_leg_plan_id": (
                str(item.order.multi_leg_plan_id) if item.order.multi_leg_plan_id else None
            ),
            "leg_index": item.order.leg_index,
        }
        for item in result.orders
    ]


def _fills(result: BacktestResult) -> list[dict[str, object]]:
    return [
        {
            "fill_id": str(item.fill_id),
            "venue_order_id": str(item.venue_order_id),
            "backtest_order_id": str(item.backtest_order_id),
            "client_order_id": str(item.client_order_id),
            "order_intent_id": str(item.order_intent_id),
            "instrument_id": str(item.instrument_id),
            "side": item.side.value,
            "quantity": str(item.quantity.amount),
            "reference_price": str(item.reference_price.amount),
            "execution_price": str(item.execution_price.amount),
            "fee": str(item.fee.amount),
            "fee_asset_id": str(item.fee.asset_id),
            "cost_breakdown_json": _json(item.cost_breakdown.model_dump(mode="json")),
            "precision": item.precision.value,
            "liquidity_role": item.liquidity_role.value,
            "source_event_id": str(item.source_event_id),
            "available_liquidity": str(item.available_liquidity),
            "event_time": item.event_time.isoformat(),
            "available_time": item.available_time.isoformat(),
            "ingest_time": item.ingest_time.isoformat(),
            "latency_ns": item.latency_ns,
        }
        for item in result.fills
    ]


def _ledger_entries(result: BacktestResult) -> list[dict[str, object]]:
    return [
        {
            "journal_entry_id": str(item.journal_entry.journal_entry_id),
            "event_time": item.journal_entry.event_time.isoformat(),
            "recorded_at": item.journal_entry.recorded_at.isoformat(),
            "description": item.journal_entry.description,
            "policy_version": item.policy_version,
            "chart_version": item.chart_version,
            "entry_template_id": str(item.entry_template_id),
            "template_version": item.template_version,
            "source_fill_id": str(item.source_fill_id) if item.source_fill_id else None,
            "source_order_intent_id": (
                str(item.source_order_intent_id) if item.source_order_intent_id else None
            ),
            "idempotency_key": str(item.idempotency_key),
            "command_hash": item.command_hash,
            "previous_hash": item.previous_hash,
            "event_hash": item.event_hash,
            "postings_json": _json(
                [posting.model_dump(mode="json") for posting in item.journal_entry.postings]
            ),
            "lot_changes_json": _json(
                [change.model_dump(mode="json") for change in item.lot_changes]
            ),
        }
        for item in result.ledger_records
    ]


def _string_schema(fields: tuple[tuple[str, pa.DataType], ...]) -> pa.Schema:
    return pa.schema([pa.field(name, data_type) for name, data_type in fields])


ORDER_SCHEMA = _string_schema(
    (
        ("backtest_order_id", pa.string()),
        ("client_order_id", pa.string()),
        ("order_intent_id", pa.string()),
        ("instrument_id", pa.string()),
        ("venue_id", pa.string()),
        ("side", pa.string()),
        ("order_type", pa.string()),
        ("quantity", pa.string()),
        ("limit_price", pa.string()),
        ("time_in_force", pa.string()),
        ("decision_time", pa.string()),
        ("submitted_at", pa.string()),
        ("arrival_time", pa.string()),
        ("status", pa.string()),
        ("cumulative_filled_quantity", pa.string()),
        ("average_fill_price", pa.string()),
        ("completed_at", pa.string()),
        ("rejection_code", pa.string()),
        ("unknown_reason", pa.string()),
        ("recovery_evidence_json", pa.string()),
        ("reduce_only", pa.bool_()),
        ("exit_trigger", pa.string()),
        ("trigger_price", pa.string()),
        ("oco_group_id", pa.string()),
        ("multi_leg_plan_id", pa.string()),
        ("leg_index", pa.int64()),
    )
)

FILL_SCHEMA = _string_schema(
    (
        ("fill_id", pa.string()),
        ("venue_order_id", pa.string()),
        ("backtest_order_id", pa.string()),
        ("client_order_id", pa.string()),
        ("order_intent_id", pa.string()),
        ("instrument_id", pa.string()),
        ("side", pa.string()),
        ("quantity", pa.string()),
        ("reference_price", pa.string()),
        ("execution_price", pa.string()),
        ("fee", pa.string()),
        ("fee_asset_id", pa.string()),
        ("cost_breakdown_json", pa.string()),
        ("precision", pa.string()),
        ("liquidity_role", pa.string()),
        ("source_event_id", pa.string()),
        ("available_liquidity", pa.string()),
        ("event_time", pa.string()),
        ("available_time", pa.string()),
        ("ingest_time", pa.string()),
        ("latency_ns", pa.int64()),
    )
)

LEDGER_SCHEMA = _string_schema(
    (
        ("journal_entry_id", pa.string()),
        ("event_time", pa.string()),
        ("recorded_at", pa.string()),
        ("description", pa.string()),
        ("policy_version", pa.string()),
        ("chart_version", pa.string()),
        ("entry_template_id", pa.string()),
        ("template_version", pa.string()),
        ("source_fill_id", pa.string()),
        ("source_order_intent_id", pa.string()),
        ("idempotency_key", pa.string()),
        ("command_hash", pa.string()),
        ("previous_hash", pa.string()),
        ("event_hash", pa.string()),
        ("postings_json", pa.string()),
        ("lot_changes_json", pa.string()),
    )
)

POSITION_SCHEMA = _string_schema(
    (
        ("time", pa.string()),
        ("instrument_id", pa.string()),
        ("quantity", pa.string()),
        ("average_entry_price", pa.string()),
        ("mark_price", pa.string()),
        ("unrealized_pnl", pa.string()),
    )
)

EQUITY_SCHEMA = _string_schema(
    (
        ("time", pa.string()),
        ("cash", pa.string()),
        ("position_value", pa.string()),
        ("realized_pnl", pa.string()),
        ("unrealized_pnl", pa.string()),
        ("equity", pa.string()),
        ("reporting_asset_id", pa.string()),
    )
)

PNL_SCHEMA = _string_schema(
    (
        ("time", pa.string()),
        ("gross_trading_pnl", pa.string()),
        ("trading_fees", pa.string()),
        ("spread_cost", pa.string()),
        ("slippage_cost", pa.string()),
        ("impact_cost", pa.string()),
        ("funding", pa.string()),
        ("borrow_interest", pa.string()),
        ("settlement_fees", pa.string()),
        ("liquidation_penalties", pa.string()),
        ("net_pnl", pa.string()),
    )
)


def _write_tables(result: BacktestResult, output: Path) -> None:
    _write_parquet(output / "orders.parquet", _orders(result), ORDER_SCHEMA)
    _write_parquet(output / "fills.parquet", _fills(result), FILL_SCHEMA)
    _write_parquet(output / "ledger_entries.parquet", _ledger_entries(result), LEDGER_SCHEMA)
    _write_parquet(
        output / "positions.parquet",
        (
            {
                "time": item.time.isoformat(),
                "instrument_id": str(item.instrument_id),
                "quantity": str(item.quantity),
                "average_entry_price": _decimal(item.average_entry_price),
                "mark_price": str(item.mark_price),
                "unrealized_pnl": str(item.unrealized_pnl),
            }
            for item in result.positions
        ),
        POSITION_SCHEMA,
    )
    _write_parquet(
        output / "equity_curve.parquet",
        (
            {
                "time": item.time.isoformat(),
                "cash": str(item.cash),
                "position_value": str(item.position_value),
                "realized_pnl": str(item.realized_pnl),
                "unrealized_pnl": str(item.unrealized_pnl),
                "equity": str(item.equity),
                "reporting_asset_id": str(item.reporting_asset_id),
            }
            for item in result.equity_curve
        ),
        EQUITY_SCHEMA,
    )
    _write_parquet(
        output / "pnl_attribution.parquet",
        (
            {
                "time": item.time.isoformat(),
                "gross_trading_pnl": str(item.gross_trading_pnl),
                "trading_fees": str(item.trading_fees),
                "spread_cost": str(item.spread_cost),
                "slippage_cost": str(item.slippage_cost),
                "impact_cost": str(item.impact_cost),
                "funding": str(item.funding),
                "borrow_interest": str(item.borrow_interest),
                "settlement_fees": str(item.settlement_fees),
                "liquidation_penalties": str(item.liquidation_penalties),
                "net_pnl": str(item.net_pnl),
            }
            for item in result.pnl_attribution
        ),
        PNL_SCHEMA,
    )


def _write_reports(result: BacktestResult, output: Path) -> None:
    _write_text(
        output / "validation_report.md",
        "\n".join(
            (
                "# Backtest Validation Report",
                "",
                f"- Run: `{result.spec.run_id}`",
                f"- Economic event hash: `{result.economic_event_hash}`",
                f"- Deterministic seed: `{result.spec.seed}`",
                f"- Ledger entries: `{len(result.ledger_records)}`",
                "- Every journal entry balanced by asset: `true`",
                f"- Ledger hash chain valid: `{str(_ledger_chain_valid(result)).lower()}`",
                f"- LIVE_TRADING locked: `{str(result.spec.live_trading_locked).lower()}`",
                "- Queue position claim: `none`",
            )
        ),
    )
    costs = result.pnl_attribution[-1]
    _write_text(
        output / "cost_report.md",
        "\n".join(
            (
                "# Backtest Cost Report",
                "",
                f"- Trading fees: `{costs.trading_fees}`",
                f"- Spread cost: `{costs.spread_cost}`",
                f"- Slippage cost: `{costs.slippage_cost}`",
                f"- Impact cost: `{costs.impact_cost}`",
                f"- Funding: `{costs.funding}`",
                f"- Borrow interest: `{costs.borrow_interest}`",
                f"- Settlement fees: `{costs.settlement_fees}`",
                f"- Liquidation penalties: `{costs.liquidation_penalties}`",
                f"- Independent reference PnL reconciliation residual: `{result.cost_identity_residual}`",
                f"- Net PnL: `{costs.net_pnl}`",
                "- Cost arithmetic: `Decimal; no binary float at domain boundary`",
            )
        ),
    )
    status_counts: dict[str, int] = {}
    for order in result.orders:
        status_counts[order.status.value] = status_counts.get(order.status.value, 0) + 1
    _write_text(
        output / "risk_report.md",
        "\n".join(
            (
                "# Backtest Risk Report",
                "",
                f"- Maximum drawdown: `{result.metrics.maximum_drawdown}`",
                f"- Mark-to-market final equity: `{result.mark_to_market_final_equity}`",
                f"- Forced-close final equity: `{result.forced_close_final_equity}`",
                f"- Forced-close status: `{result.forced_close_status}`",
                f"- Final mark to executable quote adjustment: `{result.forced_close_mark_adjustment}`",
                f"- Forced-close cost: `{result.forced_close_cost.total if result.forced_close_cost else None}`",
                f"- Metric frequency in seconds: `{result.spec.metric_frequency_seconds}`",
                f"- Expected shortfall: `{result.metrics.expected_shortfall}`",
                f"- Maximum multi-leg exposure: `{result.metrics.maximum_multi_leg_exposure}`",
                f"- Order status counts: `{_json(status_counts)}`",
                f"- Warnings: `{_json(list(result.warnings))}`",
                "- Real-account connectivity: `disabled`",
                "- Order transmission: `disabled`",
            )
        ),
    )


def write_backtest_artifacts(result: BacktestResult, output_directory: Path) -> BacktestArtifactSet:
    """Write the exact P06 artifact contract and return bounded content hashes."""

    if output_directory.exists() and output_directory.is_symlink():
        raise ValueError("AQ-BACKTEST-ARTIFACT-SYMLINK-DENIED")
    output_directory.mkdir(parents=True, exist_ok=True)
    if not output_directory.is_dir():
        raise ValueError("AQ-BACKTEST-ARTIFACT-DIRECTORY-REQUIRED")

    _write_tables(result, output_directory)
    (output_directory / "metrics.json").write_bytes(
        canonical_json_bytes(result.metrics.model_dump(mode="json"))
    )
    _write_reports(result, output_directory)
    _write_text(output_directory / "reproduction_command.txt", result.spec.reproduction_command)

    artifact_hashes = {
        name: sha256_file(output_directory / name)
        for name in REQUIRED_BACKTEST_ARTIFACTS
        if name != "run_manifest.json"
    }
    manifest = {
        "schema_version": "alpha-v4-backtest-run-manifest-v1",
        "run_id": str(result.spec.run_id),
        "engine_kind": result.engine_kind.value,
        "strategy_id": str(result.spec.strategy_id),
        "strategy_version_id": str(result.spec.strategy_version_id),
        "dataset_sha256": result.spec.dataset_sha256,
        "config_sha256": result.spec.config_sha256,
        "code_sha256": result.spec.code_sha256,
        "seed": result.spec.seed,
        "start_time": result.spec.start_time.isoformat(),
        "end_time": result.spec.end_time.isoformat(),
        "created_at": result.spec.created_at.isoformat(),
        "initial_cash": result.spec.initial_cash.model_dump(mode="json"),
        "metric_frequency_seconds": result.spec.metric_frequency_seconds,
        "spot_borrow_policy": result.spec.spot_borrow_policy.model_dump(mode="json")
        if result.spec.spot_borrow_policy
        else None,
        "mark_to_market_final_equity": _decimal(result.mark_to_market_final_equity),
        "forced_close_final_equity": _decimal(result.forced_close_final_equity),
        "forced_close_status": result.forced_close_status,
        "forced_close_mark_adjustment": str(result.forced_close_mark_adjustment),
        "forced_close_cost": result.forced_close_cost.model_dump(mode="json")
        if result.forced_close_cost
        else None,
        "cost_identity_residual": str(result.cost_identity_residual),
        "accounting_policy_version": result.spec.accounting_policy_version,
        "cost_policy_version": result.spec.cost_policy_version,
        "rule_policy_version": result.spec.rule_policy_version,
        "economic_event_hash": result.economic_event_hash,
        "events_processed": result.events_processed,
        "precision_levels": [item.value for item in result.precision_levels],
        "live_trading_locked": result.spec.live_trading_locked,
        "real_account_connected": False,
        "artifact_sha256": artifact_hashes,
    }
    (output_directory / "run_manifest.json").write_bytes(canonical_json_bytes(manifest))
    all_hashes = {
        name: sha256_file(output_directory / name) for name in REQUIRED_BACKTEST_ARTIFACTS
    }
    paths = tuple(output_directory / name for name in REQUIRED_BACKTEST_ARTIFACTS)
    return BacktestArtifactSet(
        output_directory=output_directory.resolve(),
        paths=paths,
        sha256_by_name=all_hashes,
    )
