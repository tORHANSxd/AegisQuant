from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.domain.intelligence import EventClusterStatus
from aegisquant.intelligence.world.models import RuntimeSourceState, WorldSource
from aegisquant.intelligence.world.replay import (
    EventRadarRow,
    EventReplayRow,
    EvidenceGraphRow,
    NarrativeMonitorRow,
    SourceDisposition,
    SourceMonitorRow,
    WorldIntelligenceReadModels,
)

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _read_models() -> WorldIntelligenceReadModels:
    return WorldIntelligenceReadModels(
        event_radar=(
            EventRadarRow(
                event_cluster_id="event-1",
                status=EventClusterStatus.CORROBORATED,
                impact_score=Decimal("0.2"),
                confidence=Decimal("0.7"),
                independent_family_count=2,
                evidence_ids=("evidence-1", "evidence-2"),
                as_of_time=NOW,
            ),
        ),
        evidence_graph=(
            EvidenceGraphRow(
                event_cluster_id="event-1",
                claim_id="claim-1",
                evidence_id="evidence-1",
                relation="SUPPORTS",
                source_family_id="family-1",
                policy_id="policy-v1",
                model_version="extractor-v1",
                available_at=NOW,
            ),
        ),
        narrative_monitor=(
            NarrativeMonitorRow(
                narrative_id="narrative-1",
                topic="ETF",
                propagation_stage="CROSS_PLATFORM",
                independent_author_count=2,
                coordination_risk=Decimal("0.1"),
                as_of_time=NOW,
            ),
        ),
        source_monitor=(
            SourceMonitorRow(
                source=WorldSource.BLUESKY,
                runtime_state=RuntimeSourceState.READY,
                disposition=SourceDisposition.RETAIN,
                last_success_at=NOW,
                gap_count=0,
                reason_codes=("POSITIVE_EVENT_INCREMENT",),
            ),
        ),
        event_replay=(
            EventReplayRow(
                content_id="content-1",
                as_of_time=NOW,
                selected_revision=2,
                selected_engagement_snapshot_id="engagement-1",
                deleted_as_of=False,
                excluded_future_items=1,
            ),
        ),
        generated_as_of=NOW,
    )


def test_five_read_models_are_typed_and_point_in_time() -> None:
    models = _read_models()
    assert len(models.event_radar) == 1
    assert len(models.evidence_graph) == 1
    assert len(models.narrative_monitor) == 1
    assert len(models.source_monitor) == 1
    assert len(models.event_replay) == 1


def test_read_model_rejects_future_rows() -> None:
    payload = _read_models().model_dump()
    payload["event_replay"][0]["as_of_time"] = NOW + timedelta(seconds=1)
    with pytest.raises(ValidationError, match="future row"):
        WorldIntelligenceReadModels.model_validate(payload)
