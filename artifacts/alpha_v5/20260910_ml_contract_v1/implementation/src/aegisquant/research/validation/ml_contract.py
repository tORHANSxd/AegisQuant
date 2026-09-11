"""B6 causal episode/OOF protocols. All current real research budgets remain zero."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, JsonValue, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import FiniteDecimal
from aegisquant.research.validation.calendar_walkforward import add_months
from aegisquant.research.validation.evidence_contract import (
    ZERO_BUDGETS,
    require,
    zero_budget_guard,
)
from aegisquant.research.validation.experiment_registry import registered_run
from aegisquant.research.validation.splits import (
    SampleSpan,
    dependency_interval,
    purge_interval_partitions,
)

FILES = (
    "src/aegisquant/research/validation/splits.py",
    "src/aegisquant/research/validation/calendar_walkforward.py",
    "src/aegisquant/research/models/economic_filter.py",
    "src/aegisquant/research/models/uncertainty.py",
    "src/aegisquant/research/validation/statistics.py",
    "src/aegisquant/labels/episodes.py",
    "src/aegisquant/research/validation/ml_contract.py",
    "scripts/run_alpha_v5_walkforward.py",
    "configs/research/alpha_v5_ml_contract.yaml",
    "tests/alpha_v5/test_ml_contract.py",
    "docs/research/alpha_v5_ml_contract.md",
)
OUTER_BOUNDARIES = tuple(
    datetime.fromisoformat(value).replace(tzinfo=UTC)
    for value in ("2022-04-01", "2023-06-01", "2024-08-01", "2025-10-01")
)
DEVELOPMENT_START = datetime(2021, 1, 1, tzinfo=UTC)


class TransformFit(DomainModel):
    name: str
    specification_sha256: str
    fit_sample_ids: tuple[str, ...]
    fitted_at: UtcDateTime


class FoldRegistration(DomainModel):
    generation: str
    fold_id: str
    outer_fold_id: str
    scope: Literal["PURGED_INNER_TRAIN", "PURGED_OUTER_TRAIN"]
    training_spans: tuple[SampleSpan, ...]
    evaluation_spans: tuple[SampleSpan, ...]
    label_contract: dict[str, JsonValue]
    model_specification_sha256: str
    transform_specification_hashes: dict[str, str]
    information_embargo_seconds: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_registration(self) -> FoldRegistration:
        if (
            not self.generation.strip()
            or not self.fold_id.strip()
            or not self.outer_fold_id.strip()
            or not self.label_contract
        ):
            raise ValueError(
                "fold registration needs actual generation, identities and label definition"
            )
        if self.scope == "PURGED_OUTER_TRAIN" and self.fold_id != self.outer_fold_id:
            raise ValueError("outer registration identity must match")
        values = self.training_spans + self.evaluation_spans
        if (
            not self.training_spans
            or not self.evaluation_spans
            or len({item.sample_id for item in values}) != len(values)
        ):
            raise ValueError("registered training/evaluation must be nonempty and disjoint")
        for item in values:
            dependency_interval(item)
        for digest in (
            self.model_specification_sha256,
            *self.transform_specification_hashes.values(),
        ):
            ensure_sha256(digest, field_name="registered fit specification")
        return self

    @property
    def manifest_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))

    @property
    def label_contract_sha256(self) -> str:
        return canonical_sha256(self.label_contract)


class FitProvenance(DomainModel):
    fold_id: str
    model_specification_sha256: str
    split_manifest_sha256: str
    training_payload_sha256: str
    label_contract_sha256: str
    training_spans: tuple[SampleSpan, ...]
    transforms: tuple[TransformFit, ...]
    required_transform_names: tuple[str, ...]
    trained_at: UtcDateTime
    information_embargo_seconds: int = Field(ge=0)
    scope: Literal["PURGED_INNER_TRAIN", "PURGED_OUTER_TRAIN"] = "PURGED_INNER_TRAIN"

    @model_validator(mode="after")
    def validate_fit(self) -> FitProvenance:
        for digest in (
            self.model_specification_sha256,
            self.split_manifest_sha256,
            self.training_payload_sha256,
            self.label_contract_sha256,
        ):
            ensure_sha256(digest, field_name="fit provenance")
        ids = {item.sample_id for item in self.training_spans}
        if not ids or len(ids) != len(self.training_spans):
            raise ValueError("fit training identities must be nonempty and unique")
        if any(dependency_interval(item)[1] > self.trained_at for item in self.training_spans):
            raise ValueError("training labels were not available at fit time")
        names = tuple(item.name for item in self.transforms)
        if (
            len(set(names)) != len(names)
            or len(set(self.required_transform_names)) != len(self.required_transform_names)
            or set(names) != set(self.required_transform_names)
        ):
            raise ValueError("all registered transformations must supply fold-local provenance")
        for transform in self.transforms:
            ensure_sha256(transform.specification_sha256, field_name="transform specification")
            if (
                not transform.fit_sample_ids
                or len(set(transform.fit_sample_ids)) != len(transform.fit_sample_ids)
                or not set(transform.fit_sample_ids) <= ids
            ):
                raise ValueError("transform may fit only inner-train identities")
            if transform.fitted_at > self.trained_at or any(
                dependency_interval(item)[1] > transform.fitted_at
                for item in self.training_spans
                if item.sample_id in transform.fit_sample_ids
            ):
                raise ValueError("transform fitted outside causal training time")
        return self


class OOFPrediction(DomainModel):
    sample: SampleSpan
    prediction: FiniteDecimal
    predicted_at: UtcDateTime
    fit: FitProvenance

    @model_validator(mode="after")
    def validate_oof(self) -> OOFPrediction:
        if self.fit.scope != "PURGED_INNER_TRAIN":
            raise ValueError("outer refit cannot be relabelled as inner OOF")
        validate_prediction_dependencies(self.fit, self.sample, self.predicted_at)
        return self


def validate_prediction_dependencies(
    fit: FitProvenance, sample: SampleSpan, predicted_at: datetime
) -> None:
    FitProvenance.model_validate(
        {
            **dict(fit),
            "training_spans": tuple(
                SampleSpan.model_validate(dict(item)) for item in fit.training_spans
            ),
            "transforms": tuple(TransformFit.model_validate(dict(item)) for item in fit.transforms),
        }
    )
    SampleSpan.model_validate(dict(sample))
    left, _ = dependency_interval(sample)
    if not fit.trained_at <= predicted_at <= sample.group_time:
        raise ValueError("OOF prediction/model must exist by decision time")
    embargo = timedelta(seconds=fit.information_embargo_seconds)
    for trained in fit.training_spans:
        if (
            trained.sample_id == sample.sample_id
            or trained.episode_id == sample.episode_id
            or trained.group_time == sample.group_time
            or dependency_interval(trained)[1] + embargo >= left
        ):
            raise ValueError("OOF fit overlaps held-out time, feature or episode dependencies")


def validate_registered_fit(
    fit: FitProvenance, registrations: tuple[FoldRegistration, ...]
) -> FoldRegistration:
    if (
        not registrations
        or len({item.fold_id for item in registrations}) != len(registrations)
        or len({item.generation for item in registrations}) != 1
    ):
        raise ValueError("current experiment must have one generation and unique registered folds")
    matching = tuple(item for item in registrations if item.fold_id == fit.fold_id)
    if len(matching) != 1:
        raise ValueError("fit fold is absent from the current registration")
    registered = matching[0]
    FoldRegistration.model_validate(dict(registered))
    if (
        fit.split_manifest_sha256 != registered.manifest_sha256
        or fit.label_contract_sha256 != registered.label_contract_sha256
        or fit.scope != registered.scope
        or fit.training_spans != registered.training_spans
        or fit.model_specification_sha256 != registered.model_specification_sha256
        or fit.information_embargo_seconds != registered.information_embargo_seconds
        or {item.name: item.specification_sha256 for item in fit.transforms}
        != registered.transform_specification_hashes
    ):
        raise ValueError("fit provenance does not bind the current registered fold content")
    return registered


def validate_oof_alignment(
    records: tuple[OOFPrediction, ...],
    *,
    sample_ids: tuple[str, ...],
    timestamps: tuple[datetime, ...],
    label_end_times: tuple[datetime, ...],
    consumed_at: datetime,
    registrations: tuple[FoldRegistration, ...],
) -> str:
    if (
        not records
        or len(set(sample_ids)) != len(sample_ids)
        or tuple(item.sample.sample_id for item in records) != sample_ids
        or len(records) != len(timestamps)
        or len(records) != len(label_end_times)
    ):
        raise ValueError("OOF predictions must align exactly with all calibration identities")
    for item, time, end in zip(records, timestamps, label_end_times, strict=True):
        # Revalidate copied/deserialized models at the fit trust boundary.
        OOFPrediction.model_validate(dict(item))
        registered = validate_registered_fit(item.fit, registrations)
        if item.sample not in registered.evaluation_spans:
            raise ValueError("OOF sample is absent from its registered evaluation partition")
        if (
            item.sample.group_time != time
            or item.sample.label_end_time != end
            or dependency_interval(item.sample)[1] >= consumed_at
        ):
            raise ValueError("OOF calibration labels/timestamps are unavailable or misaligned")
    return canonical_sha256([item.model_dump(mode="json") for item in records])


def nested_split_manifest(
    samples: tuple[SampleSpan, ...] | None, *, information_embargo_seconds: int = 14400
) -> dict[str, Any]:
    if information_embargo_seconds < 0:
        raise ValueError("information embargo cannot be negative")
    if samples is not None and len({item.sample_id for item in samples}) != len(samples):
        raise ValueError("nested sample identities must be unique")
    folds: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(pairwise(OUTER_BOUNDARIES)):
        inner_dates = tuple(add_months(start, -9 + 3 * i) for i in range(4))
        row: dict[str, Any] = {
            "outer_fold": index + 1,
            "train_start": DEVELOPMENT_START.isoformat(),
            "test_start": start.isoformat(),
            "test_end": end.isoformat(),
            "inner_validation": [
                {"start": a.isoformat(), "end": b.isoformat()} for a, b in pairwise(inner_dates)
            ],
            "samples": None,
            "status": "NOT_COLLECTED",
        }
        if samples is not None:
            embargo = timedelta(seconds=information_embargo_seconds)
            train = tuple(item for item in samples if DEVELOPMENT_START <= item.group_time < start)
            test = tuple(item for item in samples if start <= item.group_time < end)
            outer, removed = purge_interval_partitions(
                (train, test), ends=(start, end), information_embargo=embargo
            )
            inner_rows: list[dict[str, Any]] = []
            for a, b in pairwise(inner_dates):
                raw = (
                    tuple(item for item in outer[0] if item.group_time < a),
                    tuple(item for item in outer[0] if a <= item.group_time < b),
                )
                inner, purged = purge_interval_partitions(
                    raw, ends=(a, b), information_embargo=embargo
                )
                inner_rows.append(
                    {
                        "train_ids": [item.sample_id for item in inner[0]],
                        "validation_ids": [item.sample_id for item in inner[1]],
                        "purged_ids": purged,
                        "status": "PROTOCOL_ONLY" if all(inner) else "INSUFFICIENT",
                    }
                )
            row["samples"] = {
                "train_ids": [item.sample_id for item in outer[0]],
                "test_ids": [item.sample_id for item in outer[1]],
                "purged_ids": removed,
                "inner": inner_rows,
                "effective_episodes": [len({item.episode_id for item in part}) for part in outer],
                "independent_time_blocks": None,
            }
            row["status"] = (
                "PROTOCOL_ONLY"
                if all(outer) and all(r["status"] == "PROTOCOL_ONLY" for r in inner_rows)
                else "INSUFFICIENT"
            )
        folds.append(row)
    payload = {
        "policy": "NESTED_EPISODE_INTERVAL_V2",
        "tier": "PREVIOUSLY_USED_DEVELOPMENT_NOT_HOLDOUT",
        "information_embargo_seconds": information_embargo_seconds,
        "outer_months": 42,
        "folds": folds,
        "statistical_sufficiency": "NOT_ESTABLISHED",
        "source_span_sha256": None
        if samples is None
        else canonical_sha256([item.model_dump(mode="json") for item in samples]),
        "rows_outside_development": None
        if samples is None
        else [
            item.sample_id
            for item in samples
            if not DEVELOPMENT_START <= item.group_time < OUTER_BOUNDARIES[-1]
        ],
    }
    return {**payload, "manifest_sha256": canonical_sha256(payload)}


def planned_fit_ids() -> tuple[str, ...]:
    base = tuple(
        f"MODEL:{model}:OUTER:{fold}:{role}"
        for model in ("LINEAR", "SHALLOW_TREE")
        for fold in range(1, 4)
        for role in ("INNER:1", "INNER:2", "INNER:3", "OUTER_REFIT")
    )
    uncertainty = tuple(
        f"MODEL:{model}:OUTER:{fold}:MEAN_BLOCK:{block}"
        for model in ("LINEAR", "SHALLOW_TREE")
        for fold in range(1, 4)
        for block in range(1, 21)
    )
    calibration = tuple(
        f"CALIBRATION:{model}:OUTER:{fold}"
        for model in ("LINEAR", "SHALLOW_TREE")
        for fold in range(1, 4)
    )
    return base + uncertainty + calibration


def registered_synthetic_fit_check[T](directory: Path, run_id: str, callback: Callable[[], T]) -> T:
    """Exercise real claim/error persistence with a synthetic callback, never fit a model."""
    with registered_run(  # noqa: SIM117 -- journal errors persist after the call guard exits.
        directory,
        run_id,
        planned_run_ids=planned_fit_ids(),
        bindings={
            "kind": "SYNTHETIC_CALLBACK_CHECK_NOT_A_REAL_FIT",
            "real_model_fits": 0,
            "real_calibration_fits": 0,
        },
    ):
        with zero_budget_guard(directory, Path.cwd(), dict.fromkeys(ZERO_BUDGETS, 0)):
            return callback()


def permit_ml_entry(*, risk_reduction: bool, model_available: bool, accepted: bool) -> bool:
    return risk_reduction or (model_available and accepted)


def validate_config(config: Mapping[str, Any]) -> None:
    match = re.fullmatch(r"alpha-r5-ml-contract-(\d{8})-v([1-9]\d*)", config["generation"])
    require(match is not None, "AQ-ML-GENERATION")
    if match is None:
        return
    require(
        config["output"] == f"artifacts/alpha_v5/{match[1]}_ml_contract_v{match[2]}", "AQ-ML-OUTPUT"
    )
    require(
        config["schema_version"] == "aegis-ml-contract-b6-v1"
        and config["scope"] == "B6_ML_PROTOCOL_AND_SYNTHETIC_CONTRACT_TESTS",
        "AQ-ML-SCOPE",
    )
    require(
        config["real_episode_inputs"] is None and config["real_training_authorized"] is False,
        "AQ-ML-REAL-TRAINING-NOT-AUTHORIZED",
    )
    require(
        config["future_fit_budget"]
        == {
            "model_fits": 144,
            "calibration_fits": 6,
            "inner_oof_mean_refits": 0,
            "authorized_now": 0,
        },
        "AQ-ML-FIT-BUDGET",
    )
    require(
        config["outer_boundaries"] == [value.strftime("%Y-%m-%d") for value in OUTER_BOUNDARIES],
        "AQ-ML-FIXED-SPLITS",
    )


def build_documents(sources: dict[str, Any]) -> Mapping[str, Any]:
    missing = {"status": "NOT_COLLECTED", "rows": None}
    return {
        "episode_ledger.json": {
            **missing,
            "basis": "COMPLETE_UNFILTERED_BASE_OPPORTUNITIES",
            "rejected_opportunities": "COUNTERFACTUAL_FROZEN_BASE",
            "independent_episodes": None,
        },
        "split_manifest.json": nested_split_manifest(None),
        "oof_provenance.json": {
            **missing,
            "required": [
                "model_and_transform_training_ids",
                "full_dependency_intervals",
                "episode_ids",
                "training_payload_hash",
                "split_hash",
                "model_hash",
                "label_contract_hash",
                "fit_and_prediction_clocks",
            ],
            "future_outer_refits_in_inner_oof": "FORBIDDEN",
        },
        "fit_and_calibration_log.json": {
            "real_model_fits": 0,
            "real_calibration_fits": 0,
            "future_slots": planned_fit_ids(),
            "extra_inner_calibration_slots": 0,
            "inner_mean_uncertainty": "DISABLED_NO_BUDGET",
            "future_weights_and_update_program": None,
        },
        "trial_registry_status.json": {
            "complete_history": "UNKNOWN",
            "recovered_prior_engineering_errors": "RETAINED_IN_IMMUTABLE_PRIOR_GENERATIONS",
            "independent_return_candidates": None,
            "engineering_errors_are_independent_return_trials": False,
        },
        "outer_metrics.json": {
            **missing,
            "required": [
                "brier",
                "log_loss",
                "calibration",
                "oof_coverage_width",
                "acceptance_rate",
                "missed_positive_opportunities",
                "avoided_negative_opportunities",
                "net_pnl_delta",
                "tail_delta",
                "same_risk_no_ml_control",
                "constant_probability_control",
                "holm_adjusted_outer_comparisons",
            ],
            "actual_outer_results": None,
        },
        "statistical_evidence.json": {
            "DSR": {
                "status": "INSUFFICIENT",
                "probability": None,
                "reason": "MISSING_COMPLETE_TRIAL_HISTORY_AND_DEPENDENCE_EVIDENCE",
            },
            "PBO": {
                "status": "INSUFFICIENT",
                "probability": None,
                "reason": "NO_REGISTERED_SELECTION_MATRIX",
            },
            "predictive_distribution": "NOT_COLLECTED",
            "conditional_mean_uncertainty": "NOT_IDENTIFIED",
            "exact_nonstationary_conformal_coverage": False,
        },
        "candidate_freeze_draft.json": {
            "status": "NOT_ELIGIBLE",
            "candidate": None,
            "data_code_risk_cost_capacity_hashes": None,
            "allowed_training_update_program": None,
            "holdout_path": None,
            "orders_authorized": False,
        },
        "evidence_gaps.json": {
            "pit_quality": sources["b2_safety"]["strict_data_quality"],
            "gaps": [
                "REAL_PIT_LINEAGE",
                "VERIFIED_EXECUTION_AND_SHARED_LEDGER",
                "COMPLETE_MATURE_EPISODE_SET",
                "INDEPENDENT_TIME_BLOCK_SUFFICIENCY",
                "COMPLETE_TRIAL_HISTORY",
                "FROZEN_MODEL_CALIBRATION_SELECTION_RULE",
                "SEPARATE_REAL_FIT_AUTHORIZATION",
                "UNUSED_TWELVE_MONTH_HOLDOUT",
            ],
            "promotion_admitted": False,
        },
        "report.md": """# B6 ML、episode 与统计契约

