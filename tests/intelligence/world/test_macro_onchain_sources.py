from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from aegisquant.data.hashing import canonical_sha256
from aegisquant.intelligence.world.models import RuntimeSourceState, WorldSource
from aegisquant.intelligence.world.sources import (
    build_world_request,
    manifest_dune_result,
    parse_alfred_observations,
    parse_coin_metrics,
    parse_defillama_chain_tvl,
    register_dune_query,
    select_alfred_vintage,
)

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def test_alfred_replays_the_latest_available_vintage_without_future_revision() -> None:
    payload = {
        "observations": [
            {
                "realtime_start": "2026-08-01",
                "realtime_end": "2026-08-31",
                "date": "2026-06-01",
                "value": "100.0",
            },
            {
                "realtime_start": "2026-09-01",
                "realtime_end": "9999-12-31",
                "date": "2026-06-01",
                "value": "101.5",
            },
        ]
    }
    availability = {
        date(2026, 8, 1): datetime(2026, 8, 1, 16, tzinfo=UTC),
        date(2026, 9, 1): NOW,
    }
    observations = parse_alfred_observations(
        payload, series_id="GDP", vintage_available_at=availability
    )
    before_revision = select_alfred_vintage(
        observations, as_of_time=datetime(2026, 8, 15, tzinfo=UTC)
    )
    after_revision = select_alfred_vintage(observations, as_of_time=NOW)
    assert before_revision[0].value == Decimal("100.0")
    assert after_revision[0].value == Decimal("101.5")
    assert before_revision[0].source_hash != after_revision[0].source_hash


def test_alfred_requires_observed_availability_for_every_vintage() -> None:
    payload = {
        "observations": [
            {
                "realtime_start": "2026-09-01",
                "realtime_end": "9999-12-31",
                "date": "2026-06-01",
                "value": ".",
            }
        ]
    }
    with pytest.raises(ValueError, match="AVAILABLE-TIME-REQUIRED"):
        parse_alfred_observations(payload, series_id="GDP", vintage_available_at={})


def test_public_and_credentialed_source_requests_are_explicit() -> None:
    fred = build_world_request(
        WorldSource.FRED_ALFRED,
        "series_observations",
        {"series_id": "GDP", "file_type": "json", "output_type": 2},
    )
    coin_metrics = build_world_request(
        WorldSource.COIN_METRICS,
        "asset_metrics",
        {"assets": "btc", "metrics": "CapMrktCurUSD"},
    )
    assert fred.runtime_state is RuntimeSourceState.AWAITING_CREDENTIALS
    assert fred.executable is False
    assert coin_metrics.runtime_state is RuntimeSourceState.READY
    assert coin_metrics.base_url == "https://community-api.coinmetrics.io"
    with pytest.raises(ValueError, match="PLAINTEXT-CREDENTIAL-DENIED"):
        build_world_request(
            WorldSource.FRED_ALFRED,
            "series_observations",
            {"series_id": "GDP", "file_type": "json", "api_key": "denied"},
        )


def test_coin_metrics_and_defillama_keep_available_time_and_quality() -> None:
    coin = parse_coin_metrics(
        {
            "data": [
                {
                    "asset": "btc",
                    "time": "2026-09-01T11:00:00Z",
                    "status": "reviewed",
                    "CapMrktCurUSD": "123.45",
                }
            ]
        },
        metric_names=("CapMrktCurUSD",),
        available_at=NOW,
    )[0]
    llama = parse_defillama_chain_tvl(
        [{"date": 1788260400, "tvl": 42}], chain="Ethereum", available_at=NOW
    )[0]
    assert coin.quality_status == "reviewed" and coin.value == Decimal("123.45")
    assert llama.source is WorldSource.DEFILLAMA and llama.metric == "tvl_usd"


def test_dune_registry_rejects_writes_and_manifests_results() -> None:
    query = register_dune_query(
        query_id=42,
        version=1,
        name="daily stablecoin flow",
        sql="SELECT day, flow FROM stablecoin_flow WHERE chain = {{chain}}",
        parameter_names=("chain",),
        registered_at=NOW,
    )
    manifest = manifest_dune_result(
        query=query,
        parameters={"chain": "ethereum"},
        execution_id="exec-fixture-1",
        requested_at=NOW,
        available_at=NOW + timedelta(seconds=30),
        rows=({"day": "2026-08-31", "flow": "10"},),
    )
    assert query.sql_sha256 == canonical_sha256({"sql": query.sql})
    assert manifest.query_version == 1 and manifest.row_count == 1
    with pytest.raises(ValueError, match="read-only"):
        register_dune_query(
            query_id=43,
            version=1,
            name="denied write",
            sql="DELETE FROM stablecoin_flow",
            parameter_names=(),
            registered_at=NOW,
        )
    with pytest.raises(ValueError, match="denied SQL operation"):
        register_dune_query(
            query_id=44,
            version=1,
            name="denied CTE write",
            sql="WITH selected AS (SELECT 1) DELETE FROM stablecoin_flow",
            parameter_names=(),
            registered_at=NOW,
        )
    with pytest.raises(ValueError, match="exactly match"):
        manifest_dune_result(
            query=query,
            parameters={},
            execution_id="exec-fixture-2",
            requested_at=NOW,
            available_at=NOW + timedelta(seconds=1),
            rows=(),
        )
