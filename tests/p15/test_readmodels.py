"""P15 workbench projections remain deterministic, sourced, and non-live."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from aegisquant.data.hashing import sha256_file
from aegisquant.readmodels.models import (
    MarketStatePayload,
    OrderTracePayload,
    ProjectionKind,
    RiskLimitPayload,
)
from aegisquant.readmodels.p15_bootstrap import (
    build_p15_projection_events,
    build_p15_snapshot,
)


def test_p15_snapshot_is_deterministic_and_covers_workbench_domains(project_root: Path) -> None:
    first = build_p15_snapshot(project_root)
    second = build_p15_snapshot(project_root)
    required = {
        ProjectionKind.PNL_ATTRIBUTION,
        ProjectionKind.RISK_LIMITS,
        ProjectionKind.MODEL_METRICS,
        ProjectionKind.SIGNALS,
        ProjectionKind.FILLS,
        ProjectionKind.EXECUTION_QUALITY,
        ProjectionKind.MARKET_STATE,
        ProjectionKind.RESEARCH_RUNS,
        ProjectionKind.INCIDENTS,
        ProjectionKind.SYSTEM_HEALTH,
        ProjectionKind.RECONCILIATION_STATUS,
        ProjectionKind.ORDER_TRACES,
    }
    assert first == second
    assert required <= {record.projection for record in first.records}
    assert {record.projection for record in first.records} == set(ProjectionKind)
    assert first.source_event_count == len(build_p15_projection_events(project_root))
    assert len(first.records) > 40


def test_p15_records_retain_source_hashes_and_safety_truth(project_root: Path) -> None:
    snapshot = build_p15_snapshot(project_root)
    for record in snapshot.records:
        assert record.source_sha256 == sha256_file(project_root / record.source_artifact)
        assert record.as_of_time <= record.projected_at

    market = [
        record for record in snapshot.records if record.projection is ProjectionKind.MARKET_STATE
    ]
    assert market and all(record.payload["recommendation_provided"] is False for record in market)
    traces = [
        record for record in snapshot.records if record.projection is ProjectionKind.ORDER_TRACES
    ]
    assert traces and all(record.payload["complete"] is True for record in traces)
    assert all(record.payload["causal_link_overclaimed"] is False for record in traces)
    for trace in traces:
        stages = cast("list[dict[str, object]]", trace.payload["stages"])
        assert [item["stage"] for item in stages] == [
            "SIGNAL",
            "EVENT_EVIDENCE",
            "MODEL",
            "RISK",
            "ORDER",
            "FILL",
            "LEDGER",
        ]


def test_p15_payloads_reject_live_edits_recommendations_and_causal_overclaims(
    project_root: Path,
) -> None:
    snapshot = build_p15_snapshot(project_root)
    risk_limit = next(
        record for record in snapshot.records if record.projection is ProjectionKind.RISK_LIMITS
    )
    market = next(
        record for record in snapshot.records if record.projection is ProjectionKind.MARKET_STATE
    )
    trace = next(
        record for record in snapshot.records if record.projection is ProjectionKind.ORDER_TRACES
    )

    with pytest.raises(ValidationError, match="live_editable"):
        RiskLimitPayload.model_validate_json(
            json.dumps({**risk_limit.payload, "live_editable": True})
        )
    with pytest.raises(ValidationError, match="recommendation_provided"):
        MarketStatePayload.model_validate_json(
            json.dumps({**market.payload, "recommendation_provided": True})
        )
    with pytest.raises(ValidationError, match="causal_link_overclaimed"):
        OrderTracePayload.model_validate_json(
            json.dumps({**trace.payload, "causal_link_overclaimed": True})
        )
    with pytest.raises(ValidationError, match="completeness"):
        OrderTracePayload.model_validate_json(json.dumps({**trace.payload, "complete": False}))
