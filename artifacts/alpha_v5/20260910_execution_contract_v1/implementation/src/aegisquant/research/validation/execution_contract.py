"""B4 execution evidence protocols and pure calibration checks; no market loader."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import timedelta
from decimal import Decimal
from typing import Any

import numpy as np

from aegisquant.data.hashing import ensure_sha256
from aegisquant.research.validation.evidence_contract import CostMode, Row, decimal, require, utc
from aegisquant.research.validation.paired_bootstrap import (
    _circular_block_totals,  # pyright: ignore[reportPrivateUsage] -- reuse the existing shared row sampler without compounding counts.
)

FILES = (
    "src/aegisquant/backtest/models.py",
    "src/aegisquant/backtest/fills.py",
    "src/aegisquant/backtest/costs.py",
    "src/aegisquant/portfolio/transition_costs.py",
    "src/aegisquant/portfolio/optimizer.py",
    "src/aegisquant/portfolio/models.py",
    "src/aegisquant/research/validation/evidence_contract.py",
    "src/aegisquant/accounting/ledger.py",
    "src/aegisquant/research/validation/execution_contract.py",
    "scripts/run_alpha_v5_execution_diagnostics.py",
    "configs/research/alpha_v5_execution_contract.yaml",
    "tests/alpha_v5/test_execution_contract.py",
    "docs/research/alpha_v5_execution_contract.md",
)


def validate_config(config: Row) -> None:
    match = re.fullmatch(r"alpha-r5-execution-contract-(\d{8})-v([1-9]\d*)", config["generation"])
    require(match is not None, "AQ-EXECUTION-GENERATION")
    if match is None:
        return
    require(
        config["output"] == f"artifacts/alpha_v5/{match[1]}_execution_contract_v{match[2]}",
        "AQ-EXECUTION-OUTPUT",
    )
    require(
        config["scope"] == "B4_EXECUTION_PROTOCOL_AND_SYNTHETIC_CONTRACT_TESTS",
        "AQ-EXECUTION-SCOPE",
    )
    require(
        config["execution_observations"] is None and config["calibration_split"] is None,
        "AQ-EXECUTION-REAL-CALIBRATION-NOT-AUTHORIZED",
    )
    require(
        config["future_scenarios"]
        == {
            "controls": ["G1", "SIMPLE_TREND"],
            "capital_multipliers": ["1", "5", "10", "25", "50"],
            "stress_paths": ["BASE", "COST_AND_LATENCY", "DEPTH_AND_HALT"],
            "authorized_runs_now": 0,
        },
        "AQ-EXECUTION-SCENARIO-REGISTRATION",
    )
    require(
        config["calibration_acceptance"]
        == {
            "minimum_bucket_samples": 200,
            "minimum_bucket_days": 20,
            "maximum_abs_median_residual_bps": "1",
            "maximum_q95_exceedance_upper_bound": "0.10",
            "block_days": 5,
            "repetitions": 10000,
            "seed": 20260910,
        },
        "AQ-EXECUTION-CALIBRATION-REGISTRATION",
    )


def validate_execution_observations(rows: Sequence[Row]) -> None:
    """Reject duplicate/conflicting fills and contradictory clocks before any split."""
    fills: set[str] = set()
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    orders: dict[str, tuple[Decimal, str]] = {}
    for row in rows:
        ensure_sha256(row["source_sha256"], field_name="execution observation source")
        require(row["fill_id"] not in fills, "AQ-EXECUTION-DUPLICATE-FILL")
        fills.add(row["fill_id"])
        clocks = {
            key: utc(row[key]) if row[key] is not None else None
            for key in (
                "decision_at",
                "send_at",
                "venue_receive_at",
                "ack_at",
                "fill_at",
                "receive_at",
                "cancel_request_at",
                "cancel_ack_at",
            )
        }
        decision, send, fill, received = (
            clocks[key] for key in ("decision_at", "send_at", "fill_at", "receive_at")
        )
        require(
            all(value is not None for value in (decision, send, fill, received)),
            "AQ-EXECUTION-MISSING-REQUIRED-CLOCK",
        )
        if decision is None or send is None or fill is None or received is None:
            return
        require(decision <= send <= fill <= received, "AQ-EXECUTION-CLOCK-ORDER")
        if (arrival := clocks["venue_receive_at"]) is not None:
            require(send <= arrival <= fill, "AQ-EXECUTION-ARRIVAL-CLOCK")
        if (ack := clocks["ack_at"]) is not None:
            require(ack >= send and (arrival is None or ack >= arrival), "AQ-EXECUTION-ACK-CLOCK")
        if (cancel := clocks["cancel_request_at"]) is not None:
            require(cancel >= send, "AQ-EXECUTION-CANCEL-CLOCK")
        if (cancel_ack := clocks["cancel_ack_at"]) is not None:
            require(
                clocks["cancel_request_at"] is not None
                and cancel_ack >= clocks["cancel_request_at"],
                "AQ-EXECUTION-CANCEL-CLOCK",
            )
        require(
            row["clock_error_ns"] is None
            or (type(row["clock_error_ns"]) is int and row["clock_error_ns"] >= 0),
            "AQ-EXECUTION-CLOCK-ERROR",
        )
        quantity, order_quantity = decimal(row["quantity"]), decimal(row["order_quantity"])
        require(
            0 < quantity <= order_quantity and row["side"] in {"BUY", "SELL"},
            "AQ-EXECUTION-QUANTITY-OR-SIDE",
        )
        require(
            row["reference_price_kind"]
            in {"MID", "BBO", "DEPTH_VWAP", "BAR_OPEN_PROXY", "MAKER_LIMIT"}
            and decimal(row["reference_price"]) > 0
            and bool(row["fee_asset"]),
            "AQ-EXECUTION-REFERENCE-OR-FEE-ASSET",
        )
        identity = (order_quantity, row["side"])
        order_id = row["order_id"]
        require(
            order_id not in orders or orders[order_id] == identity, "AQ-EXECUTION-ORDER-CONFLICT"
        )
        orders[order_id] = identity
        totals[order_id] += quantity
        require(totals[order_id] <= order_quantity, "AQ-EXECUTION-OVERFILL")


def split_execution_calibration(
    rows: Sequence[Row],
    *,
    calibration_start: str,
    calibration_end: str,
    validation_start: str,
    validation_end: str,
) -> dict[str, Any]:
    """One fixed split; a partially filled order cannot straddle the two regions."""
    validate_execution_observations(rows)
    cs, ce, vs, ve = map(
        utc, (calibration_start, calibration_end, validation_start, validation_end)
    )
    require(cs < ce <= vs < ve, "AQ-EXECUTION-CALIBRATION-SPLIT-OVERLAP")
    groups: dict[str, list[Row]] = {"calibration": [], "validation": [], "excluded": []}
    memberships: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        time = utc(row["fill_at"])
        group = (
            "calibration" if cs <= time < ce else "validation" if vs <= time < ve else "excluded"
        )
        require(
            utc(row["receive_at"]) <= (ce if group == "calibration" else ve) or group == "excluded",
            "AQ-EXECUTION-LABEL-NOT-KNOWN-BY-SPLIT",
        )
        memberships[row["order_id"]].add(group)
        groups[group].append(row)
    require(
        all(len(regions) == 1 for regions in memberships.values()),
        "AQ-EXECUTION-ORDER-CROSSES-SPLIT",
    )
    return {
        "kind": "SUPPLIED_OBSERVATION_SPLIT_NOT_MODEL_FIT",
        **{key: [row["fill_id"] for row in values] for key, values in groups.items()},
    }


def calibration_residual_buckets(rows: Sequence[Row]) -> dict[str, Any]:
    """Pure fixed-rule validation; callers must separately verify real observation sources."""
    validate_execution_observations(rows)
    grouped: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[row["bucket"]].append(row)
    results = {}
    for bucket, values in sorted(grouped.items()):
        by_day: dict[Any, list[Row]] = defaultdict(list)
        for row in values:
            by_day[utc(row["fill_at"]).date()].append(row)
        require(all(decimal(row["fee_quantum"]) > 0 for row in values), "AQ-EXECUTION-FEE-QUANTUM")
        fees_exact = all(
            decimal(row["fee_amount"]) == decimal(row["expected_fee_amount"])
            and decimal(row["fee_amount"]) % decimal(row["fee_quantum"]) == 0
            for row in values
        )
        if len(values) < 200 or len(by_day) < 20:
            results[bucket] = {
                "status": "INSUFFICIENT_SAMPLE",
                "samples": len(values),
                "days": len(by_day),
                "fees_exact": fees_exact,
                "median_residual_bps": None,
                "q95_exceedance_ci95": None,
            }
            continue
        start, end = min(by_day), max(by_day)
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        counts = np.array(
            [
                [
                    len(by_day[day]),
                    sum(
                        decimal(row["observed_adverse_bps"]) > decimal(row["predicted_q95_bps"])
                        for row in by_day[day]
                    ),
                ]
                for day in days
            ],
            dtype=np.float64,
        )
        sampled = _circular_block_totals(counts, repetitions=10000, block_bars=5, seed=20260910)
        if np.any(sampled[:, 0] == 0):
            results[bucket] = {
                "status": "INSUFFICIENT_EFFECTIVE_TIME_BLOCKS",
                "samples": len(values),
                "days": len(by_day),
            }
            continue
        low, high = np.quantile(sampled[:, 1] / sampled[:, 0], (0.025, 0.975))
        median = float(np.median([float(decimal(row["residual_bps"])) for row in values]))
        results[bucket] = {
            "status": "SUPPLIED_RECORDS_PASS"
            if fees_exact and abs(median) <= 1 and high <= 0.10
            else "CALIBRATION_FAILED",
            "samples": len(values),
            "days": len(by_day),
            "fees_exact": fees_exact,
            "median_residual_bps": median,
            "q95_exceedance_ci95": [float(low), float(high)],
            "source_verification": "SEPARATE_REQUIRED",
            "no_bucket_selection": True,
        }
    return {
        "kind": "SUPPLIED_RESIDUAL_CHECK_NOT_MODEL_FIT_OR_EMPIRICAL_SOURCE_PROOF",
        "buckets": results,
    }


def build_documents(sources: Mapping[str, Any]) -> Mapping[str, Any]:
    missing = [
        {"item": name, "status": "NOT_RECEIVED", "records": None}
        for name in (
            "historical_account_fee_rules",
            "native_asset_balances_and_fee_fx",
            "historical_l1_l2_sequence_and_trades",
            "venue_and_client_latency_observations",
            "queue_positions_and_cancel_observations",
        )
    ]
    return {
        "execution_protocol.json": {
            "status": "PROTOCOL_DEFINED_EMPIRICAL_MODEL_NOT_CALIBRATED",
            "legacy_execution": "LINEAR_PROXY_V1",
            "legacy_capacity": "LEGACY_SQRT_CAPACITY_V0",
            "explicit_curves_share_forward_and_inverse": True,
            "prices": ["MID", "BBO", "DEPTH_VWAP", "BAR_OPEN_PROXY", "MAKER_LIMIT"],
            "bar_volume_is_opening_liquidity_evidence": False,
            "maker_queue_unknown": "NO_IDENTIFIED_FILL",
            "strict_budget_scope": "ONE_INSTRUMENT_VENUE_CLOSED_CUMULATIVE_WINDOW_AT_EVENT_TIME",
            "strict_budget_current_evidence_kind": "SYNTHETIC_ONLY",
            "native_fee_accounting_policy": "SPOT_NATIVE_FEES_V2",
            "native_fee_base": "FIFO_DISPOSAL_AT_FILL_MARK_REBATE_LOT_AT_FILL_MARK",
            "third_fee_asset": "REQUIRES_FUNDED_CASH_AND_FX_OPEN_OTHER_INSTRUMENT_LOTS_FAIL_CLOSED",
            "old_engine_default_changed": False,
            "existing_g1_parameters_changed": False,
        },
        "execution_quality_tables.json": {"status": "NOT_RECEIVED", "tables": missing},
        "calibration_freeze_manifest.json": {
            "status": "NOT_ALLOCATED_MISSING_EXECUTION_OBSERVATIONS",
            "calibration_period": None,
            "validation_period": None,
            "actual_data_splits": 0,
            "model_fits": 0,
            "replay_scenarios": 0,
            "frozen_model_hash": None,
        },
        "calibration_residual_buckets.json": {"status": "NOT_COLLECTED", "buckets": None},
        "cost_modes.json": {
            mode.value: {
                "monotonic_shadow_required": mode is CostMode.SAME_FILL_SHADOW,
                "new_historical_result": None,
            }
            for mode in CostMode
        },
        "capacity_curve.json": {
            "status": "NOT_COLLECTED",
            "base_capital": "50000",
            "capital_multipliers": ["1", "5", "10", "25", "50"],
            "maximum_tradable_capital": None,
            "coverage": None,
            "empirical_extrapolation_allowed": False,
        },
        "evidence_gaps.json": {
            "gaps": missing,
            "pit_data_quality": sources["b2_safety"]["strict_data_quality"],
            "promotion_admitted": False,
        },
        "report.md": """# B4 有效时点执行与成本契约

