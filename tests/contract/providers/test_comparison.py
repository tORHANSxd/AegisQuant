from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from aegisquant.data.market import (
    ClockObservation,
    MarketObservation,
    ProviderBatch,
    Venue,
    compare_venues,
    lead_lag_dataset,
)
from aegisquant.data.providers.public import (
    normalize_bybit_instruments,
    normalize_deribit_instruments,
    normalize_market_observation,
    normalize_okx_instruments,
)
from aegisquant.domain.identifiers import InstrumentId, ProviderId

NOW = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def observation(
    provider: str,
    venue: Venue,
    *,
    seconds: int = 0,
    exposure: str = "exposure:btc-usdt-linear-perp",
    quote: str = "asset:usdt",
    quality: str = "0.99",
    event_key: str | None = "move-1",
) -> MarketObservation:
    event_time = NOW + timedelta(seconds=seconds)
    return MarketObservation(
        provider_id=ProviderId(provider),
        venue=venue,
        instrument_id=InstrumentId(f"{provider}:btcusdt"),
        exposure_id=exposure,
        quote_asset_id=quote,
        event_time=event_time,
        available_time=event_time,
        ingest_time=event_time,
        bid=Decimal("99990"),
        ask=Decimal("100010"),
        mark=Decimal("100020"),
        index=Decimal("100000"),
        funding_rate=Decimal("0.0001"),
        open_interest=Decimal("1000"),
        liquidity_notional=Decimal("500000"),
        quality_score=Decimal(quality),
        event_key=event_key,
    )


def test_comparison_filters_time_quote_quality_and_isolates_failed_provider() -> None:
    batches = (
        ProviderBatch(
            provider_id=ProviderId("okx_public"),
            observations=(observation("okx_public", Venue.OKX),),
        ),
        ProviderBatch(
            provider_id=ProviderId("bybit_public"),
            observations=(observation("bybit_public", Venue.BYBIT, quote="asset:usd"),),
        ),
        ProviderBatch(
            provider_id=ProviderId("deribit_public"), error_code="AQ-PROVIDER-DISCONNECTED"
        ),
    )
    result = compare_venues(
        batches,
        as_of_time=NOW + timedelta(seconds=1),
        exposure_id="exposure:btc-usdt-linear-perp",
        quote_asset_id="asset:usdt",
        maximum_age=timedelta(seconds=5),
        minimum_quality=Decimal("0.9"),
    )
    assert [row.venue for row in result.rows] == [Venue.OKX]
    assert result.rows[0].basis_bps == Decimal("2.0000")
    assert result.filtered_observation_count == 1
    assert result.rejected_provider_ids == (ProviderId("deribit_public"),)


def test_clock_offset_and_lead_lag_are_explicit_datasets() -> None:
    sample = ClockObservation.create(
        ProviderId("okx_public"),
        request_sent_time=NOW,
        server_time=NOW + timedelta(milliseconds=15),
        response_received_time=NOW + timedelta(milliseconds=20),
    )
    assert sample.round_trip_ms == Decimal("20.0")
    assert sample.offset_ms == Decimal("5.0")

    rows = lead_lag_dataset(
        (
            observation("okx_public", Venue.OKX, seconds=0),
            observation("bybit_public", Venue.BYBIT, seconds=2),
            observation("deribit_public", Venue.DERIBIT, seconds=3),
        )
    )
    assert [row.lag_ms for row in rows] == [Decimal("2000.0"), Decimal("3000.0")]
    assert all(row.leader_provider_id == ProviderId("okx_public") for row in rows)


def test_venue_ticker_funding_and_open_interest_normalize_to_comparable_rows(
    exchange_fixtures: dict[str, object],
) -> None:
    okx_instrument = normalize_okx_instruments(
        cast(dict[str, object], exchange_fixtures["okx"]),
        observed_time=NOW,
        available_time=NOW,
    )[0]
    bybit_instrument = normalize_bybit_instruments(
        cast(dict[str, object], exchange_fixtures["bybit_linear"]),
        observed_time=NOW,
        available_time=NOW,
    )[0]
    deribit_instrument = normalize_deribit_instruments(
        cast(dict[str, object], exchange_fixtures["deribit"]),
        observed_time=NOW,
        available_time=NOW,
    )[0]
    rows = (
        normalize_market_observation(
            Venue.OKX,
            instrument=okx_instrument,
            ticker_payload={
                "data": [
                    {
                        "bidPx": "99990",
                        "askPx": "100010",
                        "last": "100000",
                        "bidSz": "2",
                        "askSz": "3",
                    }
                ]
            },
            funding_payload={"data": [{"fundingRate": "0.0001"}]},
            open_interest_payload={"data": [{"oiCcy": "100"}]},
            event_time=NOW,
            available_time=NOW,
            ingest_time=NOW,
            quality_score=Decimal("0.99"),
        ),
        normalize_market_observation(
            Venue.BYBIT,
            instrument=bybit_instrument,
            ticker_payload={
                "result": {
                    "list": [
                        {
                            "bid1Price": "99991",
                            "ask1Price": "100011",
                            "markPrice": "100001",
                            "indexPrice": "100000",
                            "bid1Size": "2",
                            "ask1Size": "3",
                            "fundingRate": "0.0002",
                            "openInterest": "200",
                        }
                    ]
                }
            },
            event_time=NOW,
            available_time=NOW,
            ingest_time=NOW,
            quality_score=Decimal("0.98"),
        ),
        normalize_market_observation(
            Venue.DERIBIT,
            instrument=deribit_instrument,
            ticker_payload={
                "result": {
                    "best_bid_price": 99992,
                    "best_ask_price": 100012,
                    "mark_price": 100002,
                    "index_price": 100000,
                    "best_bid_amount": 20,
                    "best_ask_amount": 30,
                    "current_funding": 0.0003,
                    "open_interest": 300,
                }
            },
            event_time=NOW,
            available_time=NOW,
            ingest_time=NOW,
            quality_score=Decimal("0.97"),
        ),
    )
    assert rows[0].funding_rate == Decimal("0.0001")
    assert rows[1].open_interest == Decimal("200")
    assert rows[2].liquidity_notional == Decimal("5000200")
    assert {row.venue for row in rows} == {Venue.OKX, Venue.BYBIT, Venue.DERIBIT}
