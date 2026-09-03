from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.research.causal import EventResponseDataset, EventResponseRow
from tests.v5_p05.test_canonical_events import canonical
from tests.v5_p06.helpers import response_dataset, response_row

CANONICAL_BOUND_FIELDS = {
    "event_id",
    "event_revision_id",
    "canonical_event_sha256",
    "event_type",
    "event_available_at",
    "truth_probability_at_t",
    "source_quality_at_t",
    "novelty_at_t",
    "market_reflection_at_t",
    "actual",
    "expected",
    "surprise",
}


def test_event_response_dataset_is_revision_aware_pit_and_content_addressed() -> None:
    dataset = response_dataset()
    assert dataset.revision_aware is True
    assert dataset.point_in_time is True
    assert dataset.shuffle is False
    assert len(dataset.rows) == 4
    assert len(dataset.dataset_sha256) == 64
    assert dataset.source_dataset_ids == ("official-events", "public-market")

    restored = EventResponseDataset.model_validate_json(dataset.model_dump_json())
    assert restored == dataset


def test_event_response_row_rejects_future_event_and_feature_inputs() -> None:
    row = response_row(0)
    payload = row.model_dump(mode="json")
    payload["event_available_at"] = (row.decision_time + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValidationError, match="AQ-CAUSAL-EVENT-LOOKAHEAD"):
        EventResponseRow.model_validate_json(json.dumps(payload))

    payload = row.model_dump(mode="json")
    payload["feature_available_at"] = (row.decision_time + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValidationError, match="AQ-CAUSAL-FEATURE-LOOKAHEAD"):
        EventResponseRow.model_validate_json(json.dumps(payload))


def test_event_response_row_factory_binds_one_canonical_revision() -> None:
    event = canonical()
    template = response_row(0)
    row_values = {
        name: getattr(template, name)
        for name in EventResponseRow.model_fields
        if name not in CANONICAL_BOUND_FIELDS
    }
    decision = event.available_at + timedelta(seconds=1)
    row_values.update(
        decision_time=decision,
        feature_available_at=decision,
        label_start_time=decision + timedelta(minutes=1),
        label_end_time=decision + timedelta(days=7),
        outcome_available_at=decision + timedelta(days=7, minutes=1),
    )
    row = EventResponseRow.from_canonical_event(
        canonical_event=event,
        row_values=row_values,
    )
    row.assert_canonical_event_binding(event)
    assert row.event_revision_id == event.revision_id
    assert row.canonical_event_sha256 == event.canonical_sha256

    forged = row.model_copy(update={"canonical_event_sha256": "f" * 64})
    with pytest.raises(ValueError, match="AQ-CAUSAL-CANONICAL-EVENT-BINDING-MISMATCH"):
        forged.assert_canonical_event_binding(event)


def test_event_response_row_factory_rejects_canonical_field_override() -> None:
    event = canonical()
    template = response_row(0)
    row_values = {
        name: getattr(template, name)
        for name in EventResponseRow.model_fields
        if name not in CANONICAL_BOUND_FIELDS
    }
    row_values["event_id"] = "forged-event"
    with pytest.raises(ValueError, match="AQ-CAUSAL-CANONICAL-BOUND-FIELD-OVERRIDE"):
        EventResponseRow.from_canonical_event(
            canonical_event=event,
            row_values=row_values,
        )


def test_event_response_row_rejects_incomplete_or_forged_future_labels() -> None:
    row = response_row(0)
    payload = row.model_dump(mode="json")
    payload["label_end_time"] = (row.decision_time + timedelta(days=1)).isoformat()
    payload["outcome_available_at"] = (row.decision_time + timedelta(days=1, minutes=1)).isoformat()
    with pytest.raises(ValidationError, match="AQ-CAUSAL-SEVEN-DAY-OUTCOME-INCOMPLETE"):
        EventResponseRow.model_validate_json(json.dumps(payload))

    payload = row.model_dump(mode="json")
    payload["outcome_available_at"] = (row.label_end_time - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValidationError, match="AQ-CAUSAL-OUTCOME-AVAILABLE-BEFORE-LABEL"):
        EventResponseRow.model_validate_json(json.dumps(payload))


def test_event_response_row_recomputes_surprise_and_missingness() -> None:
    row = response_row(0)
    payload = row.model_dump(mode="json")
    payload["surprise"] = "99"
    with pytest.raises(ValidationError, match="AQ-CAUSAL-SURPRISE-MISMATCH"):
        EventResponseRow.model_validate_json(json.dumps(payload))

    payload = row.model_dump(mode="json")
    payload["market_reflection_at_t"] = None
    with pytest.raises(ValidationError, match="MARKET_REFLECTION_MISSING"):
        EventResponseRow.model_validate_json(json.dumps(payload))


def test_dataset_rejects_reordering_future_outcomes_and_hash_forgery() -> None:
    dataset = response_dataset()
    payload = dataset.model_dump(mode="json")
    payload["rows"] = list(reversed(payload["rows"]))
    with pytest.raises(ValidationError, match="time ordered"):
        EventResponseDataset.model_validate_json(json.dumps(payload))

    payload = dataset.model_dump(mode="json")
    payload["as_of_time"] = dataset.rows[-1].label_end_time.isoformat()
    with pytest.raises(ValidationError, match="AQ-CAUSAL-DATASET-OUTCOME-LOOKAHEAD"):
        EventResponseDataset.model_validate_json(json.dumps(payload))

    payload = dataset.model_dump(mode="json")
    payload["dataset_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="dataset hash mismatch"):
        EventResponseDataset.model_validate_json(json.dumps(payload))


def test_dataset_rejects_one_revision_id_bound_to_different_events() -> None:
    dataset = response_dataset()
    payload = dataset.model_dump(mode="json")
    payload["rows"][1]["event_revision_id"] = payload["rows"][0]["event_revision_id"]
    with pytest.raises(ValidationError, match="AQ-CAUSAL-EVENT-REVISION-BINDING-MISMATCH"):
        EventResponseDataset.model_validate_json(json.dumps(payload))


def test_event_response_row_requires_nonpositive_mae() -> None:
    row = response_row(0)
    payload = row.model_dump(mode="json")
    payload["maximum_adverse_excursion"] = str(Decimal("0.01"))
    with pytest.raises(ValidationError, match="non-positive"):
        EventResponseRow.model_validate_json(json.dumps(payload))
