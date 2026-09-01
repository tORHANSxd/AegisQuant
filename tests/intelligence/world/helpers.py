from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

from aegisquant.data.hashing import canonical_sha256
from aegisquant.intelligence.committee import EvidenceClaim, ExpertFinding, ExpertRole
from aegisquant.intelligence.world.fusion import FusionFeature, TimedFusionFeature
from aegisquant.intelligence.world.models import ContentRevision

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def revision(
    *,
    content_id: str = "content-1",
    revision_number: int = 1,
    text: str | None = "Bitcoin protocol upgrade confirmed",
    available_at: datetime = NOW,
    deleted_at: datetime | None = None,
) -> ContentRevision:
    hash_input = text if text is not None else f"tombstone:{content_id}:{revision_number}"
    return ContentRevision(
        content_id=content_id,
        revision=revision_number,
        provider_id="fixture",
        source_family_id="family-1",
        canonical_url=f"https://example.test/{content_id}",
        original_language="en",
        published_at=datetime(2026, 9, 1, 10, tzinfo=UTC),
        observed_at=available_at,
        available_at=available_at,
        body_sha256=hashlib.sha256(hash_input.encode()).hexdigest(),
        original_text=text,
        modified_at=available_at if revision_number > 1 and deleted_at is None else None,
        deleted_at=deleted_at,
        supersedes_revision=revision_number - 1 if revision_number > 1 else None,
        policy_id="fixture-policy-v1",
    )


def committee_findings(
    evidence_id: str = "evidence-1", *, abstain_role: ExpertRole | None = None
) -> tuple[ExpertFinding, ...]:
    findings: list[ExpertFinding] = []
    for role in sorted((item for item in ExpertRole if item is not ExpertRole.ARBITER), key=str):
        reasons = ("INSUFFICIENT_CORROBORATION",) if role is abstain_role else ()
        findings.append(
            ExpertFinding(
                role=role,
                claims=(
                    EvidenceClaim(
                        claim_id=f"{role.value.casefold()}-claim",
                        text=f"{role.value} finding",
                        evidence_ids=(evidence_id,),
                        supports=True,
                    ),
                ),
                semantic_confidence=Decimal("0.8"),
                factual_confidence=Decimal("0.7"),
                impact_confidence=Decimal("0.6"),
                directional_score=Decimal("0.2"),
                conflicts=(),
                should_abstain=bool(reasons),
                abstain_reasons=reasons,
            )
        )
    return tuple(findings)


def fusion_features(
    asset_id: str, *, available_at: datetime = NOW
) -> tuple[TimedFusionFeature, ...]:
    values = {
        FusionFeature.PRICE_RETURN: Decimal("0.2"),
        FusionFeature.BOOK_IMBALANCE: Decimal("0.1"),
        FusionFeature.OPEN_INTEREST_DELTA: Decimal("0.05"),
        FusionFeature.FUNDING_RATE: Decimal("0.02"),
        FusionFeature.BASIS: Decimal("0.03"),
        FusionFeature.ONCHAIN_FLOW: Decimal("0.15"),
    }
    return tuple(
        TimedFusionFeature(
            asset_id=asset_id,
            feature=name,
            value=value,
            event_time=datetime(2026, 9, 1, 11, tzinfo=UTC),
            available_at=available_at,
            source_id="fixture",
            source_hash=canonical_sha256(
                {"asset_id": asset_id, "feature": name.value, "value": str(value)}
            ),
        )
        for name, value in values.items()
    )
