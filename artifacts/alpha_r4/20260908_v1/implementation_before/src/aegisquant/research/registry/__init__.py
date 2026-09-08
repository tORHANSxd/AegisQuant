# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Model cards and explicitly approved MLflow Champion/Challenger aliases."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from mlflow import MlflowException
from mlflow.tracking import MlflowClient
from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_json_bytes, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime


class ModelCard(DomainModel):
    model_name: str
    model_version: str
    family: str
    target: str
    horizons: tuple[str, ...] = Field(min_length=1)
    intended_use: str
    prohibited_uses: tuple[str, ...] = Field(min_length=1)
    dataset_sha256: str
    split_sha256: str
    code_sha256: str
    metrics: dict[str, float]
    calibration_summary: str
    resource_summary: str
    license_summary: str
    limitations: tuple[str, ...] = Field(min_length=1)
    created_at_utc: UtcDateTime

    @field_validator("dataset_sha256", "split_sha256", "code_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="model card hash")


class ModelAlias(StrEnum):
    CHAMPION = "champion"
    CHALLENGER = "challenger"


class PromotionState(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PromotionProposal(DomainModel):
    proposal_id: str
    model_name: str
    model_version: str
    alias: ModelAlias
    state: PromotionState
    proposed_by: str
    approved_by: str | None = None
    reason: str
    recorded_at_utc: UtcDateTime

    @model_validator(mode="after")
    def enforce_human_or_rule_approval(self) -> PromotionProposal:
        if self.state is PromotionState.APPROVED:
            if not self.approved_by or self.approved_by.casefold() == "ai":
                raise ValueError("AI cannot approve a model alias change")
        elif self.approved_by is not None:
            raise ValueError("only approved model promotion may name an approver")
        return self


class MlflowGovernedRegistry:
    def __init__(self, *, tracking_uri: str) -> None:
        self.client = MlflowClient(tracking_uri=tracking_uri)

    def register(self, *, model_name: str, source: Path, run_id: str, card: ModelCard) -> str:
        if not source.exists() or source.is_symlink():
            raise ValueError("registered model source must exist and cannot be a symlink")
        try:
            self.client.create_registered_model(model_name)
        except MlflowException as error:
            if "already exists" not in str(error).casefold():
                raise
        version = self.client.create_model_version(
            name=model_name,
            source=source.resolve().as_uri(),
            run_id=run_id,
            tags={"model_card": canonical_json_bytes(card.model_dump(mode="json")).decode()},
        )
        return str(version.version)

    def apply_alias(self, proposal: PromotionProposal) -> None:
        if proposal.state is not PromotionState.APPROVED:
            raise PermissionError("AQ-MODEL-ALIAS-NOT-APPROVED")
        self.client.set_registered_model_alias(
            proposal.model_name, proposal.alias.value, proposal.model_version
        )