**NO_PROVEN_ALPHA / CASH；ML、纸面准入、实盘、订单全部关闭。**

已实现显式成交参考价、已包含成本组件、费用可知时间与有效时间分离、逐部分成交的费用币种/优惠/余额回退、共同 impact 正反函数及时间窗口绑定。旧执行线性代理、旧容量平方根代理分别保留；显式新版输入才采用统一模型。

共享流动性工具复用 decide_fills，检查订单到达/撤单时序、maker queue 未知、窗口总绝对成交额和每事件深度消耗。它只处理输入的同一币种/场所、已知累计窗口截止事件；当前返回 SYNTHETIC_ONLY，不把窗口成交量宣称为瞬时盘口。未成交量和 FOK 失败保留。

SPOT_NATIVE_FEES_V2 为显式独立账本规则：基础币手续费按成交价作 FIFO 库存处置，返佣建立带成本基础的新 lot；交易与费用余额不足时在修改前拒绝。第三币若另有该币交易 lots，必须取得对应估值并接入处置协议，目前明确拒绝。旧账本默认及冻结回放参数保留。

合成 fixture、既有相关纯测试和静态检查见 validation/；真实样本缺失，不能以这些通过记录宣称执行模型已校准。独立校准/验证分割、残差分桶和容量曲线均未采集，实际数据切分与模型拟合为零。真实费用、FX、L1/L2、逐笔和延迟等缺口见 evidence_gaps.json。

仅消费一次本 generation 协议报告；历史策略回放、真实收益模型/校准拟合、最终留出访问和真实订单均为零。后续 B5-B7 工程继续按证据门槛推进。
""",
    }
