"""Generate or verify deterministic P17 provider bake-off evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final, cast

from aegisquant.data.models import ProviderStatus
from aegisquant.data.provider_registry import ProviderRegistry
from aegisquant.domain.identifiers import ProviderId
from aegisquant.research.provider_bakeoff.catalog import (
    load_candidate_catalog,
    load_trial_plans,
)
from aegisquant.research.provider_bakeoff.evaluation import (
    calculate_news_metrics,
    enforce_primary_source_limit,
    evaluate_candidate,
    fallback_to_free_baseline,
    require_official_trading_fact,
)
from aegisquant.research.provider_bakeoff.models import (
    EvidenceState,
    NewsDetection,
    NewsReferenceEvent,
    PriceDisclosure,
    ProviderCandidate,
    ProviderClass,
    SourceAuthority,
    TradingFactRecord,
    TrialBudget,
    TrialCriteria,
    TrialMeasurement,
    TrialPlan,
)

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT_ROOT: Final = ROOT / "reports/data/provider_bakeoff"
CANDIDATES_PATH: Final = ROOT / "configs/provider_bakeoff/candidates.json"
PLANS_PATH: Final = ROOT / "configs/provider_bakeoff/trial_plans.json"
CONTEXT_PATH: Final = ROOT / "configs/provider_bakeoff/context.json"
OUTPUTS: Final = {
    "desk_review": OUTPUT_ROOT / "SOURCE_DESK_REVIEW.json",
    "trial_requests": OUTPUT_ROOT / "TRIAL_REQUESTS.json",
    "scorecard": OUTPUT_ROOT / "PROVIDER_SCORECARD.json",
    "decisions": OUTPUT_ROOT / "PROVIDER_DECISIONS.json",
    "conditional": OUTPUT_ROOT / "CONDITIONAL_CANDIDATES.json",
    "crosscheck": OUTPUT_ROOT / "OFFICIAL_CROSSCHECK.json",
    "ablation": OUTPUT_ROOT / "ABLATION_EVIDENCE.json",
    "news": OUTPUT_ROOT / "NEWS_BAKEOFF_EVIDENCE.json",
    "degradation": OUTPUT_ROOT / "DEGRADATION_EVIDENCE.json",
    "registry": OUTPUT_ROOT / "REGISTRY_GATE_EVIDENCE.json",
    "negative": OUTPUT_ROOT / "NEGATIVE_RESULTS.json",
    "recommendation": OUTPUT_ROOT / "PROCUREMENT_RECOMMENDATION.md",
    "ai_trader": OUTPUT_ROOT / "AI_TRADER_REFERENCE_REVIEW.md",
}


def _render_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_context() -> dict[str, object]:
    payload = cast("object", json.loads(CONTEXT_PATH.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise TypeError("P17 context must be a JSON object")
    return cast("dict[str, object]", payload)


def _fixture_candidate(provider_id: str) -> ProviderCandidate:
    return ProviderCandidate(
        provider_id=ProviderId(provider_id),
        provider_name=provider_id,
        provider_class=ProviderClass.MARKET_HISTORY,
        comparison_group="fixture_market",
        official_sources=("https://example.invalid/p17-fixture-contract",),
        credentials_required=False,
        price_disclosure=PriceDisclosure.CONTACT_SALES,
        license_review_complete=True,
        evidence_state=EvidenceState.TRIAL_COMPLETE,
        status=ProviderStatus.TRIAL,
        runtime_dependency=False,
        official_fact_authority=False,
        desk_review_facts=("deterministic fixture only",),
        unresolved_questions=(),
    )


def _fixture_plan(*provider_ids: str) -> TrialPlan:
    return TrialPlan(
        trial_id="p17_deterministic_fixture_trial",
        provider_ids=tuple(ProviderId(item) for item in provider_ids),
        hypothesis="验证 P17 评分门自身能接受净增量并拒绝负结果",
        datasets=("deterministic_fixture",),
        asset_scope=("fixture-only",),
        equal_research_budget=True,
        official_crosscheck_sources=("fixture_official",),
        budget=TrialBudget(
            proposed_max_cost_usd=Decimal("10"),
            approved_max_cost_usd=Decimal("10"),
            user_budget_approved=True,
            approval_reference="fixture-only-approval",
            max_calls=100,
            max_storage_gb=Decimal("1"),
            max_duration_days=2,
        ),
        criteria=TrialCriteria(
            min_oos_observations=100,
            min_official_match_rate=Decimal("0.99"),
            min_completeness_rate=Decimal("0.99"),
            max_gap_rate=Decimal("0.01"),
            max_p95_latency_ms=Decimal("1000"),
            min_net_incremental_bps=Decimal("2"),
            max_adjusted_p_value=Decimal("0.05"),
            max_operations_minutes_per_day=Decimal("10"),
        ),
        activated=True,
        stop_conditions=("fixture gate complete",),
    )


def _fixture_measurement(provider_id: str, *, passing: bool) -> TrialMeasurement:
    return TrialMeasurement(
        provider_id=ProviderId(provider_id),
        oos_observations=1000,
        official_match_rate=Decimal("0.999"),
        completeness_rate=Decimal("0.999"),
        gap_rate=Decimal("0.001"),
        p95_latency_ms=Decimal("100"),
        baseline_net_bps=Decimal("10"),
        augmented_net_bps=Decimal("18") if passing else Decimal("12"),
        incremental_data_cost_bps=Decimal("1"),
        incremental_operations_cost_bps=Decimal("1"),
        incremental_trading_cost_bps=Decimal("1"),
        adjusted_p_value=Decimal("0.01") if passing else Decimal("0.2"),
        operations_minutes_per_day=Decimal("2"),
        total_cost_usd=Decimal("8"),
        license_approved=True,
        point_in_time_verified=True,
        negative_result_retained=True,
    )


def _real_decisions() -> tuple[dict[str, object], ...]:
    catalog = load_candidate_catalog(CANDIDATES_PATH)
    plans = load_trial_plans(PLANS_PATH)
    plan_by_provider = {
        str(provider_id): plan for plan in plans.plans for provider_id in plan.provider_ids
    }
    if len(plan_by_provider) != len(catalog.candidates):
        raise ValueError("every paid candidate must belong to exactly one trial plan")
    records = tuple(
        evaluate_candidate(
            candidate=candidate,
            plan=plan_by_provider[str(candidate.provider_id)],
            measurement=None,
            condition_satisfied=str(candidate.provider_id) != "databento",
        )
        for candidate in catalog.candidates
    )
    enforce_primary_source_limit(records)
    return tuple(cast("dict[str, object]", item.model_dump(mode="json")) for item in records)


def _news_fixture() -> tuple[dict[str, object], dict[str, object]]:
    start = datetime(2026, 9, 2, tzinfo=UTC)
    references = tuple(
        NewsReferenceEvent(
            event_id=f"official-{index}",
            official_available_time=start + timedelta(minutes=index * 10),
            risk_relevant=index in {1, 3},
        )
        for index in range(1, 5)
    )
    detections = (
        NewsDetection(
            detection_id="fixture-d1",
            matched_official_event_id="official-1",
            available_time=references[0].official_available_time - timedelta(seconds=60),
            story_fingerprint="fixture-story-a",
        ),
        NewsDetection(
            detection_id="fixture-d2",
            matched_official_event_id="official-2",
            available_time=references[1].official_available_time + timedelta(seconds=30),
            story_fingerprint="fixture-story-b",
        ),
        NewsDetection(
            detection_id="fixture-d3",
            matched_official_event_id="official-2",
            available_time=references[1].official_available_time + timedelta(seconds=45),
            story_fingerprint="fixture-story-b",
        ),
        NewsDetection(
            detection_id="fixture-d4",
            matched_official_event_id=None,
            available_time=start,
            story_fingerprint="fixture-story-c",
        ),
    )
    metrics = calculate_news_metrics(references=references, detections=detections)
    return (
        cast("dict[str, object]", metrics.model_dump(mode="json")),
        {
            "official_reference_ids": [item.event_id for item in references],
            "provider_detection_ids": [item.detection_id for item in detections],
        },
    )


def _recommendation(decisions: tuple[dict[str, object], ...]) -> str:
    rows = [
        "# P17 采购建议",
        "",
        "## 结论",
        "",
        "**NO_PURCHASE：当前不采购、不批准、不接入任何付费 Provider。**",
        "",
        "原因不是候选一定没价值，而是尚无真实试用、OOS 消融、许可确认和运维证据。桌面评审与",
        "厂商营销字段不能代替这些证据；用户未批准任何预算，批准支出上限为 0 美元。",
        "",
        "## 候选决策",
        "",
        "| Provider | Group | Decision | Evidence |",
        "|---|---|---|---|",
    ]
    rows.extend(
        f"| {item['provider_id']} | {item['comparison_group']} | {item['decision']} | "
        f"{item['evidence_state']} |"
        for item in decisions
    )
    rows.extend(
        (
            "",
            "## 重新启动试用的硬条件",
            "",
            "1. 用户先批准对应 `TRIAL_REQUESTS.json` 中的范围、最长时长和成本硬上限。",
            "2. 凭据仅由用户写入本地秘密库；聊天、Markdown、配置和报告只记录引用状态。",
            "3. 真实 Provider 数据必须按 available_time 保存，并与官方交易所或官方发布源交叉核验。",
            "4. 只有 OOS 净增量、许可、成本和运维门全部通过，才可在同类中批准最多一家。",
            "5. 任一 Provider 停服必须退回免费基线；第三方聚合永不替代官方交易事实。",
            "",
            "正式验收仍延期；未执行 12h/24h，也未生成 P17 `ACCEPTANCE.md`。",
        )
    )
    return "\n".join(rows) + "\n"


def _ai_trader_review() -> str:
    return """# HKUDS/AI-Trader 参考复核

