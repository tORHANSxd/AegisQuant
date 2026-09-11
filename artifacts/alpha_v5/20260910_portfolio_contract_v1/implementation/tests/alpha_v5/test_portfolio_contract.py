"""B5 supplied/synthetic covariance, cash, risk and ledger contracts; no engine replay."""

from __future__ import annotations

import copy
import json
import sys
from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

import pytest
import yaml

from aegisquant.accounting.ledger import LedgerEngine
from aegisquant.accounting.models import AccountingInstrument, FxRate, ValuationQuote
from aegisquant.data.hashing import sha256_file
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import InstrumentId, ProposalId, VenueId
from aegisquant.execution.accounts import AccountBalance
from aegisquant.portfolio.models import (
    CovarianceEstimate,
    CovarianceInputContract,
    ExposureConstraint,
    ExposureDimension,
    FactorRisk,
    PortfolioConstructionPolicy,
    RiskRegime,
    SignalInput,
)
from aegisquant.portfolio.optimizer import build_portfolio_proposal
from aegisquant.portfolio.risk_estimation import estimate_covariance
from aegisquant.research.validation import evidence_contract as evidence
from aegisquant.research.validation import portfolio_replay as bridge
from aegisquant.risk.engine import build_risk_snapshot
from aegisquant.risk.models import RiskPosition, RiskSnapshot, RiskState
from aegisquant.risk.stress import PortfolioStressScenario
from tests import p11_helpers as p11
from tests.alpha_v5.test_benchmark_contract import r5_fixture
from tests.alpha_v5.test_execution_contract import cash, curve, native_ledger
from tests.p05 import helpers as accounting

D = Decimal
ROOT = Path(__file__).resolve().parents[2]
NOW = p11.AS_OF
BTC, ETH, USDT = p11.BTC, p11.ETH, p11.USDT
HASH = "1" * 64


def cov_args() -> dict[str, Any]:
    return dict(
        asset_ids=(BTC, ETH),
        sample_covariance=((D("0.0001"), D("0")), (D("0"), D("0.0001"))),
        shrinkage=D("0.2"),
        factors=(),
        regime=RiskRegime.NORMAL,
        regime_multiplier=D("1"),
        observed_at=NOW - timedelta(days=1),
        available_at=NOW,
        contract=CovarianceInputContract(
            basis="TOTAL", complete_calendar_observations=90, input_sha256=HASH
        ),
    )


def test_symmetric_positive_diagonal_indefinite_covariance_fails_before_shrinkage() -> None:
    args = cov_args()
    args["sample_covariance"] = ((D("1"), D("2")), (D("2"), D("1")))
    args["shrinkage"] = D("1")
    with pytest.raises(ValueError, match="NOT-PSD"):
        estimate_covariance(**args)
    base = estimate_covariance(**cov_args())
    with pytest.raises(ValueError, match="NOT-PSD"):
        CovarianceEstimate.model_validate({**dict(base), "matrix": args["sample_covariance"]})


def test_total_cannot_double_count_factor_and_residual_requires_defined_factors() -> None:
    args = cov_args()
    factor = FactorRisk(
        factor_id="market", variance=D("0.0002"), exposures={"BTC": D("1"), "ETH": D("1")}
    )
    args["factors"] = (factor,)
    with pytest.raises(ValueError, match="TOTAL-CANNOT"):
        estimate_covariance(**args)
    args["contract"] = args["contract"].model_copy(update={"basis": "RESIDUAL"})
    result = estimate_covariance(**args)
    assert result.matrix[0][0] == D("0.0003") * D("365.25")
    assert result.matrix[0][1] == D("0.0002") * D("365.25")
    args["factors"] = ()
    with pytest.raises(ValueError, match="REQUIRES-DEFINED"):
        estimate_covariance(**args)


