"""Pre-fit, pre-trend, balance, overlap, and causal claim diagnostics."""

from __future__ import annotations

from decimal import Decimal

from aegisquant.research.causal.contracts import (
    DEFAULT_CAUSAL_DIAGNOSTIC_POLICY,
    CausalDiagnosticPolicy,
    CausalDiagnostics,
    CovariateBalanceReport,
    PlaceboTestResult,
    PreTreatmentFitReport,
    PreTrendReport,
    PropensityOverlapReport,
)


def pre_treatment_fit_report(
    *,
    treated_path: tuple[Decimal, ...],
    counterfactual_path: tuple[Decimal, ...],
    policy: CausalDiagnosticPolicy = DEFAULT_CAUSAL_DIAGNOSTIC_POLICY,
) -> PreTreatmentFitReport:
    return PreTreatmentFitReport.from_paths(
        treated_path=treated_path,
        counterfactual_path=counterfactual_path,
        maximum_normalized_error=policy.maximum_pre_treatment_nrmse,
    )


def pretrend_report(
    *,
    treated_path: tuple[Decimal, ...],
    counterfactual_path: tuple[Decimal, ...],
    policy: CausalDiagnosticPolicy = DEFAULT_CAUSAL_DIAGNOSTIC_POLICY,
) -> PreTrendReport:
    return PreTrendReport.from_paths(
        treated_path=treated_path,
        counterfactual_path=counterfactual_path,
        maximum_absolute_slope_gap=policy.maximum_pretrend_slope_gap,
    )


def covariate_balance_report(
    *,
    covariate_names: tuple[str, ...],
    treated_covariates: tuple[tuple[Decimal, ...], ...],
    candidate_covariates: tuple[tuple[Decimal, ...], ...],
    matched_covariates: tuple[tuple[Decimal, ...], ...],
    policy: CausalDiagnosticPolicy = DEFAULT_CAUSAL_DIAGNOSTIC_POLICY,
) -> CovariateBalanceReport:
    return CovariateBalanceReport.from_covariates(
        covariate_names=covariate_names,
        treated_covariates=treated_covariates,
        candidate_covariates=candidate_covariates,
        matched_covariates=matched_covariates,
        maximum_allowed=policy.maximum_absolute_smd,
    )


def propensity_overlap_report(
    *,
    propensity_scores: tuple[Decimal, ...],
    treatments: tuple[bool, ...],
    policy: CausalDiagnosticPolicy = DEFAULT_CAUSAL_DIAGNOSTIC_POLICY,
) -> PropensityOverlapReport:
    return PropensityOverlapReport.from_scores(
        propensity_scores=propensity_scores,
        treatments=treatments,
        lower_bound=policy.propensity_lower_bound,
        upper_bound=policy.propensity_upper_bound,
    )


def assemble_causal_diagnostics(
    *,
    pre_treatment_fit: PreTreatmentFitReport,
    pretrend: PreTrendReport,
    covariate_balance: CovariateBalanceReport,
    propensity_overlap: PropensityOverlapReport,
    placebo_tests: tuple[PlaceboTestResult, ...],
    control_count: int,
    unresolved_assumptions: tuple[str, ...] = (),
    policy: CausalDiagnosticPolicy = DEFAULT_CAUSAL_DIAGNOSTIC_POLICY,
) -> CausalDiagnostics:
    by_kind = {item.kind: item for item in placebo_tests}
    if set(by_kind) != set(policy.required_placebo_kinds):
        raise ValueError("P06 causal diagnostics require every configured placebo kind")
    reasons: list[str] = []
    if not pre_treatment_fit.passed:
        reasons.append("PRE_TREATMENT_FIT_FAILED")
    if not pretrend.passed:
        reasons.append("PRE_TREND_FAILED")
    if not covariate_balance.passed:
        reasons.append("COVARIATE_BALANCE_FAILED")
    if not propensity_overlap.passed:
        reasons.append("PROPENSITY_OVERLAP_FAILED")
    if control_count < policy.minimum_controls:
        reasons.append("INSUFFICIENT_CONTROLS")
    ordered_placebos = tuple(by_kind[kind] for kind in policy.required_placebo_kinds)
    if any(not item.passed for item in ordered_placebos):
        reasons.append("PLACEBO_FAILED")
    assumptions = tuple(sorted(set(unresolved_assumptions)))
    if assumptions:
        reasons.append("UNRESOLVED_IDENTIFICATION_ASSUMPTIONS")
    return CausalDiagnostics(
        policy=policy,
        pre_treatment_fit=pre_treatment_fit,
        pretrend=pretrend,
        covariate_balance=covariate_balance,
        propensity_overlap=propensity_overlap,
        placebo_tests=ordered_placebos,
        control_count=control_count,
        minimum_controls=policy.minimum_controls,
        required_placebo_kinds=policy.required_placebo_kinds,
        unresolved_assumptions=assumptions,
        passed=not reasons,
        reason_codes=tuple(reasons),
    )
