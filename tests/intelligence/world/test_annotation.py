from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.intelligence.world.events import active_learning_queue
from aegisquant.intelligence.world.models import AnnotationLabel, HumanAnnotation, OntologyVersion

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def test_ontology_is_versioned_and_annotation_is_evidence_bound() -> None:
    ontology = OntologyVersion(
        ontology_id="crypto-events",
        version="1.0.0",
        event_types=("REGULATORY_ACTION", "SECURITY_INCIDENT"),
        relation_types=("SUPPORTS", "REFUTES"),
        published_at=NOW,
    )
    annotation = HumanAnnotation(
        annotation_id="annotation-1",
        target_id="claim-1",
        ontology_version=ontology.version,
        label=AnnotationLabel.CONFIRMED,
        annotator_id="reviewer-pseudonym-1",
        rationale="Two independent primary records agree.",
        evidence_ids=("evidence-1", "evidence-2"),
        created_at=NOW,
    )
    assert annotation.ontology_version == "1.0.0"
    with pytest.raises(ValidationError, match="unique"):
        OntologyVersion.model_validate(
            {
                **ontology.model_dump(),
                "event_types": ("DUPLICATE", "DUPLICATE"),
            }
        )


def test_active_learning_prioritizes_uncertain_impactful_allowed_items() -> None:
    queue = active_learning_queue(
        (
            ("high", Decimal("0.9"), Decimal("0.8"), Decimal("0.7"), True),
            ("low", Decimal("0.2"), Decimal("0.1"), Decimal("0.1"), True),
            ("denied", Decimal("1"), Decimal("1"), Decimal("1"), False),
        ),
        limit=3,
    )
    assert queue[0].target_id == "high"
    assert queue[-1].target_id == "denied"
    assert queue[-1].priority_score == 0
