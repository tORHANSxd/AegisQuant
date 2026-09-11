"""Evidence-tier contracts that keep development artifacts out of Alpha promotion."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Self

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel


class EvidenceTier(StrEnum):
    """Mutually exclusive evidence maturity levels from the v5 SSOT."""

    FIXTURE = "FIXTURE"
    SYNTHETIC = "SYNTHETIC"
    DEVELOPMENT = "DEVELOPMENT"
    OOS_DEVELOPMENT = "OOS_DEVELOPMENT"
    FINAL_HOLDOUT = "FINAL_HOLDOUT"
    PAPER_FORWARD = "PAPER_FORWARD"
    SHADOW_FORWARD = "SHADOW_FORWARD"
    TESTNET_FORWARD = "TESTNET_FORWARD"
    CANARY_LIVE = "CANARY_LIVE"
    LIVE = "LIVE"


NON_PROMOTABLE_TIERS = frozenset(
    {EvidenceTier.FIXTURE, EvidenceTier.SYNTHETIC, EvidenceTier.DEVELOPMENT}
)


def tier_can_support_alpha_promotion(tier: EvidenceTier) -> bool:
    """Return whether a tier may support promotion; all other gates still apply."""

    return tier not in NON_PROMOTABLE_TIERS


class EvidenceDisclosure(DomainModel):
    """Machine-readable disclosure attached to evidence-backed user views."""

    evidence_tier: EvidenceTier
    alpha_promotion_eligible: bool
    source_artifacts: tuple[str, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_disclosure(self) -> Self:
        if self.alpha_promotion_eligible and not tier_can_support_alpha_promotion(
            self.evidence_tier
        ):
            raise ValueError("AQ-EVIDENCE-TIER-NOT-PROMOTABLE")
        if len(set(self.source_artifacts)) != len(self.source_artifacts):
            raise ValueError("evidence source artifacts must be unique")
        for raw_path in self.source_artifacts:
            path = PurePosixPath(raw_path)
            if (
                path.is_absolute()
                or not path.parts
                or ".." in path.parts
                or ":" in path.parts[0]
                or "\\" in raw_path
            ):
                raise ValueError("AQ-EVIDENCE-UNSAFE-SOURCE-PATH")
        return self
