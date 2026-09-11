# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""License-aware foundation-model manifests and finite Chronos-2 CPU evaluation."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import torch
from chronos import BaseChronosPipeline
from pydantic import Field, field_validator

from aegisquant.data.hashing import ensure_sha256, sha256_file
from aegisquant.domain.base import DomainModel


class FoundationCapability(StrEnum):
    EVALUABLE = "EVALUABLE"
    LICENSE_RESEARCH_ONLY = "LICENSE_RESEARCH_ONLY"
    STATIC_ANALYSIS_REQUIRED = "STATIC_ANALYSIS_REQUIRED"


class FoundationModelManifest(DomainModel):
    family: str
    model_id: str
    revision: str
    code_source: str
    code_license: str
    weights_license: str
    weight_filename: str
    weight_sha256: str
    weight_size_bytes: int = Field(gt=0)
    capability: FoundationCapability
    production_allowed: bool
    reason: str

    @field_validator("weight_sha256")
    @classmethod
    def validate_weight_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="foundation model weight hash")


FOUNDATION_MODELS = (
    FoundationModelManifest(
        family="CHRONOS_2",
        model_id="autogluon/chronos-2-small",
        revision="ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a",
        code_source="https://github.com/amazon-science/chronos-forecasting",
        code_license="Apache-2.0",
        weights_license="Apache-2.0",
        weight_filename="model.safetensors",
        weight_sha256="492290ae82bb89f9769e3479ce90b3179de1f33e600c34daa0352531538b23cd",
        weight_size_bytes=111_749_048,
        capability=FoundationCapability.EVALUABLE,
        production_allowed=True,
        reason="small Apache-2.0 checkpoint selected for finite CPU evaluation",
    ),
    FoundationModelManifest(
        family="MOIRAI_2",
        model_id="Salesforce/moirai-2.0-R-small",
        revision="30f43ff08c8494f4943ae1521e9d4e94a0fbb389",
        code_source="https://github.com/SalesforceAIResearch/uni2ts",
        code_license="Apache-2.0",
        weights_license="CC-BY-NC-4.0",
        weight_filename="model.safetensors",
        weight_sha256="fb5652a3db8ea572606221b7cb1e77bb8962b168e4d4cc752cf31ceb04074669",
        weight_size_bytes=45_557_824,
        capability=FoundationCapability.LICENSE_RESEARCH_ONLY,
        production_allowed=False,
        reason="non-commercial weights are excluded from production candidates",
    ),
    FoundationModelManifest(
        family="TIMESFM_3",
        model_id="google/timesfm-3.0-pytorch",
        revision="900fcab43d1bfe71733a33b3fec61a41fce28a27",
        code_source="https://github.com/google-research/timesfm",
        code_license="Apache-2.0",
        weights_license="TimesFM-Non-Commercial-License-1.0",
        weight_filename="model.safetensors",
        weight_sha256="a7592b0a8432baee54483254e5647856911ce69e09d09a9bb65904b2d98f17da",
        weight_size_bytes=1_322_898_824,
        capability=FoundationCapability.LICENSE_RESEARCH_ONLY,
        production_allowed=False,
        reason="weights prohibit commercial and production use",
    ),
    FoundationModelManifest(
        family="KRONOS",
        model_id="NeoQuasar/Kronos-mini",
        revision="f4e68697d9d5aed55cef5c96aabc3376bcad9f81",
        code_source="https://github.com/shiyu-coder/Kronos",
        code_license="MIT",
        weights_license="MIT",
        weight_filename="model.safetensors",
        weight_sha256="a7d5f37e2e9fbd9891f7d7d4f72574512dd1f704fee14223e0a8cd0fbf54197c",
        weight_size_bytes=16_414_000,
        capability=FoundationCapability.STATIC_ANALYSIS_REQUIRED,
        production_allowed=False,
        reason="external repository execution is blocked until P09 static analysis",
    ),
)


class FoundationEvaluation(DomainModel):
    manifest: FoundationModelManifest
    context_length: int = Field(gt=0)
    prediction_length: int = Field(gt=0)
    median: tuple[float, ...]
    weight_path: str
    verified_weight_sha256: str

    @field_validator("verified_weight_sha256")
    @classmethod
    def validate_verified_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="verified foundation weight hash")


def evaluate_chronos2(
    *, context: tuple[float, ...], prediction_length: int, cache_dir: Path
) -> FoundationEvaluation:
    manifest = FOUNDATION_MODELS[0]
    if len(context) < 8 or prediction_length < 1 or prediction_length > 64:
        raise ValueError("Chronos finite evaluation bounds are invalid")
    pipeline = BaseChronosPipeline.from_pretrained(
        manifest.model_id,
        revision=manifest.revision,
        cache_dir=str(cache_dir),
        device_map="cpu",
        torch_dtype=torch.float32,
    )
    forecasts = pipeline.predict(
        [torch.tensor(context, dtype=torch.float32)], prediction_length=prediction_length
    )
    if not isinstance(forecasts, list) or len(forecasts) != 1:
        raise ValueError("Chronos prediction response contract changed")
    forecast = forecasts[0]
    if forecast.ndim != 3:
        raise ValueError("Chronos forecast tensor rank changed")
    median = forecast[:, 1, :].median(dim=0).values
    snapshot = (
        cache_dir
        / f"models--{manifest.model_id.replace('/', '--')}"
        / "snapshots"
        / manifest.revision
    )
    snapshot_weight = snapshot / manifest.weight_filename
    weight_path = snapshot_weight.resolve(strict=True)
    if not weight_path.is_relative_to(cache_dir.resolve()):
        raise ValueError("AQ-FOUNDATION-WEIGHT-PATH-ESCAPE")
    verified = sha256_file(weight_path)
    if verified != manifest.weight_sha256:
        raise ValueError("AQ-FOUNDATION-WEIGHT-HASH-MISMATCH")
    return FoundationEvaluation(
        manifest=manifest,
        context_length=len(context),
        prediction_length=prediction_length,
        median=tuple(float(value) for value in median),
        weight_path=str(weight_path),
        verified_weight_sha256=verified,
    )