def test_fixed_tiny_psd_correction_is_recorded_and_asset_order_invariant() -> None:
    args = cov_args()
    args["sample_covariance"] = ((D("1"), D("1.0000000000001")), (D("1.0000000000001"), D("1")))
    args["shrinkage"] = D("0")
    a = estimate_covariance(**args)
    assert a.evidence is not None and a.evidence.diagonal_jitter > 0
    assert a.evidence.correction_frobenius_norm > 0
    args["asset_ids"] = (ETH, BTC)
    b = estimate_covariance(**args)
    assert a.matrix == b.matrix and a.evidence == b.evidence
    args["sample_covariance"] = ((D("1"), D("1")), (D("1"), D("1")))
    perfect = estimate_covariance(**args)
    assert perfect.matrix[0][0] >= perfect.matrix[0][1]


def daily_rows() -> list[dict[str, Any]]:
    end = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    return [
        dict(
            close_time=(end - timedelta(days=89 - i)).isoformat(),
            available_time=(end - timedelta(days=89 - i)).isoformat(),
            returns={"BTC": str(D((i % 7) - 3) / 1000), "ETH": str(D((i % 7) - 3) / 500)},
        )
        for i in range(90)
    ]


def test_closed_daily_covariance_future_mutations_and_reordering_do_not_change_past() -> None:
    rows = daily_rows()
    base = bridge.daily_covariance_from_rows(rows, asset_ids=(BTC, ETH), decision_time=NOW)
    future = dict(
        close_time=(NOW + timedelta(days=1)).isoformat(),
        available_time=(NOW + timedelta(days=2)).isoformat(),
        returns={"BTC": "999", "UNKNOWN": "-999"},
    )
    changed = bridge.daily_covariance_from_rows(
        [future, *reversed(rows)], asset_ids=(ETH, BTC), decision_time=NOW
    )
    assert base == changed and base.evidence is not None
    assert base.evidence.contract.complete_calendar_observations == 90
    assert base.evidence.contract.return_frequency == "UTC_DAILY"


@pytest.mark.parametrize("kind", ["gap", "asset", "duplicate", "intraday", "late", "zero"])
def test_missing_new_asset_or_unready_covariance_fails_closed(kind: str) -> None:
    rows = daily_rows()
    if kind == "gap":
        rows.pop(20)
    elif kind == "asset":
        rows[20]["returns"].pop("ETH")
    elif kind == "duplicate":
        rows.append(copy.deepcopy(rows[20]))
    elif kind == "intraday":
        rows[20]["close_time"] = (NOW - timedelta(days=60)).isoformat()
    elif kind == "late":
        rows[20]["available_time"] = (NOW + timedelta(days=1)).isoformat()
    else:
        for row in rows:
            row["returns"] = {"BTC": "0", "ETH": "0"}
        zero = bridge.daily_covariance_from_rows(rows, asset_ids=(BTC, ETH), decision_time=NOW)
        with pytest.raises(ValueError, match="NONPOSITIVE-ASSET-VARIANCE"):
            build_portfolio_proposal(
                proposal_id=ProposalId("zero"),
                signals=p11.signals(),
                covariance=zero,
                policy=p11.construction_policy(),
                portfolio_nav=D("1000"),
                as_of_time=NOW,
                created_at=NOW,
                raw_target_weights={s.instrument_id: D("0.1") for s in p11.signals()},
            )
        return
    with pytest.raises(ValueError):
        bridge.daily_covariance_from_rows(rows, asset_ids=(BTC, ETH), decision_time=NOW)


