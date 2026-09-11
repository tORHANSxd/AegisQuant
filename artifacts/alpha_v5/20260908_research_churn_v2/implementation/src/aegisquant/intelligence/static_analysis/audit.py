"""Conservative bias, cost, execution, tail-risk, and rights audit."""

from __future__ import annotations

from collections.abc import Iterable

from aegisquant.intelligence.static_analysis.models import (
    AuditFinding,
    AuditTag,
    EvidenceSpan,
    EvidenceStatus,
    RightsStatus,
    StaticAnalysisReport,
    StrategyAudit,
    StrategyIR,
)


def _evidence_for(evidence: tuple[EvidenceSpan, ...], prefixes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        item.evidence_id
        for item in evidence
        if any(item.selector.startswith(prefix) for prefix in prefixes)
    )


def audit_strategy(
    *,
    strategy_ir: StrategyIR,
    scan: StaticAnalysisReport,
    evidence_spans: Iterable[EvidenceSpan],
    rights_status: RightsStatus,
) -> StrategyAudit:
    """Produce explicit audit tags without accepting source performance claims."""
    evidence = tuple(evidence_spans)
    findings: list[AuditFinding] = []

    lookahead = tuple(
        item for item in scan.findings if item.category in {"lookahead", "time_index_semantics"}
    )
    if lookahead:
        findings.append(
            AuditFinding(
                tag=AuditTag.LEAKAGE,
                code="AQ-AUDIT-LOOKAHEAD",
                severity="CRITICAL",
                message="源码包含负向位移或末行位置访问，无法证明 point-in-time 安全。",
                evidence_ids=_evidence_for(evidence, ("signal:", "feature:")),
            )
        )

    if {"get_all_securities", "get_index_stocks"} & set(scan.data_calls):
        findings.append(
            AuditFinding(
                tag=AuditTag.SURVIVORSHIP_BIAS,
                code="AQ-AUDIT-UNIVERSE-PIT-UNPROVEN",
                severity="HIGH",
                message="成分或证券全集查询缺少历史时点成员资格证明。",
                evidence_ids=_evidence_for(evidence, ("universe:",)),
            )
        )

    unsupported_execution = any(
        item.status is EvidenceStatus.UNSUPPORTED for item in strategy_ir.execution_assumptions
    )
    if unsupported_execution:
        findings.extend(
            (
                AuditFinding(
                    tag=AuditTag.COST_SENSITIVE,
                    code="AQ-AUDIT-COSTS-MISSING",
                    severity="HIGH",
                    message="手续费、滑点或市场冲击没有来源证据，来源收益不可采用。",
                    evidence_ids=(),
                ),
                AuditFinding(
                    tag=AuditTag.EXECUTION_UNREALISTIC,
                    code="AQ-AUDIT-EXECUTION-MISSING",
                    severity="HIGH",
                    message="成交时点、订单类型和可成交性假设不完整。",
                    evidence_ids=(),
                ),
            )
        )

    if any(item.status is EvidenceStatus.UNSUPPORTED for item in strategy_ir.risk_controls):
        findings.append(
            AuditFinding(
                tag=AuditTag.TAIL_RISK_HIDDEN,
                code="AQ-AUDIT-RISK-CONTROLS-MISSING",
                severity="HIGH",
                message="止损、暴露上限、补仓和尾部风险控制没有可核验证据。",
                evidence_ids=(),
            )
        )

    missing_parameters = tuple(
        item.name for item in strategy_ir.parameters if item.provenance.value == "missing"
    )
    if strategy_ir.known_unknowns or missing_parameters:
        findings.append(
            AuditFinding(
                tag=AuditTag.INFORMATION_MISSING,
                code="AQ-AUDIT-INFORMATION-MISSING",
                severity="MEDIUM",
                message="Strategy IR 保留未支持规则或缺失参数，禁止 AI 自行补造。",
                evidence_ids=(),
            )
        )

    explicit_parameter_count = sum(
        item.provenance.value != "missing" for item in strategy_ir.parameters
    )
    if explicit_parameter_count > 12:
        findings.append(
            AuditFinding(
                tag=AuditTag.OVERFIT_RISK,
                code="AQ-AUDIT-PARAMETER-COUNT",
                severity="MEDIUM",
                message="显式参数数量超过初筛阈值，需要搜索预算和多重试验记录。",
                evidence_ids=_evidence_for(evidence, ("parameter:",)),
            )
        )

    expressions = "\n".join(
        item.expression or ""
        for group in (strategy_ir.entries, strategy_ir.exits, strategy_ir.position_sizing)
        for item in group
    ).casefold()
    if any(token in expressions for token in ("martingale", "2 **", "double", "倍投")):
        findings.append(
            AuditFinding(
                tag=AuditTag.TAIL_RISK_HIDDEN,
                code="AQ-AUDIT-MARTINGALE",
                severity="CRITICAL",
                message="检测到倍增或马丁格尔语义，尾部风险可能被隐藏。",
                evidence_ids=_evidence_for(evidence, ("trade:", "sizing:")),
            )
        )

    if rights_status is not RightsStatus.PUBLIC_LICENSE:
        findings.append(
            AuditFinding(
                tag=AuditTag.LICENSE_RESTRICTED,
                code="AQ-AUDIT-RIGHTS-RESTRICTED",
                severity="HIGH" if rights_status is RightsStatus.PROHIBITED else "MEDIUM",
                message="来源权利不允许公开正文或代码工件。",
                evidence_ids=(),
            )
        )

    findings.append(
        AuditFinding(
            tag=AuditTag.PARTIAL,
            code="AQ-AUDIT-STATIC-ONLY",
            severity="INFO",
            message="本阶段仅完成静态审计，未执行来源策略或采用来源回测收益。",
            evidence_ids=(),
        )
    )
    if (
        any(item.severity == "CRITICAL" for item in findings)
        or rights_status is RightsStatus.PROHIBITED
    ):
        findings.append(
            AuditFinding(
                tag=AuditTag.REJECTED,
                code="AQ-AUDIT-FAIL-CLOSED",
                severity="CRITICAL",
                message="关键安全、时间或权利门禁失败，候选被拒绝。",
                evidence_ids=(),
            )
        )
    tags = tuple(sorted({item.tag for item in findings}, key=str))
    return StrategyAudit(strategy_id=strategy_ir.strategy_id, findings=tuple(findings), tags=tags)
