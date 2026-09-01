# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
from __future__ import annotations

from pathlib import Path

from aegisquant.research.experiments.tracking import MlflowProjection
from aegisquant.research.registry import (
    MlflowGovernedRegistry,
    ModelAlias,
    ModelCard,
    PromotionProposal,
    PromotionState,
)
from tests.p08_helpers import NOW


def test_mlflow_alias_changes_only_after_explicit_non_ai_approval(tmp_path: Path) -> None:
    projection = MlflowProjection(tmp_path / "mlflow")
    run_id = projection.start_run(
        run_name="registry-source", parameters={"seed": 7}, tags={"phase": "P08"}
    )
    source = tmp_path / "model.bin"
    source.write_bytes(b"bounded model")
    card = ModelCard(
        model_name="aegisquant-p08",
        model_version="pending",
        family="LINEAR",
        target="net_return_30m",
        horizons=("30m",),
        intended_use="personal research only",
        prohibited_uses=("live order execution",),
        dataset_sha256="a" * 64,
        split_sha256="b" * 64,
        code_sha256="c" * 64,
        metrics={"mse": 0.1},
        calibration_summary="split conformal on development calibration window",
        resource_summary="CPU only, bounded",
        license_summary="project code proprietary; inputs recorded separately",
        limitations=("not validated on final holdout",),
        created_at_utc=NOW,
    )
    registry = MlflowGovernedRegistry(tracking_uri=projection.tracking_uri)
    version = registry.register(
        model_name=card.model_name,
        source=source,
        run_id=run_id,
        card=card,
    )
    proposal = PromotionProposal(
        proposal_id="promotion-p08-1",
        model_name=card.model_name,
        model_version=version,
        alias=ModelAlias.CHALLENGER,
        state=PromotionState.APPROVED,
        proposed_by="ai:model-council",
        approved_by="rule:fair-comparison",
        reason="development OOS council result",
        recorded_at_utc=NOW,
    )
    registry.apply_alias(proposal)
    resolved = registry.client.get_model_version_by_alias(card.model_name, "challenger")
    assert str(resolved.version) == version
    assert (
        str(registry.client.get_registered_model(card.model_name).aliases["challenger"]) == version
    )
