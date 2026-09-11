"""One-way final-holdout freeze gate with a content-addressed audit chain."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime

ZERO_HASH = "0" * 64


class HoldoutState(StrEnum):
    LOCKED = "LOCKED"
    FROZEN = "FROZEN"
    OPENED = "OPENED"


class FreezeAdmissionExtension(DomainModel):
    """The additional v5 evidence must be frozen with the original component set."""

    schema_version: Literal["freeze-admission-v2"] = "freeze-admission-v2"
    data_lineage_sha256: str
    risk_policy_sha256: str
    execution_rules_sha256: str
    capacity_policy_sha256: str
    statistical_protocol_sha256: str
    comparison_family_sha256: str
    complete_trial_registry_sha256: str
    model_weights_manifest_sha256: str
    training_update_program_sha256: str
    training_update_policy: Literal["NO_TEST_PERIOD_UPDATES", "FROZEN_SCHEDULE_ONLY"]
    independent_preaccess_review_sha256: str

    @model_validator(mode="after")
    def validate_components(self) -> FreezeAdmissionExtension:
        for key, value in self.model_dump().items():
            if key.endswith("_sha256"):
                ensure_sha256(value, field_name=key)
        return self


class ResearchFreezeManifest(DomainModel):
    freeze_id: str
    dataset_sha256: str
    feature_set_sha256: str
    label_set_sha256: str
    universe_sha256: str
    split_sha256: str
    cost_policy_sha256: str
    model_spec_sha256: str
    parameters_sha256: str
    code_sha256: str
    frozen_at: UtcDateTime
    frozen: Literal[True] = True
    admission_extension: FreezeAdmissionExtension | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @field_validator(
        "dataset_sha256",
        "feature_set_sha256",
        "label_set_sha256",
        "universe_sha256",
        "split_sha256",
        "cost_policy_sha256",
        "model_spec_sha256",
        "parameters_sha256",
        "code_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="freeze component hash")

    @model_validator(mode="after")
    def validate_freeze_id(self) -> ResearchFreezeManifest:
        payload: dict[str, Any] = {
            "dataset_sha256": self.dataset_sha256,
            "feature_set_sha256": self.feature_set_sha256,
            "label_set_sha256": self.label_set_sha256,
            "universe_sha256": self.universe_sha256,
            "split_sha256": self.split_sha256,
            "cost_policy_sha256": self.cost_policy_sha256,
            "model_spec_sha256": self.model_spec_sha256,
            "parameters_sha256": self.parameters_sha256,
            "code_sha256": self.code_sha256,
            "frozen_at": self.frozen_at.isoformat(),
            "frozen": self.frozen,
        }
        if self.admission_extension is not None:
            payload["admission_extension"] = self.admission_extension.model_dump(mode="json")
        if self.freeze_id != canonical_sha256(payload):
            raise ValueError("freeze_id must equal canonical manifest hash")
        return self


def create_freeze_manifest(
    *,
    dataset_sha256: str,
    feature_set_sha256: str,
    label_set_sha256: str,
    universe_sha256: str,
    split_sha256: str,
    cost_policy_sha256: str,
    model_spec_sha256: str,
    parameters_sha256: str,
    code_sha256: str,
    frozen_at: UtcDateTime,
    admission_extension: FreezeAdmissionExtension | None = None,
) -> ResearchFreezeManifest:
    payload: dict[str, Any] = {
        "dataset_sha256": dataset_sha256,
        "feature_set_sha256": feature_set_sha256,
        "label_set_sha256": label_set_sha256,
        "universe_sha256": universe_sha256,
        "split_sha256": split_sha256,
        "cost_policy_sha256": cost_policy_sha256,
        "model_spec_sha256": model_spec_sha256,
        "parameters_sha256": parameters_sha256,
        "code_sha256": code_sha256,
        "frozen_at": frozen_at.isoformat(),
        "frozen": True,
    }
    if admission_extension is not None:
        payload["admission_extension"] = admission_extension.model_dump(mode="json")
    return ResearchFreezeManifest(
        freeze_id=canonical_sha256(payload),
        dataset_sha256=dataset_sha256,
        feature_set_sha256=feature_set_sha256,
        label_set_sha256=label_set_sha256,
        universe_sha256=universe_sha256,
        split_sha256=split_sha256,
        cost_policy_sha256=cost_policy_sha256,
        model_spec_sha256=model_spec_sha256,
        parameters_sha256=parameters_sha256,
        code_sha256=code_sha256,
        frozen_at=frozen_at,
        frozen=True,
        admission_extension=admission_extension,
    )


class HoldoutAuditEntry(DomainModel):
    sequence: int
    event: str
    occurred_at: UtcDateTime
    state: HoldoutState
    freeze_id: str | None
    reason: str
    previous_hash: str
    entry_hash: str

    @model_validator(mode="after")
    def validate_entry(self) -> HoldoutAuditEntry:
        if self.sequence < 1:
            raise ValueError("holdout audit sequence starts at one")
        ensure_sha256(self.previous_hash, field_name="previous audit hash")
        payload = {
            "sequence": self.sequence,
            "event": self.event,
            "occurred_at": self.occurred_at.isoformat(),
            "state": self.state.value,
            "freeze_id": self.freeze_id,
            "reason": self.reason,
            "previous_hash": self.previous_hash,
        }
        if self.entry_hash != canonical_sha256(payload):
            raise ValueError("holdout audit entry hash mismatch")
        return self


class FinalHoldoutVault[T]:
    """The loader is invoked only after a complete freeze and at most once."""

    def __init__(
        self,
        *,
        holdout_id: str,
        expected_dataset_sha256: str,
        loader: Callable[[], T],
    ) -> None:
        ensure_sha256(expected_dataset_sha256, field_name="holdout dataset hash")
        if not holdout_id.strip():
            raise ValueError("holdout_id is required")
        self.holdout_id = holdout_id
        self.expected_dataset_sha256 = expected_dataset_sha256
        self._loader = loader
        self._state = HoldoutState.LOCKED
        self._freeze: ResearchFreezeManifest | None = None
        self._audit: list[HoldoutAuditEntry] = []

    @property
    def state(self) -> HoldoutState:
        return self._state

    def _record(
        self, *, event: str, occurred_at: UtcDateTime, reason: str, freeze_id: str | None
    ) -> None:
        payload = {
            "sequence": len(self._audit) + 1,
            "event": event,
            "occurred_at": occurred_at.isoformat(),
            "state": self._state.value,
            "freeze_id": freeze_id,
            "reason": reason,
            "previous_hash": self._audit[-1].entry_hash if self._audit else ZERO_HASH,
        }
        self._audit.append(
            HoldoutAuditEntry(
                sequence=len(self._audit) + 1,
                event=event,
                occurred_at=occurred_at,
                state=self._state,
                freeze_id=freeze_id,
                reason=reason,
                previous_hash=self._audit[-1].entry_hash if self._audit else ZERO_HASH,
                entry_hash=canonical_sha256(payload),
            )
        )

    def freeze(self, manifest: ResearchFreezeManifest, *, occurred_at: UtcDateTime) -> None:
        if self._state is not HoldoutState.LOCKED:
            self._record(
                event="FREEZE_DENIED",
                occurred_at=occurred_at,
                reason="holdout can only freeze once from LOCKED",
                freeze_id=manifest.freeze_id,
            )
            raise ValueError("AQ-HOLDOUT-FREEZE-STATE-INVALID")
        if manifest.dataset_sha256 != self.expected_dataset_sha256:
            self._record(
                event="FREEZE_DENIED",
                occurred_at=occurred_at,
                reason="dataset hash differs from sealed holdout",
                freeze_id=manifest.freeze_id,
            )
            raise ValueError("AQ-HOLDOUT-DATASET-HASH-MISMATCH")
        self._freeze = manifest
        self._state = HoldoutState.FROZEN
        self._record(
            event="FROZEN",
            occurred_at=occurred_at,
            reason="all research components frozen",
            freeze_id=manifest.freeze_id,
        )

    def open_once(self, *, freeze_id: str, occurred_at: UtcDateTime) -> T:
        if self._state is not HoldoutState.FROZEN or self._freeze is None:
            self._record(
                event="OPEN_DENIED",
                occurred_at=occurred_at,
                reason="final holdout is unavailable before freeze or after opening",
                freeze_id=freeze_id,
            )
            raise PermissionError("AQ-HOLDOUT-LOCKED")
        if freeze_id != self._freeze.freeze_id:
            self._record(
                event="OPEN_DENIED",
                occurred_at=occurred_at,
                reason="freeze id mismatch",
                freeze_id=freeze_id,
            )
            raise PermissionError("AQ-HOLDOUT-FREEZE-ID-MISMATCH")
        self._state = HoldoutState.OPENED
        self._record(
            event="OPENED_ONCE",
            occurred_at=occurred_at,
            reason="one-time final evaluation access",
            freeze_id=freeze_id,
        )
        return self._loader()

    def audit_log(self) -> tuple[HoldoutAuditEntry, ...]:
        return tuple(self._audit)