def assets(
    *, adv: str = "1000000", step: str = "0.01", cost: str = "0.01"
) -> tuple[bridge.BridgeAsset, ...]:
    result: list[bridge.BridgeAsset] = []
    for asset in (BTC, ETH):
        spec = AccountingInstrument.model_validate(
            {
                **dict(accounting.spot_instrument()),
                "instrument_id": InstrumentId(f"SIM:SPOT:{asset}USDT"),
                "base_asset_id": asset,
                "quantity_asset_id": asset,
            }
        )
        context = p11.signal(
            asset=asset,
            instrument=str(spec.instrument_id),
            raw_score=D("1"),
            confidence=D("1"),
            adv=D(adv),
            impact_bps=D("10"),
            cluster="crypto",
        )
        context = SignalInput.model_validate(
            {
                **dict(context),
                "venue_id": VenueId("SIM"),
                "impact_model": curve(),
                "liquidity_horizon_seconds": 60,
            }
        )
        result.append(
            bridge.BridgeAsset(
                instrument=spec,
                signal=context,
                mark=D("100"),
                quantity_step=D(step),
                minimum_notional=D("1"),
                maximum_execution_cost_fraction=D(cost),
                available_at=NOW,
            )
        )
    return tuple(result)


def construction() -> PortfolioConstructionPolicy:
    return p11.construction_policy().model_copy(
        update={
            "maximum_gross_weight": D("0.9"),
            "maximum_turnover": D("1"),
            "volatility_target": D("0.5"),
            "exposure_constraints": tuple(
                ExposureConstraint(dimension=dimension, key=key, maximum_absolute_weight=D(value))
                for dimension, key, value in (
                    (ExposureDimension.ASSET, "BTC", "0.6"),
                    (ExposureDimension.ASSET, "ETH", "0.6"),
                    (ExposureDimension.CORRELATION_CLUSTER, "crypto", "0.9"),
                )
            ),
        }
    )


def account_args(
    ledger: LedgerEngine,
    selected: tuple[bridge.BridgeAsset, ...] | None = None,
    *,
    available: str | None = None,
    unsettled: str = "0",
    pending: tuple[bridge.PendingReservation, ...] = (),
) -> dict[str, Any]:
    selected = selected or assets()
    total = cash(ledger, USDT)
    return dict(
        assets=selected,
        quote_balance=AccountBalance(
            asset_id=USDT, total=total, available=total if available is None else D(available)
        ),
        fx_rates={
            a.instrument.base_asset_id: FxRate(
                asset_id=a.instrument.base_asset_id,
                reporting_asset_id=USDT,
                rate=a.mark,
                as_of_time=NOW,
                policy_version="SYNTHETIC",
            )
            for a in selected
        },
        pending=pending,
        unsettled_quote=D(unsettled),
        decision_time=NOW,
        balance_available_at=NOW,
        fx_available_at=NOW,
    )


def snapshot(account: bridge.BridgeAccount, **changes: Any) -> RiskSnapshot:
    values: dict[str, Any] = dict(
        snapshot_id="b5-synthetic",
        as_of_time=NOW,
        available_at=NOW,
        data_last_available_at=NOW,
        model_last_available_at=NOW,
        positions=tuple(
            RiskPosition(
                instrument_id=a.instrument.instrument_id,
                asset_id=a.signal.asset_id,
                strategy_id=a.signal.strategy_id,
                account_id=a.signal.account_id,
                signed_weight=account.current_quantities[a.instrument.instrument_id]
                * a.mark
                / account.nav,
            )
            for a in account.assets
        ),
        daily_pnl_fraction=D("0"),
        drawdown_fraction=D("0"),
        margin_utilization=D("0"),
        liquidity_score=D("1"),
        venue_operational=True,
        security_clear=True,
        major_event_clear=True,
        ledger_reconciled=True,
    )
    values.update(changes)
    return build_risk_snapshot(**values)


