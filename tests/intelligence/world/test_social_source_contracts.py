from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aegisquant.intelligence.world.models import RuntimeSourceState, WorldSource
from aegisquant.intelligence.world.sources import (
    WORLD_ENDPOINTS,
    DegradationMode,
    build_world_request,
    gdelt_discover_originals,
    plan_cursor_gap,
    plan_intelligence_degradation,
)

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def test_social_contracts_use_official_read_only_routes_and_degrade_without_credentials() -> None:
    x_request = build_world_request(WorldSource.X, "filtered_stream")
    youtube = build_world_request(WorldSource.YOUTUBE, "videos", {"part": "snippet"})
    github = build_world_request(
        WorldSource.GITHUB, "releases", {"owner": "example", "repo": "protocol"}
    )
    assert x_request.runtime_state is RuntimeSourceState.AWAITING_CREDENTIALS
    assert youtube.executable is False
    assert github.executable is True
    assert github.headers == {"X-GitHub-Api-Version": "2026-03-10"}


def test_bluesky_v2_is_canonical_and_v1_is_explicit_legacy() -> None:
    endpoints = WORLD_ENDPOINTS[WorldSource.BLUESKY]
    assert endpoints["jetstream_v2"].path_template.endswith("subscribeEvents")
    assert endpoints["jetstream_v2"].allowed_parameters >= {
        "kinds",
        "dids",
        "collections",
        "cursor",
    }
    assert endpoints["jetstream_v1_legacy"].api_version == "v1-legacy"


def test_gdelt_only_discovers_and_traces_original_source() -> None:
    discoveries = gdelt_discover_originals(
        {
            "articles": [
                {
                    "url": "https://www.sec.gov/news/example",
                    "title": "Official filing published",
                    "seendate": "20260901T110000Z",
                }
            ]
        },
        discovered_at=NOW,
    )
    assert discoveries[0].original_host == "www.sec.gov"
    assert discoveries[0].authoritative_evidence is False
    with pytest.raises(ValueError, match="original-source host"):
        gdelt_discover_originals(
            {
                "articles": [
                    {
                        "url": "https://api.gdeltproject.org/result",
                        "title": "Aggregator result",
                    }
                ]
            },
            discovered_at=NOW,
        )


def test_gap_planner_records_recoverable_and_permanent_gaps() -> None:
    recoverable = plan_cursor_gap(
        source=WorldSource.BLUESKY,
        expected_cursor=10,
        observed_cursor=15,
        detected_at=NOW,
        earliest_recoverable_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    permanent = plan_cursor_gap(
        source=WorldSource.X,
        expected_cursor=10,
        observed_cursor=15,
        detected_at=NOW,
        earliest_recoverable_at=None,
    )
    assert recoverable.action == "BACKFILL"
    assert permanent.action == "RECORD_PERMANENT_GAP"
    assert permanent.missing_count == 5


def test_unavailable_source_and_llm_degrade_without_permission_or_time_escalation() -> None:
    cached = plan_intelligence_degradation(
        source=WorldSource.X,
        source_state=RuntimeSourceState.AWAITING_CREDENTIALS,
        llm_available=False,
        cache_available_at=datetime(2026, 9, 1, 11, tzinfo=UTC),
        as_of_time=NOW,
    )
    unavailable = plan_intelligence_degradation(
        source=WorldSource.X,
        source_state=RuntimeSourceState.AWAITING_CREDENTIALS,
        llm_available=False,
        cache_available_at=None,
        as_of_time=NOW,
    )
    assert cached.mode is DegradationMode.LOCAL_RULES_ONLY
    assert cached.action == "RESEARCH_PROPOSAL_ONLY"
    assert "STALE_CACHE_DISCLOSED" in cached.reason_codes
    assert unavailable.mode is DegradationMode.ABSTAIN
    assert unavailable.can_emit_forecast is False
