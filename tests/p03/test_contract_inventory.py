"""Official contract inventory and fail-closed adapter registration tests."""

# pyright: reportUnknownMemberType=false

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from aegisquant.data.providers.binance.contracts import (
    REST_CONTRACTS,
    Product,
    RestEndpoint,
    StreamKind,
    assert_public_archive_url,
    assert_public_url,
    build_rest_request,
    build_ws_url,
)
from aegisquant.domain.policy import RawStorageMode
from tests.p03.helpers import registries


def test_machine_inventory_matches_code_and_contains_no_auth(project_root: Path) -> None:
    inventory = yaml.safe_load(
        (project_root / "data/contracts/binance_public_contracts.yaml").read_text(encoding="utf-8")
    )
    assert inventory["authentication"] == "none"
    assert set(inventory["forbidden_capabilities"]) >= {
        "account",
        "orders",
        "user_data_stream",
        "private_websocket",
        "signed_request",
    }
    names = {row["name"] for row in inventory["rest_endpoints"]}
    assert names == {endpoint.value for endpoint in REST_CONTRACTS}
    assert inventory["websocket_hosts"]["usdm_public"].endswith("/public")
    assert inventory["websocket_hosts"]["usdm_market"].endswith("/market")


def test_public_url_builders_are_allowlisted_and_reject_private_material() -> None:
    url, parameters, request_hash = build_rest_request(
        RestEndpoint.SPOT_KLINES,
        {"symbol": "BTCUSDT", "interval": "1m", "limit": 1000},
    )
    assert url == "https://data-api.binance.vision/api/v3/klines"
    assert parameters["symbol"] == "BTCUSDT"
    assert len(request_hash) == 64
    with pytest.raises(ValueError, match="PRIVATE-PARAMETER"):
        build_rest_request(RestEndpoint.SPOT_TIME, {"signature": "forbidden"})
    with pytest.raises(ValueError, match="PARAMETERS"):
        build_rest_request(RestEndpoint.USDM_OPEN_INTEREST, {})
    with pytest.raises(ValueError, match="maximum"):
        build_rest_request(
            RestEndpoint.USDM_KLINES,
            {"symbol": "BTCUSDT", "interval": "1m", "limit": 1501},
        )
    assert (
        build_ws_url(product=Product.SPOT, kind=StreamKind.DEPTH, symbol="BTCUSDT")
        == "wss://data-stream.binance.vision/ws/btcusdt@depth@1000ms"
    )
    assert "/public/ws/" in build_ws_url(
        product=Product.USD_M, kind=StreamKind.DEPTH, symbol="BTCUSDT"
    )
    assert "/market/ws/" in build_ws_url(
        product=Product.USD_M, kind=StreamKind.AGG_TRADE, symbol="BTCUSDT"
    )
    with pytest.raises(ValueError, match="PRIVATE-ROUTE"):
        assert_public_url("wss://fstream.binance.com/private/ws/user", websocket=True)
    with pytest.raises(ValueError, match="ARCHIVE-DENIED"):
        assert_public_archive_url("https://data.binance.vision/not-data/public.zip")


def test_registry_schema_allows_one_public_adapter_but_no_trading_adapter(
    project_root: Path,
) -> None:
    registry = json.loads(
        (project_root / "configs/exchanges/adapter_registry.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (project_root / "schemas/exchange_adapter_registry.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(registry)
    assert registry["live_trading_locked"] is True
    assert registry["order_submission_enabled"] is False
    assert (
        registry["paper_adapters"]
        == registry["testnet_adapters"]
        == registry["live_adapters"]
        == []
    )
    public = registry["public_market_data_adapters"][0]
    assert public["credentials_required"] is False
    assert public["private_api_enabled"] is False
    assert public["order_submission_enabled"] is False


def test_binance_provider_and_public_archive_policy_are_approved(project_root: Path) -> None:
    providers, _, policy = registries(project_root)
    entry = providers.require_collection(policy.provider_id, policy)
    providers.require_archive(policy.provider_id, policy)
    assert entry.credentials_required is False
    assert policy.raw_storage is RawStorageMode.PUBLIC_APPEND_ONLY
    assert policy.cloud_inference.value == "PROHIBITED"
    assert policy.redistribution.value == "PROHIBITED"