def plan_args(
    ledger: LedgerEngine,
    account: bridge.BridgeAccount,
    *,
    targets: Mapping[InstrumentId, Decimal] | None = None,
    policy: PortfolioConstructionPolicy | None = None,
    **changes: Any,
) -> dict[str, Any]:
    values: dict[str, Any] = dict(
        ledger=ledger,
        account=account,
        raw_target_weights=targets
        or {a.instrument.instrument_id: D("0.2") for a in account.assets},
        covariance=estimate_covariance(**cov_args()),
        construction=policy or construction(),
        risk_snapshot=snapshot(account),
        signed_policy=p11.signed_policy(),
        trusted_public_keys=p11.trusted_public_keys(),
        prior_risk_state=RiskState.NORMAL,
        risk_transition_sequence=1,
        tail_evidence_ready=True,
    )
    return {**values, **changes}


def test_funded_buys_compete_proportionally_and_input_order_is_invariant() -> None:
    ledger = native_ledger()
    selected = assets()
    a = bridge.account_from_ledger(ledger, **account_args(ledger, selected, available="100"))
    plan = bridge.plan_shared_capital(**plan_args(ledger, a))
    assert set(plan.signed_quantities.values()) == {D("0.49")}
    assert plan.quote_required == D("98.98") <= a.quote_available
    assert plan.proposal.expected_return == 0 and all(
        leg.expected_return_contribution == 0 for leg in plan.proposal.legs
    )
    b = bridge.account_from_ledger(
        ledger, **account_args(ledger, tuple(reversed(selected)), available="100")
    )
    other = bridge.plan_shared_capital(**plan_args(ledger, b))
    assert plan == other
    assert not plan.diagnostics["post_rounding_risk"]["breaches"]


def test_unfilled_sales_and_unsettled_cash_never_finance_buys() -> None:
    ledger, selected = native_ledger(), assets(cost="0")
    ledger.process_fill(
        accounting.fill(
            selected[0].instrument, sequence=1, side=OrderSide.BUY, quantity="2", price="100"
        ),
        selected[0].instrument,
    )
    account = bridge.account_from_ledger(ledger, **account_args(ledger, selected, available="0"))
    targets = {
        selected[0].instrument.instrument_id: D("0"),
        selected[1].instrument.instrument_id: D("0.2"),
    }
    plan = bridge.plan_shared_capital(**plan_args(ledger, account, targets=targets))
    assert plan.signed_quantities[selected[0].instrument.instrument_id] == D("-2")
    assert plan.signed_quantities[selected[1].instrument.instrument_id] == 0
    assert plan.diagnostics["assumed_sale_proceeds"] == "0"
    ledger.process_fill(
        accounting.fill(
            selected[0].instrument, sequence=2, side=OrderSide.SELL, quantity="0.5", price="100"
        ),
        selected[0].instrument,
    )
    with pytest.raises(ValueError, match="LEDGER-CHANGED"):
        bridge.plan_shared_capital(**plan_args(ledger, account, targets=targets))
    fresh = bridge.account_from_ledger(
        ledger, **account_args(ledger, selected, available="50", unsettled="850")
    )
    recomputed = bridge.plan_shared_capital(**plan_args(ledger, fresh, targets=targets))
    assert recomputed.signed_quantities[selected[0].instrument.instrument_id] == D("-1.5")
    assert recomputed.signed_quantities[selected[1].instrument.instrument_id] == 0


def pending_buy(
    selected: tuple[bridge.BridgeAsset, ...], quantity: str = "4.5"
) -> bridge.PendingReservation:
    return bridge.PendingReservation(
        order_id="pending-btc",
        instrument_id=selected[0].instrument.instrument_id,
        side=OrderSide.BUY,
        remaining_quantity=D(quantity),
        maximum_price=D("100"),
        maximum_cost_fraction=D("0"),
        available_at=NOW,
    )


def test_pending_risk_and_reserves_are_not_netted_by_hoped_for_cancellation() -> None:
    ledger, selected = native_ledger(), assets(cost="0")
    pending = pending_buy(selected)
    account = bridge.account_from_ledger(
        ledger, **account_args(ledger, selected, pending=(pending,))
    )
    assert account.quote_available == D("550") and account.pending_quote_reserved == D("450")
    plan = bridge.plan_shared_capital(**plan_args(ledger, account))
    assert plan.cancel_first == (pending.order_id,)
    assert set(plan.signed_quantities.values()) == {D("0")}
    assert plan.status == "BREACH_UNEXECUTABLE_OR_PENDING"
    assert "ASSET:BTC" in plan.diagnostics["worst_fill_order_risk"]["breaches"]
    assert account.quote_available == D("550")


