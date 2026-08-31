"""P03 Binance adapter can expose public data but no credential or trading surface."""

import json
from pathlib import Path

import pytest

from aegisquant.data.archive import RevisionArchive
from aegisquant.data.providers.binance.adapter import BinancePublicAdapter
from aegisquant.data.providers.binance.contracts import (
    Product,
    RestEndpoint,
    StreamKind,
    assert_public_url,
)
from aegisquant.data.providers.binance.rest import BinancePublicRestClient
from tests.p03.helpers import registries


def test_registry_keeps_all_trading_surfaces_empty(project_root: Path) -> None:
    registry = json.loads(
        (project_root / "configs/exchanges/adapter_registry.json").read_text(encoding="utf-8")
    )
    assert registry["live_trading_locked"] is True
    assert registry["order_submission_enabled"] is False
    assert registry["paper_adapters"] == []
    assert registry["testnet_adapters"] == []
    assert registry["live_adapters"] == []
    public = registry["public_market_data_adapters"]
    assert len(public) == 1
    assert public[0]["credentials_required"] is False
    assert public[0]["private_api_enabled"] is False
    assert public[0]["order_submission_enabled"] is False


@pytest.mark.parametrize(
    "url",
    [
        "https://api.binance.com/api/v3/account",
        "https://fapi.binance.com/fapi/v1/order",
        "wss://fstream.binance.com/private/ws/user",
        "wss://fstream.binance.com/ws/listenKey",
    ],
)
def test_private_account_order_and_user_routes_are_denied(url: str) -> None:
    with pytest.raises(ValueError):
        assert_public_url(url, websocket=url.startswith("wss"))


def test_adapter_catalog_and_health_are_permanently_public_only(
    tmp_path: Path, project_root: Path
) -> None:
    providers, _, policy = registries(project_root)
    with BinancePublicRestClient() as rest:
        adapter = BinancePublicAdapter(
            registry=providers,
            policy=policy,
            rest=rest,
            archive=RevisionArchive(tmp_path / "archive", providers),
        )
        catalog = adapter.discover_catalog()
        health = adapter.health()
    assert {row.product for row in catalog} == {Product.SPOT, Product.USD_M}
    assert health.live_trading_locked is True
    assert health.order_submission_enabled is False
    assert health.private_api_enabled is False
    assert not hasattr(adapter, "submit_order")
    assert not hasattr(adapter, "account")
    assert RestEndpoint.SPOT_TIME.value in {endpoint.value for endpoint in RestEndpoint}
    assert StreamKind.DEPTH.value == "depth"
