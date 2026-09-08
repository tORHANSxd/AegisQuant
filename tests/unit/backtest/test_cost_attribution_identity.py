from datetime import timedelta
from decimal import Decimal

from aegisquant.backtest.models import FundingEvent
from aegisquant.domain.accounting import PostingSide
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import BacktestEventId
from tests.p06.helpers import NOW, engine, perp_bars, perp_instrument, perp_order, run_spec


def test_contract_multiplier_costs_funding_and_settlement_close_against_reference_pnl() -> None:
    instrument = perp_instrument().model_copy(update={"contract_multiplier": Decimal("10")})
    values = perp_bars()
    funding = FundingEvent(
        event_id=BacktestEventId("funding-multiplier"),
        instrument_id=instrument.instrument_id,
        venue_id=values[1].venue_id,
        base_asset_id=instrument.base_asset_id,
        quote_asset_id=instrument.quote_asset_id,
        event_time=NOW + timedelta(seconds=1, microseconds=1),
        available_time=NOW + timedelta(seconds=1, microseconds=1),
        mark_price=Decimal("100"),
        funding_rate=Decimal("0.001"),
    )
    result = engine().run(
        spec=run_spec(),
        instrument=instrument,
        market_events=values,
        funding_events=(funding,),
        orders=(
            perp_order(
                sequence=1,
                side=OrderSide.BUY,
                quantity="1",
                submitted_at=NOW + timedelta(microseconds=1),
            ),
            perp_order(
                sequence=2,
                side=OrderSide.SELL,
                quantity="1",
                submitted_at=NOW + timedelta(seconds=2, microseconds=1),
            ),
        ),
    )
    costs = result.pnl_attribution[-1]
    assert costs.funding == Decimal("1")
    assert costs.settlement_fees > 0
    assert costs.gross_trading_pnl == Decimal("-200")
    assert costs.net_pnl == result.equity_curve[-1].equity - result.spec.initial_cash.amount
    assert result.cost_identity_residual == 0
    assert result.fills[0].cost_breakdown.gross_notional == Decimal("1000")
    for record in result.ledger_records:
        balances: dict[str, Decimal] = {}
        for posting in record.journal_entry.postings:
            sign = Decimal("1") if posting.side is PostingSide.DEBIT else Decimal("-1")
            asset = str(posting.amount.asset_id)
            balances[asset] = balances.get(asset, Decimal("0")) + sign * posting.amount.amount
        assert all(value == 0 for value in balances.values())