@pytest.mark.parametrize(
    "kind",
    [
        "future_balance",
        "future_fx",
        "future_pending",
        "overreserved",
        "oversold",
        "opposing",
        "unknown_pending",
        "bad_cash",
        "future_ledger",
    ],
)
def test_bad_funding_inputs_fail_before_proposal(kind: str) -> None:
    ledger, selected = native_ledger(), assets()
    args = account_args(ledger, selected)
    p = pending_buy(selected, "1")
    if kind == "future_balance":
        args["balance_available_at"] = NOW + timedelta(seconds=1)
    elif kind == "future_fx":
        args["fx_available_at"] = NOW + timedelta(seconds=1)
    elif kind == "future_pending":
        args["pending"] = (p.model_copy(update={"available_at": NOW + timedelta(seconds=1)}),)
    elif kind == "overreserved":
        args["pending"] = (p.model_copy(update={"remaining_quantity": D("11")}),)
    elif kind == "oversold":
        args["pending"] = (p.model_copy(update={"side": OrderSide.SELL}),)
    elif kind == "opposing":
        args["pending"] = (p, p.model_copy(update={"order_id": "opposite", "side": OrderSide.SELL}))
    elif kind == "unknown_pending":
        args["pending"] = (p.model_copy(update={"instrument_id": InstrumentId("UNKNOWN")}),)
    elif kind == "bad_cash":
        args["quote_balance"] = AccountBalance(asset_id=USDT, total=D("999"), available=D("999"))
    else:
        args["decision_time"] = accounting.NOW - timedelta(seconds=1)
        args["balance_available_at"] = args["fx_available_at"] = args["decision_time"]
        args["assets"] = tuple(
            a.model_copy(update={"available_at": args["decision_time"]}) for a in selected
        )
    with pytest.raises(ValueError):
        bridge.account_from_ledger(ledger, **args)


def test_hard_risk_bypasses_turnover_but_retains_liquidity_breach() -> None:
    ledger, selected = native_ledger(), assets(adv="100", cost="0")
    ledger.process_fill(
        accounting.fill(
            selected[0].instrument, sequence=1, side=OrderSide.BUY, quantity="5", price="100"
        ),
        selected[0].instrument,
    )
    account = bridge.account_from_ledger(ledger, **account_args(ledger, selected))
    tiny_turnover = construction().model_copy(update={"maximum_turnover": D("0.0001")})
    plan = bridge.plan_shared_capital(**plan_args(ledger, account, policy=tiny_turnover))
    assert plan.signed_quantities[selected[0].instrument.instrument_id] == D("-0.1")
    assert all(value <= 0 for value in plan.signed_quantities.values())
    assert plan.status == "BREACH_UNEXECUTABLE_OR_PENDING"
    assert plan.proposal.turnover > tiny_turnover.maximum_turnover
    assert "ASSET:BTC" in plan.diagnostics["post_rounding_risk"]["breaches"]
    assert cash(ledger, BTC) == D("5")


