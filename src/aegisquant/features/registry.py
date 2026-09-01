"""Versioned registry and fail-closed construction of feature snapshots."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.intelligence import QualityState
from aegisquant.domain.time import ensure_utc
from aegisquant.features.models import (
    FeatureDefinition,
    FeatureSetManifest,
    FeatureSnapshot,
    FeatureValueRecord,
    FeatureVector,
)


class FeatureRegistry:
    """In-memory deterministic registry; persistent manifests are content addressed."""

    def __init__(self) -> None:
        self._definitions: dict[str, FeatureDefinition] = {}

    def register(self, definition: FeatureDefinition) -> None:
        key = definition.qualified_id
        current = self._definitions.get(key)
        if current is not None and current != definition:
            raise ValueError("AQ-FEATURE-REGISTRY-CONFLICT")
        self._definitions[key] = definition

    def register_all(self, definitions: Iterable[FeatureDefinition]) -> None:
        for definition in definitions:
            self.register(definition)

    def get(self, feature_key: str) -> FeatureDefinition:
        try:
            return self._definitions[feature_key]
        except KeyError as error:
            raise KeyError(f"AQ-FEATURE-NOT-REGISTERED: {feature_key}") from error

    def definitions(self) -> tuple[FeatureDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))

    def manifest(self, *, feature_set_id: str, created_at: datetime) -> FeatureSetManifest:
        return FeatureSetManifest(
            feature_set_id=feature_set_id,
            definition_hashes=tuple(
                sorted(definition.definition_sha256 for definition in self._definitions.values())
            ),
            created_at=ensure_utc(created_at),
        )

    def snapshot(
        self,
        *,
        vector: FeatureVector,
        as_of_time: datetime,
        feature_set_id: str,
        values_uri: str,
        quality_state: QualityState,
    ) -> FeatureSnapshot:
        decision_time = ensure_utc(as_of_time)
        if vector.available_time > decision_time:
            raise ValueError("AQ-FEATURE-LOOKAHEAD")
        registered = {definition.qualified_id for definition in self._definitions.values()}
        vector_keys = {item.feature_key for item in vector.values}
        missing_keys = set(vector.missing_flags)
        unknown = (vector_keys | missing_keys) - registered
        if unknown:
            raise ValueError(f"AQ-FEATURE-NOT-REGISTERED: {sorted(unknown)}")
        payload = {
            "entity_id": vector.entity_id,
            "as_of_time": decision_time.isoformat(),
            "feature_set_id": feature_set_id,
            "values": [item.model_dump(mode="json") for item in vector.values],
            "missing_flags": list(vector.missing_flags),
            "source_dataset_ids": list(vector.source_dataset_ids),
            "watermark_time": vector.available_time.isoformat(),
            "quality_state": quality_state.value,
        }
        return FeatureSnapshot(
            feature_snapshot_id=canonical_sha256(payload),
            entity_id=vector.entity_id,
            as_of_time=decision_time,
            feature_set_id=feature_set_id,
            values_uri=values_uri,
            values=tuple(sorted(vector.values, key=lambda item: item.feature_key)),
            missing_flags=tuple(sorted(vector.missing_flags)),
            source_dataset_ids=tuple(sorted(set(vector.source_dataset_ids))),
            watermark_time=vector.available_time,
            quality_state=quality_state,
        )


def values_by_key(vector: FeatureVector) -> dict[str, object]:
    return {item.feature_key: item.value for item in vector.values}


def feature_value(feature_key: str, value: object) -> FeatureValueRecord:
    if not isinstance(value, (Decimal, str, int, bool)):
        raise TypeError("feature values must use Decimal, int, str, or bool")
    return FeatureValueRecord(feature_key=feature_key, value=value)
