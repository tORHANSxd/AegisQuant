from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aegisquant.backtest.models import EquityPoint
from aegisquant.domain.identifiers import AssetId
from aegisquant.research.validation.multi_asset import combine_independent_sleeves


def curve(values: tuple[str, ...], *, offset: int = 0) -> tuple[EquityPoint, ...]:
    return tuple(
        EquityPoint(
            time=datetime(2022, 1, 1, tzinfo=UTC) + timedelta(hours=4 * i + offset),
            cash=Decimal(value),
            position_value=Decimal("0"),
            realized_pnl=Decimal(value) - Decimal(values[0]),
            unrealized_pnl=Decimal("0"),
            equity=Decimal(value),
            reporting_asset_id=AssetId("USDT"),
        )
        for i, value in enumerate(values)
    )


def test_independent_sleeves_do_not_imply_free_continuous_rebalancing() -> None:
    combined = combine_independent_sleeves(
        {"A": curve(("100", "200", "200")), "B": curve(("100", "100", "50"))}
    )
    assert [point.equity for point in combined] == [Decimal(v) for v in ("200", "300", "250")]
    assert combined[-1].equity / combined[0].equity == Decimal("1.25")
    # Averaging each bar's sleeve returns would manufacture rebalancing and yield 1.125.
    assert combined[-1].equity / combined[0].equity != Decimal("1.5") * Decimal("0.75")


def test_misaligned_sleeves_are_rejected_instead_of_using_future_marks() -> None:
    with pytest.raises(ValueError, match="complete reporting clock"):
        combine_independent_sleeves(
            {"A": curve(("100", "110")), "B": curve(("100", "120"), offset=1)}
        )
