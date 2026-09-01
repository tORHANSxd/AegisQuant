from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.domain.intelligence import QualityState
from aegisquant.features import (
    FeatureDefinition,
    FeatureDType,
    FeatureEntity,
    FeatureRegistry,
    FeatureValueRecord,
    FeatureVector,
)

NOW = datetime(2026, 9, 1, 8, tzinfo=UTC)


def definition() -> FeatureDefinition:
    return FeatureDefinition(
        feature_id="returns.log",
        version="1.0.0",
        description="log return",
        entity=FeatureEntity.INSTRUMENT,
        dtype=FeatureDType.FLOAT64,
        unit="log_return",
        inputs=("close",),
        formula_reference="P07-test",
        lookback_seconds=60,
        minimum_history=2,
        frequency_seconds=60,
        normalization="none",
        missing_policy="explicit",
        online_compatible=True,
        owner="research",
        tests=("tests/unit/features/test_registry.py",),
    )


def test_definition_rejects_hidden_parameters_and_requires_tests() -> None:
    payload = definition().model_dump()
    payload["feature_id"] = "returns_5m.log"
    with pytest.raises(ValidationError, match="parameters cannot be hidden"):
        FeatureDefinition.model_validate(payload)

    payload["feature_id"] = "returns.log"
    payload["tests"] = ()
    with pytest.raises(ValidationError, match="requires tests"):
        FeatureDefinition.model_validate(payload)


def test_registry_is_versioned_and_fail_closed() -> None:
    registry = FeatureRegistry()
    item = definition()
    registry.register(item)
    registry.register(item)
    assert registry.get(item.qualified_id) == item
    assert registry.manifest(feature_set_id="p07", created_at=NOW).definition_hashes == (
        item.definition_sha256,
    )
    with pytest.raises(KeyError, match="AQ-FEATURE-NOT-REGISTERED"):
        registry.get("returns.log@9.9.9")


def test_snapshot_rejects_future_or_unregistered_vectors_and_is_immutable() -> None:
    registry = FeatureRegistry()
    item = definition()
    registry.register(item)
    vector = FeatureVector(
        entity_id="BINANCE:SPOT:BTCUSDT",
        event_time=NOW,
        available_time=NOW + timedelta(seconds=5),
        values=(FeatureValueRecord(feature_key=item.qualified_id, value=Decimal("0.01")),),
        source_dataset_ids=("market-v1",),
    )
    with pytest.raises(ValueError, match="AQ-FEATURE-LOOKAHEAD"):
        registry.snapshot(
            vector=vector,
            as_of_time=NOW,
            feature_set_id="p07",
            values_uri="memory://features",
            quality_state=QualityState.GOOD,
        )

    snapshot = registry.snapshot(
        vector=vector,
        as_of_time=NOW + timedelta(seconds=5),
        feature_set_id="p07",
        values_uri="memory://features",
        quality_state=QualityState.GOOD,
    )
    assert len(snapshot.feature_snapshot_id) == 64
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.quality_state = QualityState.INVALID  # type: ignore[misc]

    unknown = vector.model_copy(
        update={
            "values": (FeatureValueRecord(feature_key="future.magic@1.0.0", value=Decimal("1")),)
        }
    )
    with pytest.raises(ValueError, match="AQ-FEATURE-NOT-REGISTERED"):
        registry.snapshot(
            vector=unknown,
            as_of_time=NOW + timedelta(seconds=5),
            feature_set_id="p07",
            values_uri="memory://features",
            quality_state=QualityState.GOOD,
        )