def test_halted_venue_and_depeg_do_not_invent_an_exit() -> None:
    ledger, selected = native_ledger(), assets(cost="0")
    ledger.process_fill(
        accounting.fill(
            selected[0].instrument, sequence=1, side=OrderSide.BUY, quantity="2", price="100"
        ),
        selected[0].instrument,
    )
    account = bridge.account_from_ledger(ledger, **account_args(ledger, selected))
    stopped = snapshot(account, venue_operational=False)
    plan = bridge.plan_shared_capital(**plan_args(ledger, account, risk_snapshot=stopped))
    assert not any(plan.signed_quantities.values()) and cash(ledger, BTC) == 2
    scenario = PortfolioStressScenario(
        scenario_id="SYNTHETIC-DEPEG-HALT",
        asset_return_shocks={"BTC": D("-0.4"), "ETH": D("-0.4")},
        stablecoin_return_shocks={"USDT": D("-0.1")},
        correlation_multiplier=D("2"),
        liquidity_multiplier=D("0"),
        margin_multiplier=D("1"),
        unavailable_venues=(VenueId("SIM"),),
    )
    stress = bridge.joint_stress_diagnostic(
        plan=plan,
        account=account,
        snapshot=stopped,
        signed_policy=p11.signed_policy(),
        scenario=scenario,
    )
    assert stress["execution_status"] == "UNEXECUTABLE" and stress[
        "actual_positions_not_exited"
    ] == [str(selected[0].instrument.instrument_id)]
    assert stress["realized_tail_loss"] is None and not stress["instant_cash_assumed"]


def test_post_rounding_risk_includes_execution_cost_loss_in_nav() -> None:
    ledger, selected = native_ledger(), assets(step="1", cost="0.5")
    account = bridge.account_from_ledger(ledger, **account_args(ledger, selected))
    targets = {a.instrument.instrument_id: D("0.3") for a in selected}
    plan = bridge.plan_shared_capital(**plan_args(ledger, account, targets=targets))
    assert not any(plan.signed_quantities.values())
    assert "POST_ROUNDING_RISK" in plan.diagnostics["blocked"]
    assert plan.quote_required == 0


def test_unknown_tail_evidence_blocks_increase_but_not_risk_exit() -> None:
    ledger, selected = native_ledger(), assets(cost="0")
    account = bridge.account_from_ledger(ledger, **account_args(ledger, selected))
    plan = bridge.plan_shared_capital(**plan_args(ledger, account, tail_evidence_ready=False))
    assert not any(plan.signed_quantities.values())
    point = bridge.cvar_evidence([D("-0.01")] * 90)
    assert point["tail_mass"] == "4.50" and point["daily_cvar95_point"] == "0.01"
    assert not point["safety_proven"] and point["block_uncertainty"] is None


def test_signed_order_limit_still_bounds_the_actual_rounded_quantity() -> None:
    ledger, selected = native_ledger(), assets(cost="0")
    account = bridge.account_from_ledger(ledger, **account_args(ledger, selected))
    targets = {
        selected[0].instrument.instrument_id: D("0.4"),
        selected[1].instrument.instrument_id: D("0"),
    }
    plan = bridge.plan_shared_capital(**plan_args(ledger, account, targets=targets))
    maximum = p11.signed_policy().policy.pre_trade_limits.maximum_order_weight
    assert maximum == D("0.3")
    assert plan.signed_quantities[selected[0].instrument.instrument_id] == D("3")
    for asset in selected:
        assert (
            abs(plan.signed_quantities[asset.instrument.instrument_id]) * asset.mark / account.nav
            <= maximum
        )


def test_normalized_risk_snapshot_cannot_automatically_unlock_a_previous_hard_gate() -> None:
    ledger = native_ledger()
    account = bridge.account_from_ledger(ledger, **account_args(ledger))
    first = bridge.plan_shared_capital(
        **plan_args(ledger, account, risk_snapshot=snapshot(account, daily_pnl_fraction=D("-0.06")))
    )
    assert first.diagnostics["effective_risk_state"] == "REDUCE_ONLY"
    assert first.diagnostics["risk_transition"]["automatic"] is True
    second = bridge.plan_shared_capital(
        **plan_args(ledger, account, prior_risk_state=RiskState.REDUCE_ONLY)
    )
    assert second.risk_decision.state is RiskState.REDUCE_ONLY
    assert second.risk_decision.new_risk_allowed is False
    assert not any(second.signed_quantities.values())
    assert not second.diagnostics["automatic_recovery_allowed"]


