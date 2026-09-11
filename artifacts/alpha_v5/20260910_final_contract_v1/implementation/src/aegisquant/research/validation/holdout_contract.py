"""B7 metadata, explicit access authority and independent-review handoff contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256, safe_relative_path
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.research.experiments.ledger import PromotionDecision
from aegisquant.research.validation.evidence_contract import require

FILES = (
    "src/aegisquant/research/validation/persistent_holdout.py",
    "src/aegisquant/research/validation/holdout.py",
    "src/aegisquant/research/validation/experiment_registry.py",
    "tests/integration/test_walkforward_holdout_firewall.py",
    "src/aegisquant/research/validation/holdout_contract.py",
    "scripts/run_alpha_v5_final_holdout.py",
    "configs/research/alpha_v5_final_holdout_contract.yaml",
    "tests/alpha_v5/test_holdout_contract.py",
    "docs/research/alpha_v5_final_holdout_contract.md",
)
ANCHOR_PATH = "state/final_holdout_anchor.json"
CLAIM_PATH = "state/final_holdout_access_claim.json"
ACCESS_JOURNAL_PATH = "state/final_holdout_access_events.jsonl"
ACCESS_LOCK_PATH = "state/final_holdout_access.lock"


class HoldoutDataSeal(DomainModel):
    semantic_dataset_id: str = Field(min_length=1)
    dataset_sha256: str
    content_bytes: int = Field(gt=0)
    sealed_relative_path: str
    registered_aliases: tuple[str, ...] = ()
    start: UtcDateTime
    end_exclusive: UtcDateTime
    source_material_start: UtcDateTime
    source_material_end_exclusive: UtcDateTime
    previously_used_through: UtcDateTime
    source_was_previously_accessed: bool | None
    unused_and_coverage_evidence_sha256: str
    independent_metadata_verification: Literal["VERIFIED", "UNKNOWN"]
    lineage_source_hashes: tuple[str, ...]
    derived_artifact_hashes: tuple[str, ...] = ()
    verification_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_seal(self) -> HoldoutDataSeal:
        for digest in (
            self.dataset_sha256,
            self.unused_and_coverage_evidence_sha256,
            *self.lineage_source_hashes,
            *self.derived_artifact_hashes,
        ):
            ensure_sha256(digest, field_name="sealed data evidence")
        if not self.lineage_source_hashes or len(set(self.lineage_source_hashes)) != len(
            self.lineage_source_hashes
        ):
            raise ValueError("sealed data requires unique source lineage hashes")
        for name in (self.sealed_relative_path, *self.registered_aliases):
            if safe_relative_path(name) != name:
                raise ValueError("sealed paths must be normalized relative paths")
        if PurePosixPath(safe_relative_path(self.sealed_relative_path)).parts[:2] != (
            "data",
            "final_holdout",
        ):
            raise ValueError("sealed data must use the protected final_holdout data root")
        if (
            not self.semantic_dataset_id.strip()
            or self.semantic_dataset_id != self.semantic_dataset_id.strip()
        ):
            raise ValueError("semantic dataset identity cannot be blank or padded")
        if (
            not self.start < self.end_exclusive
            or not self.source_material_start < self.source_material_end_exclusive
        ):
            raise ValueError("invalid sealed data interval")
        return self

    @property
    def protected_hashes(self) -> frozenset[str]:
        return frozenset(
            (self.dataset_sha256, *self.lineage_source_hashes, *self.derived_artifact_hashes)
        )


class HoldoutProjectAnchor(DomainModel):
    schema_version: Literal["aegis-project-holdout-anchor-v1"] = "aegis-project-holdout-anchor-v1"
    project_id: str = Field(min_length=1)
    dataset: HoldoutDataSeal
    freeze_id: str
    operator_authorization_sha256: str
    journal_genesis_entry_sha256: str
    independent_storage_attestation_sha256: str
    created_at: UtcDateTime
    maximum_data_claims: Literal[1] = 1
    approved_purpose: Literal["ONE_FINAL_EVALUATION_FROZEN_COMPARISON_FAMILY"] = (
        "ONE_FINAL_EVALUATION_FROZEN_COMPARISON_FAMILY"
    )

    @model_validator(mode="after")
    def validate_hashes(self) -> HoldoutProjectAnchor:
        for digest in (
            self.freeze_id,
            self.operator_authorization_sha256,
            self.journal_genesis_entry_sha256,
            self.independent_storage_attestation_sha256,
        ):
            ensure_sha256(digest, field_name="project anchor")
        return self

    @property
    def anchor_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class HoldoutAccessAuthorization(DomainModel):
    """An explicit, separately approved authority record; metadata is not self-authorization."""

    project_id: str = Field(min_length=1)
    anchor_sha256: str
    freeze_id: str
    operator_authorization_sha256: str
    generation: str = Field(min_length=1)
    authorized_at: UtcDateTime
    purpose: Literal["FINAL_EVALUATION"] = "FINAL_EVALUATION"
    allow_data_read: Literal[True] = True

    @model_validator(mode="after")
    def validate_hashes(self) -> HoldoutAccessAuthorization:
        for digest in (self.anchor_sha256, self.freeze_id, self.operator_authorization_sha256):
            ensure_sha256(digest, field_name="holdout authority")
        return self


FINAL_GATE_NAMES = frozenset(
    {
        "original_profitability_and_stability_gates",
        "holm_corrected_incremental_evidence",
        "same_risk_no_ml_and_cash_comparisons",
        "verified_pit_data_and_complete_trials",
        "execution_and_capacity",
        "funded_shared_ledger_and_tail_risk",
        "frozen_model_weights_and_update_program",
        "unused_twelve_month_claim_and_immutable_report",
    }
)


def independent_review_handoff(
    gates: Mapping[str, bool | None], *, immutable_report_sha256: str | None
) -> dict[str, Any]:
    """Even a complete pass can only request independent review, never promote or trade."""
    if frozenset(gates) != FINAL_GATE_NAMES:
        raise ValueError("final evaluation must retain every frozen gate")
    if immutable_report_sha256 is not None:
        ensure_sha256(immutable_report_sha256, field_name="immutable final report")
    ready = all(value is True for value in gates.values()) and immutable_report_sha256 is not None
    return {
        "promotion_decision": PromotionDecision.HOLD
        if ready or any(value is None for value in gates.values())
        else PromotionDecision.REJECT,
        "status": "INDEPENDENT_REVIEW_REQUIRED" if ready else "NO_PROVEN_ALPHA",
        "gates": dict(gates),
        "immutable_report_sha256": immutable_report_sha256,
        "independent_review_completed": False,
        "production_policy": "CASH",
        "production_ml_enabled": False,
        "paper_trading_admitted": False,
        "live_trading": False,
        "order_submission_enabled": False,
    }


def validate_config(config: Mapping[str, Any]) -> None:
    match = re.fullmatch(r"alpha-r5-final-contract-(\d{8})-v([1-9]\d*)", config["generation"])
    require(match is not None, "AQ-FINAL-CONTRACT-GENERATION")
    if match is None:
        return
    require(
        config["output"] == f"artifacts/alpha_v5/{match[1]}_final_contract_v{match[2]}",
        "AQ-FINAL-CONTRACT-OUTPUT",
    )
    require(
        config["schema_version"] == "aegis-final-contract-b7-v1"
        and config["scope"] == "B7_ANCHORED_FIREWALL_AND_SYNTHETIC_CONTRACT_TESTS",
        "AQ-FINAL-CONTRACT-SCOPE",
    )
    require(
        all(
            config[key] is None
            for key in (
                "eligible_unused_dataset",
                "actual_project_anchor",
                "actual_freeze_manifest",
                "actual_access_authorization",
            )
        ),
        "AQ-FINAL-CONTRACT-REAL-INPUTS-NOT-AUTHORIZED",
    )
    require(
        config["future_access_budget"]
        == {
            "unique_data_claims": 1,
            "authorized_now": 0,
            "failure_consumes_claim": True,
            "generation_reset_allowed": False,
        },
        "AQ-FINAL-CONTRACT-ACCESS-BUDGET",
    )


def build_documents(sources: dict[str, Any]) -> Mapping[str, Any]:
    gates = dict.fromkeys(FINAL_GATE_NAMES, None)
    batches = [
        {
            "batch": "B0/B1",
            "engineering": "COMPLETED",
            "pure_tests": 48,
            "real_evidence": "RAW_BUNDLES_AND_TRACES_INCOMPLETE",
        },
        {
            "batch": "B2",
            "engineering": "COMPLETED",
            "pure_tests": 49,
            "real_evidence": "FAILED_CLOSED_INSUFFICIENT_PIT_EVIDENCE",
            "quality_jobs": 1,
        },
        {
            "batch": "B3",
            "engineering": "COMPLETED",
            "pure_tests": 44,
            "real_evidence": "MATRIX_AND_INCREMENTAL_STATISTICS_NOT_COLLECTED",
        },
        {
            "batch": "B4",
            "engineering": "COMPLETED",
            "pure_tests": 85,
            "real_evidence": "EXECUTION_CALIBRATION_NOT_COLLECTED",
        },
        {
            "batch": "B5",
            "engineering": "COMPLETED",
            "pure_tests": 100,
            "real_evidence": "JOINT_PORTFOLIO_REPLAYS_NOT_COLLECTED",
        },
        {
            "batch": "B6",
            "engineering": "COMPLETED",
            "pure_tests": 48,
            "real_evidence": "REAL_FITS_AND_OUTER_RESULTS_NOT_COLLECTED",
        },
        {
            "batch": "B7",
            "engineering": "CONTRACT_REPORT_WITH_SOURCE_BOUND_TEST_RECEIPTS",
            "pure_tests": "SEE_SOURCE_AND_VERSION_BINDINGS",
            "real_evidence": "NO_ELIGIBLE_HOLDOUT_OR_INDEPENDENT_ADMISSION_REVIEW",
        },
    ]
    return {
        "holdout_eligibility.json": {
            "status": "NO_ELIGIBLE_UNUSED_TWELVE_MONTH_DATASET",
            "dataset": None,
            "actual_anchor": None,
            "actual_freeze": None,
            "actual_authorization": None,
            "actual_content_accesses": 0,
            "actual_data_claims": 0,
            "minimum_months": 12,
            "pit_quality": sources["b2_safety"]["strict_data_quality"],
        },
        "access_ledger_status.json": {
            "status": "NO_REAL_ACCESS_REGISTRY_CREATED",
            "actual_data_access_ledger": None,
            "fixed_anchor_relative_path": ANCHOR_PATH,
            "fixed_claim_relative_path": CLAIM_PATH,
            "fixed_shared_journal_relative_path": ACCESS_JOURNAL_PATH,
            "caller_directory_is_claim_key": False,
            "candidate_and_generation_are_claim_keys": False,
            "loader_errors_consume_claim": True,
            "storage_limit": "APPLICATION_GATE_REQUIRES_INDEPENDENT_APPEND_ONLY_STORAGE_ATTESTATION;NOT_AN_OS_SANDBOX",
        },
        "freeze_component_contract.json": {
            "status": "NOT_ELIGIBLE",
            "candidate": None,
            "original_components_preserved": True,
            "additional_components": [
                "data_lineage",
                "risk",
                "rules",
                "capacity",
                "statistics",
                "comparison_family",
                "complete_trials",
                "weights",
                "training_update_program",
                "independent_preaccess_review",
            ],
            "missing_extension_blocks_read": True,
        },
        "independent_review.json": independent_review_handoff(gates, immutable_report_sha256=None),
        "all_batches_status.json": {
            "batches": batches,
            "test_counts_are_per_batch_and_overlap": True,
            "research_conclusion": "NO_PROVEN_ALPHA",
            "authorized_engineering_scope": "B0_THROUGH_B7",
            "real_research_acceptance": "NOT_COMPLETED_MISSING_DATA_AND_SEPARATE_AUTHORIZATION",
            "live_or_order_authorization": False,
        },
        "evidence_gaps.json": {
            "gaps": [
                "UNMODIFIED_RAW_BUNDLE_AND_TRACE_LINKAGE",
                "REAL_PIT_UNIVERSE_AND_LIQUIDITY_RULES",
                "EXECUTION_FEE_DEPTH_LATENCY_CALIBRATION",
                "JOINT_SHARED_CASH_REPLAY",
                "MATURE_UNFILTERED_EPISODES_AND_COMPLETE_TRIAL_HISTORY",
                "SEPARATE_REAL_REPLAY_FIT_AUTHORIZATION",
                "UNUSED_CONTINUOUS_TWELVE_MONTH_HOLDOUT",
                "INDEPENDENT_STORAGE_AND_ADMISSION_REVIEW",
            ],
            "unknown_history": "UNKNOWN_NOT_ZERO",
            "failure_or_uncertainty": "NO_PROVEN_ALPHA",
            "holdout_repair_and_retry": "FORBIDDEN",
        },
        "report.md": """# B7 一次性留出契约与整改工程交付