- 复核日期：2026-09-02
- 官方仓库：https://github.com/HKUDS/AI-Trader
- 使用方式：`REFERENCE_ONLY`
- 外部脚本执行：0
- 外部 Skill 加载：0
- 平台注册：0
- 代码复制：0
- 真实账户或 Live 连接：0

## 可借鉴的高层思想

1. Paper 环境先于真实交易，且实验/挑战应保留暴露和结果记录。
2. Web 服务与后台 worker 分离，避免研究任务阻塞用户接口。
3. 信号、讨论、实验和表现应有可追踪实体，而不是只留一条收益截图。

这些思想已经由 AegisQuant 自身的 Paper/Shadow、事件溯源、实验账本、运行监督和只读工作台契约实现；
没有复制 AI-Trader 代码，也没有把它变成运行时依赖。

## 明确拒绝的边界

- 不执行 README 中“一条消息读取远程 Skill 并注册平台”的流程。
- 不启用 copy trading、broker sync、agent direct trading 或任何 Live 自动化。
- 不把社区排名、Star、宣传收益或 mark-to-market 排名当成策略有效性证据。
- 不向第三方上传本项目数据、账户信息、策略、密钥或研究结果。

## 许可证结论

README 徽章声称 MIT，但复核时仓库根目录没有可读取的 `LICENSE` 文件，对应 raw URL 返回 404。
因此许可证不能仅凭徽章视为已核验：本阶段只保留思想级引用，不复制或派生其代码。若未来出现精确
代码复用需求，必须先固定 commit、取得完整许可证文本并完成依赖与安全审计。
"""


def build_payloads() -> dict[str, object]:
    catalog = load_candidate_catalog(CANDIDATES_PATH)
    plan_document = load_trial_plans(PLANS_PATH)
    context = _load_context()
    decisions = _real_decisions()
    approved = [item for item in decisions if item["decision"] == "APPROVE"]

    plan_by_provider = {
        str(provider_id): plan for plan in plan_document.plans for provider_id in plan.provider_ids
    }
    dimensions = (
        "license",
        "historical_coverage",
        "first_publish_latency",
        "revisions_and_deletions",
        "gaps_and_completeness",
        "languages",
        "price",
        "operations",
        "oos_net_increment",
    )
    scorecards = [
        {
            "provider_id": str(item.provider_id),
            "comparison_group": item.comparison_group,
            "measurement_status": "NOT_TESTED",
            "aggregate_score": None,
            "dimensions": {dimension: None for dimension in dimensions},
            "marketing_claims_scored": False,
            "official_source_count": len(item.official_sources),
        }
        for item in catalog.candidates
    ]

    passing_id = "fixture_passing"
    failing_id = "fixture_negative"
    fixture_plan = _fixture_plan(passing_id, failing_id)
    fixture_pass = evaluate_candidate(
        candidate=_fixture_candidate(passing_id),
        plan=fixture_plan,
        measurement=_fixture_measurement(passing_id, passing=True),
    )
    fixture_fail = evaluate_candidate(
        candidate=_fixture_candidate(failing_id),
        plan=fixture_plan,
        measurement=_fixture_measurement(failing_id, passing=False),
    )
    news_metrics, news_fixture_ids = _news_fixture()

    baseline = ("official-binance", "official-okx", "official-bybit")
    degraded = fallback_to_free_baseline(
        baseline_record_ids=baseline,
        candidate_record_ids=("paid-fixture",),
        candidate_approved=True,
        provider_available=False,
    )
    unapproved = fallback_to_free_baseline(
        baseline_record_ids=baseline,
        candidate_record_ids=("paid-fixture",),
        candidate_approved=False,
        provider_available=True,
    )

    aggregator_rejected = False
    try:
        require_official_trading_fact(
            TradingFactRecord(
                fact_id="fixture-aggregate-fill",
                fact_type="fill",
                source_authority=SourceAuthority.THIRD_PARTY_AGGREGATOR,
                source_id="fixture-paid-provider",
            )
        )
    except PermissionError:
        aggregator_rejected = True
    official = require_official_trading_fact(
        TradingFactRecord(
            fact_id="fixture-official-fill",
            fact_type="fill",
            source_authority=SourceAuthority.OFFICIAL_EXCHANGE,
            source_id="binance_public",
        )
    )

    runtime = ProviderRegistry.from_yaml(ROOT / "data/catalogs/provider_registry.yaml")
    paid_ids = {str(item.provider_id) for item in catalog.candidates}
    registered_paid = [
        str(item.provider_id)
        for item in runtime.document.providers
        if str(item.provider_id) in paid_ids
    ]
    approved_paid = [
        str(item.provider_id)
        for item in runtime.document.providers
        if str(item.provider_id) in paid_ids and item.status is ProviderStatus.APPROVED
    ]

    desk_review = {
        "schema_version": "p17-source-desk-review-v1",
        "reviewed_at_utc": catalog.reviewed_at_utc.isoformat().replace("+00:00", "Z"),
        "candidate_config_sha256": _sha256(CANDIDATES_PATH),
        "candidate_count": len(catalog.candidates),
        "official_source_count": sum(len(item.official_sources) for item in catalog.candidates),
        "candidates": [
            {
                "provider_id": str(item.provider_id),
                "provider_name": item.provider_name,
                "provider_class": item.provider_class.value,
                "comparison_group": item.comparison_group,
                "official_sources": list(item.official_sources),
                "desk_review_facts": list(item.desk_review_facts),
                "unresolved_questions": list(item.unresolved_questions),
                "price_disclosure": item.price_disclosure.value,
                "public_monthly_price_usd": (
                    str(item.public_monthly_price_usd)
                    if item.public_monthly_price_usd is not None
                    else None
                ),
                "license_review_complete": item.license_review_complete,
                "evidence_state": item.evidence_state.value,
            }
            for item in catalog.candidates
        ],
        "marketing_material_is_purchase_evidence": False,
        "external_code_executed": False,
    }
    trial_requests = {
        "schema_version": "p17-trial-requests-v1",
        "trial_plan_config_sha256": _sha256(PLANS_PATH),
        "trial_count": len(plan_document.plans),
        "plans": [item.model_dump(mode="json") for item in plan_document.plans],
        "proposed_max_cost_usd": str(
            sum(
                (item.budget.proposed_max_cost_usd for item in plan_document.plans),
                Decimal("0"),
            )
        ),
        "approved_max_cost_usd": "0",
        "activated_trial_count": sum(item.activated for item in plan_document.plans),
        "real_provider_network_requests_performed": context[
            "real_provider_network_requests_performed"
        ],
        "credentials_requested_or_received": False,
        "plaintext_secrets_written": False,
    }
    scorecard = {
        "schema_version": "p17-provider-scorecard-v1",
        "dimensions": list(dimensions),
        "scorecards": scorecards,
        "numeric_scores_assigned_without_trial": 0,
        "feature_importance_used_as_procurement_evidence": False,
    }
    decision_payload: dict[str, object] = {
        "schema_version": "p17-provider-decisions-v1",
        "procurement_decision": "NO_PURCHASE",
        "decisions": list(decisions),
        "approved_provider_count": len(approved),
        "approved_by_group": {},
        "same_class_primary_limit": 1,
        "sunk_cost_used_as_reason": False,
        "real_trial_evidence_count": len(
            cast("list[object]", context["real_provider_trial_artifacts"])
        ),
    }
    conditional = {
        "schema_version": "p17-conditional-candidates-v1",
        "provider_id": "databento",
        "condition": plan_by_provider["databento"].condition,
        "approved_cross_asset_or_cme_hypothesis_ids": context[
            "approved_cross_asset_or_cme_hypothesis_ids"
        ],
        "condition_satisfied": False,
        "decision": "NOT_APPLICABLE",
        "network_requests_performed": 0,
    }
    crosscheck = {
        "schema_version": "p17-official-crosscheck-v1",
        "fixture_only": True,
        **news_fixture_ids,
        "matched_event_count": news_metrics["matched_event_count"],
        "third_party_trading_fact_rejected": aggregator_rejected,
        "official_trading_fact_accepted": official.fact_id == "fixture-official-fill",
        "third_party_replaces_official_trading_fact": False,
        "real_provider_claim_made": False,
    }
    ablation: dict[str, object] = {
        "schema_version": "p17-ablation-evidence-v1",
        "fixture_only": True,
        "equal_research_budget": True,
        "feature_importance_used": False,
        "passing_gate": fixture_pass.model_dump(mode="json"),
        "negative_gate": fixture_fail.model_dump(mode="json"),
        "real_provider_trial_count": 0,
        "real_provider_incremental_value_claims": [],
    }
    news = {
        "schema_version": "p17-news-bakeoff-evidence-v1",
        "fixture_only": True,
        "metrics": news_metrics,
        "required_metrics": [
            "recall",
            "false_alert_rate",
            "mean_lead_time_seconds",
            "duplicate_rate",
            "risk_coverage_rate",
        ],
        "real_provider_comparison_performed": False,
    }
    degradation = {
        "schema_version": "p17-degradation-evidence-v1",
        "provider_outage": degraded.model_dump(mode="json"),
        "unapproved_provider": unapproved.model_dump(mode="json"),
        "free_baseline_record_ids": list(baseline),
        "free_baseline_survives_provider_loss": degraded.selected_record_ids == baseline,
        "unpaid_provider_runtime_hard_dependency": False,
    }
    registry = {
        "schema_version": "p17-registry-gate-evidence-v1",
        "paid_candidate_count": len(paid_ids),
        "paid_candidates_registered_at_runtime": sorted(registered_paid),
        "paid_candidates_approved_at_runtime": sorted(approved_paid),
        "approved_paid_count": len(approved_paid),
        "real_trial_evidence_count": 0,
        "license_approved_paid_count": 0,
        "gate_status": "passed_no_paid_provider_approved",
    }
    negative = {
        "schema_version": "p17-negative-results-v1",
        "retention_policy": "append_only_no_cherry_picking",
        "result_count": len(decisions) + 1,
        "real_provider_results": [
            {
                "provider_id": item["provider_id"],
                "decision": item["decision"],
                "reason_codes": item["reason_codes"],
            }
            for item in decisions
        ],
        "fixture_negative_result": fixture_fail.model_dump(mode="json"),
        "deleted_negative_result_count": 0,
    }
    return {
        "desk_review": desk_review,
        "trial_requests": trial_requests,
        "scorecard": scorecard,
        "decisions": decision_payload,
        "conditional": conditional,
        "crosscheck": crosscheck,
        "ablation": ablation,
        "news": news,
        "degradation": degradation,
        "registry": registry,
        "negative": negative,
        "recommendation": _recommendation(decisions),
        "ai_trader": _ai_trader_review(),
    }


def _validate(payloads: dict[str, object]) -> None:
    decisions = cast("dict[str, object]", payloads["decisions"])
    trial_requests = cast("dict[str, object]", payloads["trial_requests"])
    scorecard = cast("dict[str, object]", payloads["scorecard"])
    crosscheck = cast("dict[str, object]", payloads["crosscheck"])
    ablation = cast("dict[str, object]", payloads["ablation"])
    degradation = cast("dict[str, object]", payloads["degradation"])
    registry = cast("dict[str, object]", payloads["registry"])
    checks = {
        "no purchase": decisions["procurement_decision"] == "NO_PURCHASE"
        and decisions["approved_provider_count"] == 0,
        "no unauthorized trial": trial_requests["approved_max_cost_usd"] == "0"
        and trial_requests["activated_trial_count"] == 0
        and trial_requests["real_provider_network_requests_performed"] == 0,
        "no fabricated score": scorecard["numeric_scores_assigned_without_trial"] == 0,
        "official authority": crosscheck["third_party_trading_fact_rejected"] is True
        and crosscheck["third_party_replaces_official_trading_fact"] is False,
        "ablation gate": cast("dict[str, object]", ablation["passing_gate"])["decision"]
        == "APPROVE"
        and cast("dict[str, object]", ablation["negative_gate"])["decision"] == "REJECT"
        and ablation["real_provider_trial_count"] == 0,
        "degradation": degradation["free_baseline_survives_provider_loss"] is True
        and degradation["unpaid_provider_runtime_hard_dependency"] is False,
        "registry": registry["approved_paid_count"] == 0,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("P17 evidence validation failed: " + ", ".join(failed))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    payloads = build_payloads()
    _validate(payloads)
    mismatches: list[str] = []
    for name, payload in payloads.items():
        target = OUTPUTS[name]
        rendered = payload if isinstance(payload, str) else _render_json(payload)
        if arguments.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != rendered:
                mismatches.append(target.relative_to(ROOT).as_posix())
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8", newline="\n")
    if mismatches:
        raise SystemExit("P17 evidence drift: " + ", ".join(mismatches))
    print(f"{'verified' if arguments.check else 'generated'} {len(payloads)} P17 evidence files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