def test_legacy_optimizer_payload_matches_sealed_b4_implementation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = ROOT / "artifacts/alpha_v5/20260910_execution_contract_v1"
    name = "implementation/src/aegisquant/portfolio/optimizer.py"
    manifest = json.loads((frozen / "OUTPUT_MANIFEST.json").read_text(encoding="utf-8"))
    assert sha256_file(frozen / name) == manifest["files"][name]["sha256"]
    module = ModuleType("b5_legacy_optimizer")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile((frozen / name).read_bytes(), str(frozen / name), "exec"), module.__dict__)  # noqa: S102 -- hash-verified frozen project code, synthetic inputs only.
    kwargs: dict[str, Any] = dict(
        proposal_id=ProposalId("same-synthetic"),
        signals=p11.signals(),
        covariance=p11.covariance(),
        policy=p11.construction_policy(),
        portfolio_nav=D("100000"),
        as_of_time=NOW,
        created_at=p11.CREATED,
    )
    assert build_portfolio_proposal(**kwargs).model_dump(
        mode="json"
    ) == module.build_portfolio_proposal(**kwargs).model_dump(mode="json")
    assert "evidence" not in p11.covariance().model_dump()


def test_spot_native_mtm_values_price_move_once_and_legacy_stays_distinct() -> None:
    ledger = native_ledger()
    instrument = accounting.spot_instrument()
    ledger.process_fill(
        accounting.fill(instrument, sequence=1, side=OrderSide.BUY, quantity="1", price="100"),
        instrument,
    )
    valuation = ledger.valuation_snapshot(
        {
            instrument.instrument_id: ValuationQuote(
                instrument_id=instrument.instrument_id,
                as_of_time=NOW,
                available_time=NOW,
                mark=D("200"),
            )
        }
    )
    fx = {
        BTC: FxRate(
            asset_id=BTC,
            reporting_asset_id=USDT,
            rate=D("200"),
            as_of_time=NOW,
            policy_version="SYNTHETIC",
        )
    }
    legacy = ledger.equity_snapshot(valuation=valuation, reporting_asset_id=USDT, fx_rates=fx)
    current = ledger.equity_snapshot(
        valuation=valuation,
        reporting_asset_id=USDT,
        fx_rates=fx,
        valuation_basis="SPOT_NATIVE_MTM_V2",
    )
    assert legacy.equity == D("1200") and current.equity == D("1100")
    assert current.unrealized_pnl_value == 0 and valuation.lots[0].unrealized_pnl.amount == D("100")
    assert current.account_snapshot_id != legacy.account_snapshot_id


def test_drawdown_windows_do_not_conflate_full_period_loss_and_recent_recovery() -> None:
    rows = [
        dict(
            close_time=(NOW - timedelta(days=39 - i)).isoformat(),
            available_time=(NOW - timedelta(days=39 - i)).isoformat(),
            equity="100" if i == 0 else "80",
        )
        for i in range(40)
    ]
    value = bridge.drawdown_history(rows, decision_time=NOW)
    assert D(value["full_period_maximum_drawdown"]) == D("0.2")
    assert D(value["trailing_30d_maximum_drawdown"]) == 0
    assert value["full_period_maximum_duration_days"] == 39
    assert value["automatic_recovery_allowed"] is False
    assert (
        bridge.drawdown_history(rows[-5:], decision_time=NOW)["trailing_30d_maximum_drawdown"]
        is None
    )


