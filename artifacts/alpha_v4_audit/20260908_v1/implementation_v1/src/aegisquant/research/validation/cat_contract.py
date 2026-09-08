"""Versioned research contracts; legacy runs reject every undeclared configuration change."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import NonNegativeDecimal, PositiveDecimal, UnitInterval


class CatExecutionPolicy(DomainModel):
    version: Literal["cat-execution-v2"] = "cat-execution-v2"
    fee_bps: NonNegativeDecimal = Decimal("10")
    half_spread_bps: NonNegativeDecimal = Decimal("1")
    slippage_floor_bps: NonNegativeDecimal = Decimal("2")
    natr_slippage_coefficient: NonNegativeDecimal = Decimal("0.01")
    impact_coefficient_bps: NonNegativeDecimal = Decimal("25")
    latency_adverse_bps: NonNegativeDecimal = Decimal("1")
    participation_cap: PositiveDecimal = Field(default=Decimal("0.01"), le=1)
    minimum_notional: PositiveDecimal = Decimal("10")
    latency_ns: int = Field(default=100_000, ge=0)
    price_reserve_natr_fraction: NonNegativeDecimal = Decimal("0.25")
    fee_currency: Literal["QUOTE_USDT_NO_DISCOUNT"] = "QUOTE_USDT_NO_DISCOUNT"
    approximation: Literal["CLOSED_BAR_PROXY_NOT_ORDERBOOK_PROOF"] = (
        "CLOSED_BAR_PROXY_NOT_ORDERBOOK_PROOF"
    )


class CatSwitches(DomainModel):
    use_model_entry_filter: bool = False
    use_cost_entry_gate: bool = False
    use_probability_entry_gate: bool = False
    use_uncertainty_entry_gate: bool = False
    use_model_economic_exit: bool = False
    use_risk_sizing: bool = True
    use_confidence_sizing: bool = False
    use_rebalancing_band: bool = True


class CatAuditPolicy(DomainModel):
    version: Literal["cat-audit-v2"] = "cat-audit-v2"
    execution: CatExecutionPolicy = CatExecutionPolicy()
    switches: CatSwitches = CatSwitches()
    rebalance_weight_band: UnitInterval = Decimal("0.02")
    rebalance_cooldown_seconds: int = Field(default=86400, ge=14400)
    missing_forecast_policy: Literal["NO_ENTRY_HOLD_UNTIL_TREND_OR_RISK_EXIT"] = (
        "NO_ENTRY_HOLD_UNTIL_TREND_OR_RISK_EXIT"
    )
    model_entry_rule: Literal["FROZEN_CALIBRATED_EXPECTED_GROSS_RETURN_GT_ZERO"] = (
        "FROZEN_CALIBRATED_EXPECTED_GROSS_RETURN_GT_ZERO"
    )
    uncertainty_definition: Literal[
        "VALIDATION_RESIDUAL_PREDICTIVE_WIDTH_NOT_MEAN_STANDARD_ERROR"
    ] = "VALIDATION_RESIDUAL_PREDICTIVE_WIDTH_NOT_MEAN_STANDARD_ERROR"
    live_trading: Literal[False] = False
    order_submission_enabled: Literal[False] = False

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


def audit_arms() -> dict[str, CatAuditPolicy]:
    """The fixed eight-arm question; A0 is the separately verified legacy B3."""
    switches = {
        "C0": CatSwitches(use_risk_sizing=False, use_rebalancing_band=False),
        "A1": CatSwitches(),
        "A2": CatSwitches(use_model_entry_filter=True),
        "A3": CatSwitches(use_model_entry_filter=True, use_cost_entry_gate=True),
        "A4": CatSwitches(
            use_model_entry_filter=True, use_cost_entry_gate=True, use_model_economic_exit=True
        ),
        "A5": CatSwitches(
            use_model_entry_filter=True, use_cost_entry_gate=True, use_probability_entry_gate=True
        ),
        "A6": CatSwitches(
            use_model_entry_filter=True,
            use_cost_entry_gate=True,
            use_probability_entry_gate=True,
            use_uncertainty_entry_gate=True,
        ),
        "A7": CatSwitches(
            use_model_entry_filter=True,
            use_cost_entry_gate=True,
            use_probability_entry_gate=True,
            use_uncertainty_entry_gate=True,
            use_confidence_sizing=True,
        ),
    }
    return {name: CatAuditPolicy(switches=value) for name, value in switches.items()}


def compile_legacy_config(root: Path, *, multi_asset: bool = False) -> dict[str, Any]:
    frozen = json.loads(
        (root / "artifacts/alpha_v4/walkforward/run_manifest.json").read_text(encoding="utf-8")
    )
    declared = {
        "strategy": yaml.safe_load(
            (root / "configs/strategies/aegisalpha_cat_v1.yaml").read_text(encoding="utf-8")
        ),
        "research": yaml.safe_load(
            (root / "configs/research/aegis_alpha_v4.yaml").read_text(encoding="utf-8")
        ),
    }
    expected = {"strategy": frozen["strategy_config"], "research": frozen["research_config"]}
    if multi_asset:
        declared["multi_asset"] = yaml.safe_load(
            (root / "configs/research/alpha_v4_multi_asset.yaml").read_text(encoding="utf-8")
        )
        expected["multi_asset"] = json.loads(
            (root / "artifacts/alpha_v4_multi_asset/run_manifest.json").read_text(encoding="utf-8")
        )["policy"]
    if declared != expected:
        raise ValueError(
            "legacy v1 configuration changed; every field is frozen, use a registered v2 experiment"
        )
    return {
        "version": "cat-legacy-effective-v1",
        "declared": declared,
        "effective_sha256": canonical_sha256(declared),
        "label_contract": {
            "version": "decision-offset-v1",
            "entry_offset": 1,
            "exit_offset": 6,
            "holding_intervals": 5,
            "return_unit": "arithmetic",
        },
        "trend_score": "ma_distance_natr_column_0",
        "trend_validity": "all_17_features",
        "execution": {
            "fee_bps": 10,
            "half_spread_bps": 1,
            "slippage_floor_bps": 2,
            "natr_slippage_coefficient": 0.01,
            "impact_coefficient_bps": 25,
            "latency_adverse_bps": 1,
            "cash_reserve_fraction": 0.01,
            "fee_currency": "QUOTE_USDT_NO_DISCOUNT",
            "latency_ns": 100000,
        },
        "sizing": "B7_DAILY_RISK_CAP_REDUCE_ONLY_CONFIDENCE_AT_ENTRY",
        "unsupported_changes": "REJECT_ALL_LEGACY_CONFIGURATION_PERTURBATIONS",
    }
