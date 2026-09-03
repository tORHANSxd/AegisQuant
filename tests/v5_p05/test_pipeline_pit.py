from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from aegisquant.domain.identifiers import ProviderId
from aegisquant.domain.intelligence import ContentType, EventClusterStatus
from aegisquant.intelligence.collectors import CollectedContent, SourceKind
from aegisquant.intelligence.pipeline import point_in_time_contents, run_pipeline

BASE = datetime(2026, 9, 2, 8, tzinfo=UTC)


def content(
    *,
    native_id: str,
    text: str,
    observed_after: int,
    verified: bool,
    revision: int = 1,
    published_after: int = 0,
    modified_after: int | None = None,
    deleted_after: int | None = None,
) -> CollectedContent:
    return CollectedContent(
        source=SourceKind.GITHUB,
        provider_id=ProviderId("github_public"),
        native_id=native_id,
        source_native_id="official/project",
        display_name="official/project",
        ownership_group="official/project",
        independence_group="official/project",
        verified_source=verified,
        content_type=ContentType.ANNOUNCEMENT,
        canonical_url=f"https://github.com/official/project/releases/{native_id}",
        text=text,
        language="en",
        published_time=BASE + timedelta(seconds=published_after),
        observed_time=BASE + timedelta(seconds=observed_after),
        modified_time=(
            BASE + timedelta(seconds=modified_after) if modified_after is not None else None
        ),
        deleted_time=(
            BASE + timedelta(seconds=deleted_after) if deleted_after is not None else None
        ),
        revision=revision,
        checkpoint=f"{native_id}:{revision}",
    )


def test_future_official_content_cannot_confirm_past_rumor() -> None:
    rumor = content(
        native_id="rumor",
        text="Unconfirmed rumor: Bitcoin protocol release",
        observed_after=1,
        verified=True,
    )
    future_confirmation = content(
        native_id="confirmation",
        text="Bitcoin protocol release approved",
        observed_after=20,
        verified=True,
    )
    before = run_pipeline((rumor, future_confirmation), as_of_time=BASE + timedelta(seconds=10))
    assert len(before.claims) == 1
    assert before.event_clusters[0].status is EventClusterStatus.RUMOR
    assert before.event_clusters[0].official_confirmation_ids == ()
    assert before.event_clusters[0].first_observed_time == rumor.observed_time
    assert before.event_clusters[0].last_updated_time == rumor.observed_time

    after = run_pipeline((rumor, future_confirmation), as_of_time=BASE + timedelta(seconds=30))
    assert len(after.claims) == 2
    assert after.event_clusters[0].status is EventClusterStatus.CONFIRMED
    assert after.event_clusters[0].first_observed_time == rumor.observed_time
    assert after.event_clusters[0].last_updated_time == future_confirmation.observed_time


def test_pipeline_selects_latest_revision_visible_at_decision_time() -> None:
    first = content(
        native_id="same",
        text="Unconfirmed rumor: Bitcoin protocol release",
        observed_after=1,
        verified=False,
        revision=1,
    )
    corrected = content(
        native_id="same",
        text="Bitcoin protocol release approved",
        observed_after=20,
        verified=True,
        revision=2,
    )
    assert point_in_time_contents((corrected, first), as_of_time=BASE + timedelta(seconds=10)) == (
        first,
    )
    assert point_in_time_contents((corrected, first), as_of_time=BASE + timedelta(seconds=30)) == (
        corrected,
    )


def test_duplicate_or_time_regressing_revisions_fail_closed() -> None:
    first = content(
        native_id="same",
        text="Bitcoin protocol release",
        observed_after=10,
        verified=False,
        revision=1,
    )
    duplicate = content(
        native_id="same",
        text="Bitcoin protocol release corrected",
        observed_after=11,
        verified=False,
        revision=1,
    )
    with pytest.raises(ValueError, match="AQ-INTELLIGENCE-DUPLICATE-CONTENT-REVISION"):
        point_in_time_contents((first, duplicate), as_of_time=BASE + timedelta(seconds=30))

    regressing = content(
        native_id="same",
        text="Bitcoin protocol release corrected",
        observed_after=9,
        verified=False,
        revision=2,
    )
    with pytest.raises(ValueError, match="AQ-INTELLIGENCE-CONTENT-REVISION-TIME-REGRESSION"):
        point_in_time_contents((first, regressing), as_of_time=BASE + timedelta(seconds=30))


def test_collected_content_rejects_future_modification_knowledge() -> None:
    payload = content(
        native_id="invalid",
        text="Bitcoin protocol release",
        observed_after=10,
        verified=True,
    ).model_dump_json()
    payload = json.loads(payload)
    payload["modified_time"] = (BASE + timedelta(seconds=11)).isoformat()
    with pytest.raises(ValidationError, match="cannot be known before observation"):
        CollectedContent.model_validate_json(json.dumps(payload))


def test_revision_history_rejects_publication_and_lifecycle_regressions() -> None:
    first = content(
        native_id="same",
        text="Bitcoin protocol release",
        observed_after=10,
        verified=False,
        revision=1,
        modified_after=5,
    )
    changed_publication = content(
        native_id="same",
        text="Bitcoin protocol release corrected",
        observed_after=20,
        verified=False,
        revision=2,
        published_after=1,
        modified_after=15,
    )
    with pytest.raises(ValueError, match="AQ-INTELLIGENCE-CONTENT-PUBLICATION-TIME-CHANGED"):
        point_in_time_contents(
            (first, changed_publication), as_of_time=BASE + timedelta(seconds=30)
        )

    cleared_modification = content(
        native_id="same",
        text="Bitcoin protocol release corrected",
        observed_after=20,
        verified=False,
        revision=2,
    )
    with pytest.raises(
        ValueError,
        match="AQ-INTELLIGENCE-CONTENT-MODIFICATION-STATE-REGRESSION",
    ):
        point_in_time_contents(
            (first, cleared_modification), as_of_time=BASE + timedelta(seconds=30)
        )

    deleted = content(
        native_id="deleted",
        text="[deleted]",
        observed_after=10,
        verified=False,
        revision=1,
        deleted_after=9,
    )
    silently_restored = content(
        native_id="deleted",
        text="Bitcoin protocol release",
        observed_after=20,
        verified=False,
        revision=2,
    )
    with pytest.raises(ValueError, match="AQ-INTELLIGENCE-CONTENT-DELETION-STATE-REGRESSION"):
        point_in_time_contents(
            (deleted, silently_restored), as_of_time=BASE + timedelta(seconds=30)
        )


def test_first_locally_observed_provider_revision_may_be_sparse() -> None:
    first_seen = content(
        native_id="sparse",
        text="Bitcoin protocol release corrected before local collection began",
        observed_after=20,
        verified=False,
        revision=7,
        modified_after=15,
    )
    assert point_in_time_contents(
        (first_seen,),
        as_of_time=BASE + timedelta(seconds=30),
    ) == (first_seen,)
