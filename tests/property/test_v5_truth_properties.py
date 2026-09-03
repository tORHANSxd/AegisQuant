from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from aegisquant.domain.identifiers import ArtifactId, SourceDocumentId
from aegisquant.domain.truth import TemporalRevision
from aegisquant.intelligence.truth import select_revisions_as_of

BASE_TIME = datetime(2026, 9, 2, tzinfo=UTC)


def revision(number: int, available_after: int) -> TemporalRevision:
    instant = BASE_TIME + timedelta(seconds=available_after)
    return TemporalRevision(
        source_document_id=SourceDocumentId("property-document"),
        revision_id=ArtifactId(f"property-revision-{number}"),
        previous_revision_id=(
            ArtifactId(f"property-revision-{number - 1}") if number > 1 else None
        ),
        revision_number=number,
        content_hash=f"{number:x}" * 64,
        observed_at=instant,
        effective_at=instant,
        available_at=instant,
        updated_time=instant if number > 1 else None,
    )


@given(
    first_delay=st.integers(min_value=0, max_value=1000),
    gap=st.integers(min_value=1, max_value=1000),
    lead=st.integers(min_value=0, max_value=1000),
)
def test_pit_never_selects_revision_before_its_availability(
    first_delay: int, gap: int, lead: int
) -> None:
    first = revision(1, first_delay)
    second = revision(2, first_delay + gap)
    decision = BASE_TIME + timedelta(seconds=first_delay + min(lead, gap - 1))
    assert select_revisions_as_of((second, first), decision_time=decision) == (first,)


@given(order=st.permutations((1, 2, 3)))
def test_revision_selection_and_hash_are_input_order_independent(
    order: tuple[int, int, int],
) -> None:
    revisions = {number: revision(number, number) for number in (1, 2, 3)}
    selected = select_revisions_as_of(
        tuple(revisions[number] for number in order),
        decision_time=BASE_TIME + timedelta(seconds=3),
    )
    assert selected == (revisions[3],)
    assert revisions[3].content_sha256() == revisions[3].model_copy().content_sha256()
