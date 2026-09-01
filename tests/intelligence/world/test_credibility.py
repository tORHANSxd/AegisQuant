from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from aegisquant.intelligence.world.events import summarize_independent_evidence
from aegisquant.intelligence.world.models import SourceCredibilityProfile

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _profile(
    identity: str,
    family: str,
    *,
    officiality: Decimal,
    manipulation: Decimal,
) -> SourceCredibilityProfile:
    return SourceCredibilityProfile(
        source_identity_id=identity,
        source_family_id=family,
        domain_accuracy=Decimal("0.8"),
        correction_quality=Decimal("0.7"),
        officiality=officiality,
        manipulation_risk=manipulation,
        identity_confidence=Decimal("0.9"),
        as_of_time=NOW,
        evidence_count=10,
    )


def test_credibility_separates_officiality_manipulation_and_independence() -> None:
    official = _profile("official", "family-a", officiality=Decimal("1"), manipulation=Decimal("0"))
    repost = _profile("repost", "family-a", officiality=Decimal("0"), manipulation=Decimal("0.8"))
    independent = _profile(
        "independent", "family-b", officiality=Decimal("0.2"), manipulation=Decimal("0.1")
    )
    result = summarize_independent_evidence((official, repost, independent))
    assert official.score > repost.score
    assert result.profile_count == 3
    assert result.independent_family_count == 2
    assert result.official_family_count == 1