**NO_PROVEN_ALPHA / CASH；ML、纸面、实盘和订单继续关闭。**

新增完整基础机会集的 episode 包装，复用可执行 t+1、双腿成本与路径标签；被拒绝机会保留 COUNTERFACTUAL 标记。严格分割按完整特征依赖、标签可用时间、同时间资产组和 episode 清除所有后续边界重叠，记录 purge 和不成熟尾部。旧调用和默认输出契约保留。

三个 outer 块固定为 2022-04 至 2023-06、2023-06 至 2024-08、2024-08 至 2025-10，共 42 个月，最后九个月各三块 inner 验证。仍是已使用开发区间；缺真实标签时只输出日期协议，不能宣称有三个有效统计 fold。

OOF 元数据绑定每个训练、转换和预测的样本、episode、时钟及哈希。校准入口使用对齐的 OOF 预测；模型不可用不能否决风险减仓。预测分布与均值估计不确定性分别记录；conformal 不保证非平稳市场精确覆盖，30 行代码门槛不代表有效样本充分。

未来拟议 144 模型 fit、6 校准 fit 全部列出；当前实际均为 0。内层额外校准和 OOF 均值重拟合没有预算，保持关闭。合成 callback 仅检查原 registry 的失败消耗，不是实际模型拟合。真实训练入口仍未启用。

DSR 缺全试验史、频率/峰度/依赖依据时返回 INSUFFICIENT 和 null；PBO 使用相同登记 score、全部候选和 mid-rank/tie 权重，不因数组顺序造优胜。旧统计实现只保留历史复现兼容，不给新准入证据使用。

episode 实证、outer 指标、OOF 覆盖、经济增量与候选冻结全部 NOT_COLLECTED；实际历史回放、真实模型/校准 fit、最终留出和订单均为 0。本批工程通过不代表 ML 有效或可交易。
""",
    }
