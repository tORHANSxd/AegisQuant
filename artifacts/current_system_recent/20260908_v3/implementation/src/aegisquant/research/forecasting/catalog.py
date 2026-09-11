"""Explicit, license-aware capability catalog for Forecast Council 2.0."""

from __future__ import annotations

from typing import Final

from aegisquant.domain.time import UtcDateTime
from aegisquant.research.forecasting.contracts import (
    CapabilityMatrix,
    CapabilityStatus,
    CouncilHorizon,
    ForecastModality,
    ForecastModelClass,
    LicenseStatus,
    MarketRegime,
    ModelCapability,
    PredictionMode,
)

ALL_HORIZONS: Final = tuple(CouncilHorizon)
ALL_REGIMES: Final = tuple(MarketRegime)
MEDIUM_HORIZONS: Final = (
    CouncilHorizon.FIVE_MINUTES,
    CouncilHorizon.FIFTEEN_MINUTES,
    CouncilHorizon.THIRTY_MINUTES,
    CouncilHorizon.ONE_HOUR,
    CouncilHorizon.FOUR_HOURS,
    CouncilHorizon.TWELVE_HOURS,
    CouncilHorizon.ONE_DAY,
    CouncilHorizon.THREE_DAYS,
    CouncilHorizon.SEVEN_DAYS,
)
MICRO_HORIZONS: Final = (
    CouncilHorizon.FIVE_SECONDS,
    CouncilHorizon.FIFTEEN_SECONDS,
    CouncilHorizon.THIRTY_SECONDS,
    CouncilHorizon.ONE_MINUTE,
    CouncilHorizon.THREE_MINUTES,
    CouncilHorizon.FIVE_MINUTES,
    CouncilHorizon.FIFTEEN_MINUTES,
)


def _candidate(
    *,
    candidate_id: str,
    family: str,
    model_class: ForecastModelClass,
    modality: ForecastModality,
    status: CapabilityStatus,
    prediction_modes: tuple[PredictionMode, ...],
    horizons: tuple[CouncilHorizon, ...],
    adapter_name: str,
    model_revision: str,
    code_license: str,
    weights_license: str,
    license_status: LicenseStatus,
    weights_required: bool = False,
    weight_sha256: str | None = None,
) -> ModelCapability:
    return ModelCapability(
        candidate_id=candidate_id,
        family=family,
        model_class=model_class,
        modality=modality,
        prediction_modes=prediction_modes,
        supported_horizons=horizons,
        supported_regimes=ALL_REGIMES,
        supports_return_distribution=True,
        supports_direction_probabilities=True,
        supports_volatility_distribution=True,
        supports_range_and_excursions=True,
        supports_barrier_and_tail=True,
        supports_liquidity_spread_slippage=True,
        supports_uncertainty_and_abstain=True,
        status=status,
        adapter_name=adapter_name,
        model_revision=model_revision,
        code_license=code_license,
        weights_license=weights_license,
        license_status=license_status,
        weights_required=weights_required,
        weight_sha256=weight_sha256,
        production_allowed=False,
    )


