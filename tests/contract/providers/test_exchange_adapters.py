from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest

from aegisquant.data.market import ContractForm, InstrumentType, Venue
from aegisquant.data.providers.public import (
    EXCHANGE_CONTRACTS,
    PublicExchangeAdapter,
    build_orderbook_subscription,
    build_public_request,
    load_changelog_snapshot,
    normalize_bybit_instruments,
    normalize_deribit_instruments,
    normalize_okx_instruments,
    snapshot_changelog,
    write_changelog_snapshot,
)

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def test_public_request_allowlists_and_private_parameter_denial() -> None:
    requests = (
        build_public_request(Venue.OKX, "instruments", {"instType": "SWAP"}),
        build_public_request(Venue.BYBIT, "instruments", {"category": "linear", "limit": 1000}),
        build_public_request(Venue.DERIBIT, "instruments", {"currency": "BTC", "kind": "future"}),
    )
    assert {request.venue for request in requests} == {Venue.OKX, Venue.BYBIT, Venue.DERIBIT}
    assert all(request.authentication_used is False for request in requests)
    assert all(request.url.startswith("https://") for request in requests)
    with pytest.raises(ValueError, match="PRIVATE-PARAMETER"):
        build_public_request(Venue.OKX, "instruments", {"instType": "SWAP", "api_key": "x"})
    with pytest.raises(ValueError, match="CAPABILITY-NOT-ALLOWLISTED"):
        build_public_request(Venue.BYBIT, "order/create", {})


def test_public_orderbook_subscriptions_preserve_venue_channels() -> None:
    okx = build_orderbook_subscription(Venue.OKX, "BTC-USDT-SWAP")
    bybit = build_orderbook_subscription(Venue.BYBIT, "BTCUSDT", product="linear", depth=50)
    deribit = build_orderbook_subscription(Venue.DERIBIT, "BTC-PERPETUAL")
    assert okx.channel == "books"
    assert bybit.channel == "orderbook.50.BTCUSDT"
    assert deribit.channel == "book.BTC-PERPETUAL.raw"
    assert all(item.authentication_used is False for item in (okx, bybit, deribit))
    assert all(item.snapshot_required for item in (okx, bybit, deribit))


def test_exchange_instrument_normalizers_share_exposure_only_when_dimensions_match(
    exchange_fixtures: dict[str, object],
) -> None:
    okx = normalize_okx_instruments(
        cast(dict[str, object], exchange_fixtures["okx"]), observed_time=NOW, available_time=NOW
    )
    bybit = normalize_bybit_instruments(
        cast(dict[str, object], exchange_fixtures["bybit_linear"]),
        observed_time=NOW,
        available_time=NOW,
    )
    deribit = normalize_deribit_instruments(
        cast(dict[str, object], exchange_fixtures["deribit"]),
        observed_time=NOW,
        available_time=NOW,
    )
    assert okx[0].exposure.exposure_id == bybit[0].exposure.exposure_id
    assert okx[0].instrument_id != bybit[0].instrument_id
    assert deribit[0].exposure.contract_form is ContractForm.INVERSE
    assert deribit[0].exposure.instrument_type is InstrumentType.PERPETUAL
    assert okx[1].exposure.exposure_id == deribit[1].exposure.exposure_id
    assert okx[1].instrument_id != deribit[1].instrument_id


def test_options_retain_expiry_strike_type_and_iv_source(
    exchange_fixtures: dict[str, object],
) -> None:
    normalizers = (
        normalize_okx_instruments(
            cast(dict[str, object], exchange_fixtures["okx"]),
            observed_time=NOW,
            available_time=NOW,
        )[1],
        normalize_bybit_instruments(
            cast(dict[str, object], exchange_fixtures["bybit_option"]),
            observed_time=NOW,
            available_time=NOW,
        )[0],
        normalize_deribit_instruments(
            cast(dict[str, object], exchange_fixtures["deribit"]),
            observed_time=NOW,
            available_time=NOW,
        )[1],
    )
    for instrument in normalizers:
        assert instrument.exposure.instrument_type is InstrumentType.OPTION
        assert instrument.exposure.expiry is not None
        assert instrument.exposure.strike is not None
        assert instrument.exposure.option_type is not None
        assert instrument.iv_source.value == "VENUE_MARK_TICKER"


def test_real_adapter_uses_injected_unsigned_http_transport(
    exchange_fixtures: dict[str, object],
) -> None:
    raw = json.dumps(exchange_fixtures["okx"]).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v5/public/instruments"
        assert request.headers.get("authorization") is None
        return httpx.Response(200, content=raw, headers={"content-type": "application/json"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = PublicExchangeAdapter(Venue.OKX, client)
        instruments = adapter.fetch_instruments(
            {"instType": "SWAP"}, observed_time=NOW, available_time=NOW
        )
    assert len(instruments) == 2


def test_public_adapter_rejects_credentialled_injected_client_before_network() -> None:
    def fail_if_called(_: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be called")

    with httpx.Client(
        headers={"Authorization": "x"}, transport=httpx.MockTransport(fail_if_called)
    ) as client:
        adapter = PublicExchangeAdapter(Venue.OKX, client)
        with pytest.raises(ValueError, match="CREDENTIALLED-CLIENT-DENIED"):
            adapter.fetch_json("instruments", {"instType": "SWAP"})


def test_status_changelog_and_rate_limit_contracts_are_explicit(tmp_path: Path) -> None:
    for venue in (Venue.OKX, Venue.BYBIT, Venue.DERIBIT):
        contract = EXCHANGE_CONTRACTS[venue]
        assert contract.status_url.startswith("https://")
        assert contract.changelog_url.startswith("https://")
        assert contract.rate_limits and all(value > 0 for value in contract.rate_limits.values())
        first = snapshot_changelog(venue, b"v1", checked_at=NOW)
        second = snapshot_changelog(
            venue, b"v2", checked_at=NOW, previous_sha256=first.content_sha256
        )
        assert first.changed is False
        assert second.changed is True
        path = tmp_path / f"{venue.value}.json"
        write_changelog_snapshot(path, second)
        assert load_changelog_snapshot(path) == second
