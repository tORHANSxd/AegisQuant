"""News metrics, official-fact authority, and free-baseline degradation tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aegisquant.research.provider_bakeoff.evaluation import (
    calculate_news_metrics,
    fallback_to_free_baseline,
    require_official_trading_fact,
)
from aegisquant.research.provider_bakeoff.models import (
    DegradationMode,
    NewsDetection,
    NewsReferenceEvent,
    SourceAuthority,
    TradingFactRecord,
)


def test_news_metrics_use_official_events_and_count_false_alerts_and_duplicates() -> None:
    start = datetime(2026, 9, 2, tzinfo=UTC)
    references = tuple(
        NewsReferenceEvent(
            event_id=f"event-{index}",
            official_available_time=start + timedelta(minutes=index * 10),
            risk_relevant=index in {1, 3},
        )
        for index in range(1, 5)
    )
    detections = (
        NewsDetection(
            detection_id="d1",
            matched_official_event_id="event-1",
            available_time=references[0].official_available_time - timedelta(seconds=60),
            story_fingerprint="story-a",
        ),
        NewsDetection(
            detection_id="d2",
            matched_official_event_id="event-2",
            available_time=references[1].official_available_time + timedelta(seconds=30),
            story_fingerprint="story-b",
        ),
        NewsDetection(
            detection_id="d3",
            matched_official_event_id="event-2",
            available_time=references[1].official_available_time + timedelta(seconds=45),
            story_fingerprint="story-b",
        ),
        NewsDetection(
            detection_id="d4",
            matched_official_event_id=None,
            available_time=start,
            story_fingerprint="story-c",
        ),
    )
    metrics = calculate_news_metrics(references=references, detections=detections)
    assert metrics.matched_event_count == 2
    assert metrics.recall == Decimal("0.5")
    assert metrics.false_alert_rate == Decimal("0.25")
    assert metrics.duplicate_rate == Decimal("0.25")
    assert metrics.mean_lead_time_seconds == Decimal("15")
    assert metrics.risk_coverage_rate == Decimal("0.5")


def test_provider_outage_returns_exact_free_baseline_without_hard_dependency() -> None:
    result = fallback_to_free_baseline(
        baseline_record_ids=("official-1", "official-2"),
        candidate_record_ids=("paid-1",),
        candidate_approved=True,
        provider_available=False,
    )
    assert result.mode is DegradationMode.BASELINE_ONLY
    assert result.selected_record_ids == ("official-1", "official-2")
    assert result.baseline_preserved is True
    assert result.candidate_records_used is False
    assert result.runtime_hard_dependency is False


def test_third_party_aggregator_cannot_become_trading_fact_authority() -> None:
    aggregated = TradingFactRecord(
        fact_id="fact-aggregated",
        fact_type="fill",
        source_authority=SourceAuthority.THIRD_PARTY_AGGREGATOR,
        source_id="paid-provider",
    )
    official = TradingFactRecord(
        fact_id="fact-official",
        fact_type="fill",
        source_authority=SourceAuthority.OFFICIAL_EXCHANGE,
        source_id="binance_public",
    )
    with pytest.raises(PermissionError, match="THIRD-PARTY-NOT-TRADING-FACT-AUTHORITY"):
        require_official_trading_fact(aggregated)
    assert require_official_trading_fact(official) == official