def default_capability_matrix(*, as_of_time: UtcDateTime) -> CapabilityMatrix:
    """Return the deterministic catalog; catalogued never means installed or promoted."""

    candidates = (
        _candidate(
            candidate_id="naive-last-baseline",
            family="NAIVE_LAST",
            model_class=ForecastModelClass.BASELINE,
            modality=ForecastModality.NUMERIC_ONLY,
            status=CapabilityStatus.RUNNABLE_LOCAL,
            prediction_modes=(PredictionMode.BASELINE,),
            horizons=ALL_HORIZONS,
            adapter_name="aegisquant.research.models.baselines",
            model_revision="project-source",
            code_license="PROJECT",
            weights_license="NOT_APPLICABLE",
            license_status=LicenseStatus.PROJECT_OWNED,
        ),
        _candidate(
            candidate_id="linear-baseline",
            family="LINEAR",
            model_class=ForecastModelClass.BASELINE,
            modality=ForecastModality.NUMERIC_ONLY,
            status=CapabilityStatus.RUNNABLE_LOCAL,
            prediction_modes=(PredictionMode.BASELINE,),
            horizons=ALL_HORIZONS,
            adapter_name="aegisquant.research.models.baselines",
            model_revision="project-source",
            code_license="PROJECT",
            weights_license="NOT_APPLICABLE",
            license_status=LicenseStatus.PROJECT_OWNED,
        ),
        _candidate(
            candidate_id="timesfm-2.5-candidate",
            family="TIMESFM_2_5",
            model_class=ForecastModelClass.FOUNDATION,
            modality=ForecastModality.NUMERIC_ONLY,
            status=CapabilityStatus.DEPENDENCY_BLOCKED,
            prediction_modes=(PredictionMode.ZERO_SHOT,),
            horizons=MEDIUM_HORIZONS,
            adapter_name="timesfm-adapter-contract",
            model_revision="UNPINNED",
            code_license="UNVERIFIED_FOR_P07",
            weights_license="UNVERIFIED_FOR_P07",
            license_status=LicenseStatus.UNVERIFIED,
            weights_required=True,
        ),
        _candidate(
            candidate_id="chronos-2-candidate",
            family="CHRONOS_2",
            model_class=ForecastModelClass.FOUNDATION,
            modality=ForecastModality.NUMERIC_ONLY,
            status=CapabilityStatus.ADAPTER_ONLY,
            prediction_modes=(PredictionMode.ZERO_SHOT,),
            horizons=MEDIUM_HORIZONS,
            adapter_name="aegisquant.research.models.foundation.evaluate_chronos2",
            model_revision="ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a",
            code_license="Apache-2.0",
            weights_license="Apache-2.0",
            license_status=LicenseStatus.VERIFIED_PERMISSIVE,
            weights_required=True,
            weight_sha256="492290ae82bb89f9769e3479ce90b3179de1f33e600c34daa0352531538b23cd",
        ),
        _candidate(
            candidate_id="moirai-2-candidate",
            family="MOIRAI_2",
            model_class=ForecastModelClass.FOUNDATION,
            modality=ForecastModality.NUMERIC_ONLY,
            status=CapabilityStatus.ADAPTER_ONLY,
            prediction_modes=(PredictionMode.ZERO_SHOT,),
            horizons=MEDIUM_HORIZONS,
            adapter_name="moirai-adapter-contract",
            model_revision="30f43ff08c8494f4943ae1521e9d4e94a0fbb389",
            code_license="Apache-2.0",
            weights_license="CC-BY-NC-4.0",
            license_status=LicenseStatus.RESEARCH_ONLY,
            weights_required=True,
            weight_sha256="fb5652a3db8ea572606221b7cb1e77bb8962b168e4d4cc752cf31ceb04074669",
        ),
        _candidate(
            candidate_id="toto-2.0-candidate",
            family="TOTO_2_0",
            model_class=ForecastModelClass.FOUNDATION,
            modality=ForecastModality.NUMERIC_ONLY,
            status=CapabilityStatus.DEPENDENCY_BLOCKED,
            prediction_modes=(PredictionMode.ZERO_SHOT,),
            horizons=MEDIUM_HORIZONS,
            adapter_name="toto-adapter-contract",
            model_revision="UNPINNED",
            code_license="UNVERIFIED_FOR_P07",
            weights_license="UNVERIFIED_FOR_P07",
            license_status=LicenseStatus.UNVERIFIED,
            weights_required=True,
        ),
        *(
            _candidate(
                candidate_id=f"{family.casefold().replace('_', '-')}-candidate",
                family=family,
                model_class=ForecastModelClass.SUPERVISED,
                modality=ForecastModality.NUMERIC_ONLY,
                status=(
                    CapabilityStatus.RUNNABLE_LOCAL
                    if family in {"TCN", "MULTI_SCALE_PATCH_TRANSFORMER"}
                    else CapabilityStatus.ADAPTER_ONLY
                ),
                prediction_modes=(PredictionMode.TRAINED,),
                horizons=MEDIUM_HORIZONS,
                adapter_name=(
                    "aegisquant.research.models.deep"
                    if family in {"TCN", "MULTI_SCALE_PATCH_TRANSFORMER"}
                    else f"{family.casefold()}-adapter-contract"
                ),
                model_revision="project-source",
                code_license="PROJECT"
                if family in {"TCN", "MULTI_SCALE_PATCH_TRANSFORMER"}
                else "UNVERIFIED_FOR_P07",
                weights_license="GENERATED_DURING_TRAINING",
                license_status=(
                    LicenseStatus.PROJECT_OWNED
                    if family in {"TCN", "MULTI_SCALE_PATCH_TRANSFORMER"}
                    else LicenseStatus.UNVERIFIED
                ),
            )
            for family in (
                "PATCHTST",
                "ITRANSFORMER",
                "TFT",
                "N_HITS",
                "N_BEATSX",
                "TIDE",
                "TCN",
                "DLINEAR_NLINEAR",
                "MULTI_SCALE_PATCH_TRANSFORMER",
                "MAMBA",
            )
        ),
        *(
            _candidate(
                candidate_id=f"{family.casefold().replace('_', '-')}-candidate",
                family=family,
                model_class=ForecastModelClass.MICROSTRUCTURE,
                modality=ForecastModality.NUMERIC_ONLY,
                status=CapabilityStatus.ADAPTER_ONLY,
                prediction_modes=(PredictionMode.TRAINED,),
                horizons=MICRO_HORIZONS,
                adapter_name=f"{family.casefold()}-adapter-contract",
                model_revision="UNPINNED",
                code_license="UNVERIFIED_FOR_P07",
                weights_license="UNVERIFIED_FOR_P07",
                license_status=LicenseStatus.UNVERIFIED,
            )
            for family in (
                "DEEPLOB_STYLE",
                "LOB_TRANSFORMER",
                "ORDER_FLOW_TRANSFORMER",
                "HAWKES_PROCESS",
                "HAWKES_NEURAL_RESIDUAL",
            )
        ),
        _candidate(
            candidate_id="vit-vision-candidate",
            family="VIT",
            model_class=ForecastModelClass.VISION,
            modality=ForecastModality.VISION_ONLY,
            status=CapabilityStatus.OPTIONAL,
            prediction_modes=(PredictionMode.TRAINED,),
            horizons=MEDIUM_HORIZONS,
            adapter_name="vit-pit-adapter-contract",
            model_revision="UNPINNED",
            code_license="UNVERIFIED_FOR_P07",
            weights_license="UNVERIFIED_FOR_P07",
            license_status=LicenseStatus.UNVERIFIED,
        ),
        _candidate(
            candidate_id="swin-vision-candidate",
            family="SWIN",
            model_class=ForecastModelClass.VISION,
            modality=ForecastModality.VISION_ONLY,
            status=CapabilityStatus.OPTIONAL,
            prediction_modes=(PredictionMode.TRAINED,),
            horizons=MEDIUM_HORIZONS,
            adapter_name="swin-pit-adapter-contract",
            model_revision="UNPINNED",
            code_license="UNVERIFIED_FOR_P07",
            weights_license="UNVERIFIED_FOR_P07",
            license_status=LicenseStatus.UNVERIFIED,
        ),
        _candidate(
            candidate_id="numeric-vision-fusion-candidate",
            family="NUMERIC_VISION_FUSION",
            model_class=ForecastModelClass.VISION,
            modality=ForecastModality.NUMERIC_VISION,
            status=CapabilityStatus.OPTIONAL,
            prediction_modes=(PredictionMode.TRAINED,),
            horizons=MEDIUM_HORIZONS,
            adapter_name="numeric-vision-pit-adapter-contract",
            model_revision="UNPINNED",
            code_license="UNVERIFIED_FOR_P07",
            weights_license="UNVERIFIED_FOR_P07",
            license_status=LicenseStatus.UNVERIFIED,
        ),
    )
    return CapabilityMatrix(as_of_time=as_of_time, candidates=candidates)
