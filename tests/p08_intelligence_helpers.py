from __future__ import annotations

from decimal import Decimal

from aegisquant.intelligence.committee import (
    REQUIRED_EXPERTS,
    EvidenceClaim,
    ExpertFinding,
    ExpertRole,
)


def committee_findings() -> tuple[ExpertFinding, ...]:
    output: list[ExpertFinding] = []
    for index, role in enumerate(sorted(REQUIRED_EXPERTS, key=lambda item: item.value)):
        evidence_id = "evidence-1" if index % 2 == 0 else "evidence-2"
        directional = (
            Decimal("0.3")
            if role
            in {
                ExpertRole.MARKET,
                ExpertRole.ON_CHAIN,
                ExpertRole.IMPACT,
            }
            else Decimal("0")
        )
        output.append(
            ExpertFinding(
                role=role,
                claims=(
                    EvidenceClaim(
                        claim_id=f"claim-{role.value.casefold()}",
                        text=f"evidence-bound {role.value.casefold()} finding",
                        evidence_ids=(evidence_id,),
                        supports=True,
                    ),
                ),
                semantic_confidence=Decimal("0.8"),
                factual_confidence=Decimal("0.7"),
                impact_confidence=Decimal("0.6"),
                directional_score=directional,
                should_abstain=False,
                abstain_reasons=(),
            )
        )
    return tuple(output)