**NO_PROVEN_ALPHA / CASH；ML、纸面准入、实盘、订单全部关闭。**

本批为最后的工程契约：全项目使用同一个固定位置的 claim 和共享访问日志，候选、路径和 generation 不产生新次数。已有入口在读取前核验项目锚点、明确授权、完整冻结、数据身份和未使用十二个月条件；无锚点、无扩展冻结、未知来源或已用源尾部都拒绝。claim 以 exclusive create 和 fsync 落盘后才允许读取，loader 异常、内容 hash/长度不符仍消耗 claim；缺失或损坏已有日志不能自动初始化新次数。

读取范围守卫覆盖声明的原始、别名及派生数据；开发加载器按登记的 hash/完整血缘拒绝缓存、预览和特征间接引用。应用级守卫不能替代操作系统权限或独立不可回滚存储；真实准入仍要求独立存储证明。当前没有创建真实锚点，也没有读取、预览或 hash 真实最终留出内容，所有访问测试仅使用临时合成文件。

原冻结 manifest 增加版本化的风险、规则、容量、统计、比较族、试验史、模型权重、定期更新程序和独立预审绑定。即使未来所有门槛通过，也只交独立准入评审，不自动改模型别名或打开订单。失败、不确定、读取异常都不能回到同一留出改特征再试。

B0/B1 至 B7 的当前授权工程与必要合成验证已依次交付，各批原始失败记录和封存证据保留，详见 all_batches_status.json 与各自 manifest。每批测试数量有重叠，不能相加当作独立测试总数。本批精确检查数量见 source_and_version_bindings.json。

完整研究验收尚未完成：真实 PIT、费用/规则/盘口/延迟、共享现金历史回放、成熟机会及全试验史、真实 OOF/outer 和未使用留出仍缺证据或后批授权。现有已用历史不能改名为最终留出。当前历史策略回放、真实收益模型拟合、真实校准拟合、最终留出读取和实盘订单五项累计新增均为 0。
""",
    }