@pytest.mark.parametrize("kind", ["data", "adopt", "runs", "policy", "capital"])
def test_b5_report_cannot_activate_economic_research(kind: str) -> None:
    config = yaml.safe_load(
        (ROOT / "configs/research/alpha_v5_portfolio_contract.yaml").read_text(encoding="utf-8")
    )
    if kind == "data":
        config["historical_portfolio_inputs"] = "history.csv"
    elif kind == "adopt":
        config["economic_policy_adopted"] = True
    elif kind == "runs":
        config["future_scenarios"]["authorized_runs_now"] = 9
    elif kind == "policy":
        config["proposed_risk_policy"]["volatility_target_annual"] = "0.5"
    else:
        config["future_scenarios"]["capital"] = "500000"
    with pytest.raises(ValueError):
        bridge.validate_config(config)


def test_b5_contract_job_seals_without_invoking_real_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    for name in bridge.FILES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("SYNTHETIC_IMPLEMENTATION", encoding="utf-8")
    config = yaml.safe_load(
        (ROOT / "configs/research/alpha_v5_portfolio_contract.yaml").read_text(encoding="utf-8")
    )
    manifest = root / config["sources"]["r5_manifest"]["path"]
    manifest.parent.mkdir(parents=True, exist_ok=True)
    source = r5_fixture()
    manifest.write_text(json.dumps(source), encoding="utf-8")
    research_config = root / "configs/research/aegis_alpha_v5.yaml"
    research_config.write_text(yaml.safe_dump(source["config"]), encoding="utf-8")
    lock = root / "src/aegisquant/bootstrap/live_lock.py"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        "LIVE_TRADING: bool = False\nORDER_SUBMISSION_ENABLED: bool = False\nLIVE_ADAPTERS: tuple = ()\n",
        encoding="utf-8",
    )
    config["sources"]["r5_manifest"]["sha256"] = sha256_file(manifest)
    for name in ("b4_manifest", "b2_safety"):
        path = root / config["sources"][name]["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"strict_data_quality": "FAILED_CLOSED_INSUFFICIENT_PIT_EVIDENCE"}),
            encoding="utf-8",
        )
        config["sources"][name]["sha256"] = sha256_file(path)
    stage = tmp_path / "preflight"
    stage.mkdir()
    (stage / "baseline_workspace.json").write_text(
        json.dumps(
            {
                "root": str(root),
                "branch": "main",
                "head": evidence.BASE,
                "files": {},
                "allowed_modifications": [],
            }
        ),
        encoding="utf-8",
    )
    for name in ("workspace_before.patch", "version_graph.txt", "test_commands_and_results.txt"):
        (stage / name).write_text("SYNTHETIC", encoding="utf-8")
    hashes = {name: sha256_file(root / name) for name in bridge.FILES}
    (stage / "validation_records.json").write_text(
        json.dumps(
            [
                dict(check=k, command=["SYNTHETIC"], exit_code=0, source_sha256=hashes)
                for k in ("ruff", "format", "pyright", "pytest")
            ]
        ),
        encoding="utf-8",
    )
    (stage / "pytest_results.xml").write_text(
        '<testsuite><testcase name="SYNTHETIC"/></testsuite>', encoding="utf-8"
    )

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("real portfolio work not authorized")

    monkeypatch.setattr(bridge, "plan_shared_capital", forbidden)
    monkeypatch.setattr(bridge, "daily_covariance_from_rows", forbidden)
    monkeypatch.setattr(bridge, "run_portfolio_stress", forbidden)
    bridge.validate_config(config)
    output = evidence.run_zero_research_contract(
        root=root,
        config=config,
        stage=stage,
        git_state={"head": evidence.BASE, "branch": "main"},
        files=bridge.FILES,
        build_documents=bridge.build_documents,
    )
    assert evidence.load_evidence_manifest(output, "OUTPUT_MANIFEST.json")["status"] == "VERIFIED"
    actual = json.loads((output / "safety_and_budget_audit.json").read_text())["actual"]
    assert actual.pop("contract_jobs") == 1 and not any(actual.values())
    assert (
        json.loads((output / "three_mode_attribution.json").read_text())[
            "funding_bridge_contribution"
        ]
        is None
    )
