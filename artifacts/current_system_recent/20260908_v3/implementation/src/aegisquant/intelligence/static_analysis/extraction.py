"""Evidence-bound Strategy IR extraction with a proposal-only AI lane."""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Iterable
from typing import cast

from pydantic import Field, JsonValue, model_validator

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.intelligence.static_analysis.models import (
    ArtifactKind,
    EvidenceSpan,
    EvidenceStatus,
    FeatureIR,
    KnowledgeProposal,
    ParameterIR,
    ParameterProvenance,
    SourceArtifact,
    StaticAnalysisReport,
    StrategyIR,
    StrategyRuleIR,
)
from aegisquant.intelligence.static_analysis.scanner import source_lines


class StrategyExtractionResult(DomainModel):
    strategy_ir: StrategyIR
    evidence_spans: tuple[EvidenceSpan, ...] = Field(min_length=1)
    extraction_channel: str = "RULE_BASED_AST"
    source_code_executed: bool = False
    unsupported_assertions: tuple[str, ...]

    @model_validator(mode="after")
    def validate_evidence_links(self) -> StrategyExtractionResult:
        declared = {item.evidence_id for item in self.evidence_spans}
        referenced = ir_evidence_ids(self.strategy_ir)
        if referenced != declared:
            raise ValueError("Strategy IR evidence links must exactly match extracted spans")
        return self


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _base_call_name(node: ast.Call) -> str:
    return _call_name(node.func).rsplit(".", maxsplit=1)[-1]


def _safe_literal(node: ast.AST) -> JsonValue | None:
    try:
        value = cast("object", ast.literal_eval(node))
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None
    return _json_value(value)


def _json_value(value: object) -> JsonValue | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return cast("JsonValue", value)
    if isinstance(value, (list, tuple)):
        converted = [_json_value(item) for item in cast("list[object] | tuple[object, ...]", value)]
        if all(item is not None for item in converted):
            return cast("JsonValue", converted)
    if isinstance(value, dict):
        typed_value = cast("dict[object, object]", value)
        if not all(isinstance(key, str) for key in typed_value):
            return None
        converted_dict = {str(key): _json_value(item) for key, item in typed_value.items()}
        if all(item is not None for item in converted_dict.values()):
            return cast("JsonValue", converted_dict)
    return None


class _EvidenceFactory:
    def __init__(self, *, source_id: str, artifact: SourceArtifact, lines: tuple[str, ...]) -> None:
        self.source_id = source_id
        self.artifact = artifact
        self.lines = lines
        self.spans: list[EvidenceSpan] = []

    def create(self, node: ast.AST, selector: str) -> str:
        start = max(getattr(node, "lineno", 1), 1)
        end = max(getattr(node, "end_lineno", start) or start, start)
        excerpt = "\n".join(self.lines[start - 1 : end]).strip()
        excerpt = excerpt[:400] or "<empty source line>"
        excerpt_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        evidence_id = canonical_sha256(
            {
                "artifact_id": self.artifact.artifact_id,
                "start_line": start,
                "end_line": end,
                "selector": selector,
                "excerpt_sha256": excerpt_hash,
            }
        )
        self.spans.append(
            EvidenceSpan(
                evidence_id=evidence_id,
                source_id=self.source_id,
                artifact_id=self.artifact.artifact_id,
                artifact_sha256=self.artifact.sha256,
                start_line=start,
                end_line=end,
                selector=selector,
                excerpt=excerpt,
                excerpt_sha256=excerpt_hash,
            )
        )
        return evidence_id


def _lookback(call: ast.Call) -> str | None:
    for keyword in call.keywords:
        if keyword.arg in {"count", "bar_count", "window", "lookback"}:
            value = _safe_literal(keyword.value)
            return str(value) if value is not None else None
    if call.args:
        for argument in reversed(call.args):
            value = _safe_literal(argument)
            if isinstance(value, (int, str)):
                return str(value)
    return None


def _is_zero_target(call: ast.Call) -> bool:
    if len(call.args) < 2:
        return False
    value = _safe_literal(call.args[1])
    return value in {0, "0"}


def _unsupported_rule(rule_id: str) -> StrategyRuleIR:
    return StrategyRuleIR(
        rule_id=rule_id,
        expression=None,
        evidence_ids=(),
        status=EvidenceStatus.UNSUPPORTED,
    )


def extract_strategy_ir(
    *,
    strategy_id: str,
    source_id: str,
    artifact: SourceArtifact,
    raw: bytes,
    scan: StaticAnalysisReport,
) -> StrategyExtractionResult:
    """Extract conservative machine-readable rules from already scanned source bytes."""
    if scan.artifact_id != artifact.artifact_id or scan.source_id != source_id:
        raise ValueError("static-analysis report does not match extraction input")
    if not scan.syntax_valid:
        raise ValueError("invalid source cannot be converted to Strategy IR")
    notebook = artifact.kind is ArtifactKind.NOTEBOOK
    lines = source_lines(raw, notebook=notebook)
    source = "\n".join(lines)
    tree = ast.parse(source, filename=artifact.relative_path, mode="exec")
    evidence = _EvidenceFactory(source_id=source_id, artifact=artifact, lines=lines)

    calls = sorted(
        (node for node in ast.walk(tree) if isinstance(node, ast.Call)),
        key=lambda item: (item.lineno, item.col_offset),
    )
    assignments = sorted(
        (node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))),
        key=lambda item: (item.lineno, item.col_offset),
    )
    comparisons = sorted(
        (node for node in ast.walk(tree) if isinstance(node, ast.Compare)),
        key=lambda item: (item.lineno, item.col_offset),
    )

    features: list[FeatureIR] = []
    entries: list[StrategyRuleIR] = []
    exits: list[StrategyRuleIR] = []
    sizing: list[StrategyRuleIR] = []
    rebalance: list[StrategyRuleIR] = []
    execution: list[StrategyRuleIR] = []
    risk: list[StrategyRuleIR] = []
    universe: list[StrategyRuleIR] = []

    data_names = set(scan.data_calls)
    trade_names = set(scan.trade_calls)
    schedule_names = set(scan.scheduled_callbacks)
    for index, call in enumerate(calls, start=1):
        base = _base_call_name(call)
        expression = ast.unparse(call)
        if base in data_names:
            evidence_id = evidence.create(call, f"feature:{index}:{base}")
            features.append(
                FeatureIR(
                    feature_id=f"source_feature_{index}_{base}",
                    formula=expression,
                    lookback=_lookback(call),
                    availability_lag="source_unspecified",
                    evidence_ids=(evidence_id,),
                    status=EvidenceStatus.SUPPORTED,
                )
            )
            if base in {"get_all_securities", "get_index_stocks"}:
                universe.append(
                    StrategyRuleIR(
                        rule_id=f"universe_{index}_{base}",
                        expression=expression,
                        evidence_ids=(evidence.create(call, f"universe:{index}:{base}"),),
                        status=EvidenceStatus.SUPPORTED,
                    )
                )
        if base in trade_names:
            rule = StrategyRuleIR(
                rule_id=f"trade_{index}_{base}",
                expression=expression,
                evidence_ids=(evidence.create(call, f"trade:{index}:{base}"),),
                status=EvidenceStatus.SUPPORTED,
            )
            (exits if _is_zero_target(call) else entries).append(rule)
            sizing.append(
                StrategyRuleIR(
                    rule_id=f"sizing_{index}_{base}",
                    expression=expression,
                    evidence_ids=(evidence.create(call, f"sizing:{index}:{base}"),),
                    status=EvidenceStatus.SUPPORTED,
                )
            )
        if base in schedule_names:
            rebalance.append(
                StrategyRuleIR(
                    rule_id=f"rebalance_{index}_{base}",
                    expression=expression,
                    evidence_ids=(evidence.create(call, f"rebalance:{index}:{base}"),),
                    status=EvidenceStatus.SUPPORTED,
                )
            )
        if base in {"set_commission", "set_order_cost", "set_slippage"}:
            execution.append(
                StrategyRuleIR(
                    rule_id=f"execution_{index}_{base}",
                    expression=expression,
                    evidence_ids=(evidence.create(call, f"execution:{index}:{base}"),),
                    status=EvidenceStatus.SUPPORTED,
                )
            )

    signals: list[StrategyRuleIR] = []
    for index, comparison in enumerate(comparisons[:32], start=1):
        signals.append(
            StrategyRuleIR(
                rule_id=f"signal_{index}",
                expression=ast.unparse(comparison),
                evidence_ids=(evidence.create(comparison, f"signal:{index}"),),
                status=EvidenceStatus.SUPPORTED,
            )
        )

    parameters: list[ParameterIR] = []
    for index, assignment in enumerate(assignments, start=1):
        target: ast.AST
        value_node: ast.AST | None
        if isinstance(assignment, ast.Assign) and len(assignment.targets) == 1:
            target = assignment.targets[0]
            value_node = assignment.value
        elif isinstance(assignment, ast.AnnAssign):
            target = assignment.target
            value_node = assignment.value
        else:
            continue
        if not isinstance(target, ast.Name) or value_node is None:
            continue
        value = _safe_literal(value_node)
        if value is None:
            continue
        evidence_id = evidence.create(assignment, f"parameter:{index}:{target.id}")
        parameters.append(
            ParameterIR(
                name=target.id,
                value=value,
                provenance=ParameterProvenance.EXPLICIT,
                evidence_ids=(evidence_id,),
            )
        )
        lowered = target.id.casefold()
        if any(token in lowered for token in ("risk", "stop", "max_position", "exposure")):
            risk.append(
                StrategyRuleIR(
                    rule_id=f"risk_{index}_{target.id}",
                    expression=ast.unparse(assignment),
                    evidence_ids=(evidence.create(assignment, f"risk:{index}:{target.id}"),),
                    status=EvidenceStatus.SUPPORTED,
                )
            )

    unsupported: list[str] = []
    if not universe:
        universe.append(_unsupported_rule("universe_selection_missing"))
        unsupported.append("universe_selection")
    if not features:
        features.append(
            FeatureIR(
                feature_id="feature_definition_missing",
                formula=None,
                lookback=None,
                availability_lag=None,
                evidence_ids=(),
                status=EvidenceStatus.UNSUPPORTED,
            )
        )
        unsupported.append("features")
    if not signals:
        signals.append(_unsupported_rule("signal_definition_missing"))
        unsupported.append("signals")
    if not entries:
        entries.append(_unsupported_rule("entry_rule_missing"))
        unsupported.append("entries")
    if not exits:
        exits.append(_unsupported_rule("exit_rule_missing"))
        unsupported.append("exits")
    if not sizing:
        sizing.append(_unsupported_rule("position_sizing_missing"))
        unsupported.append("position_sizing")
    if not rebalance:
        rebalance.append(_unsupported_rule("rebalance_rule_missing"))
        unsupported.append("rebalance")
    if not execution:
        execution.append(_unsupported_rule("execution_costs_missing"))
        unsupported.append("execution_assumptions")
    if not risk:
        risk.append(_unsupported_rule("risk_controls_missing"))
        unsupported.append("risk_controls")
    for missing_name in ("fee_bps", "slippage_bps"):
        if not any(item.name.casefold() == missing_name for item in parameters):
            parameters.append(
                ParameterIR(
                    name=missing_name,
                    value=None,
                    provenance=ParameterProvenance.MISSING,
                    evidence_ids=(),
                )
            )

    ir = StrategyIR(
        strategy_id=strategy_id,
        source_ids=(source_id,),
        universe_selection_time=("scheduled_callback" if scan.scheduled_callbacks else None),
        universe_eligibility_rules=tuple(universe),
        data_requirements=tuple(sorted(scan.data_calls)),
        features=tuple(features),
        signals=tuple(signals),
        entries=tuple(entries),
        exits=tuple(exits),
        position_sizing=tuple(sizing),
        rebalance=tuple(rebalance),
        execution_assumptions=tuple(execution),
        risk_controls=tuple(risk),
        parameters=tuple(parameters),
        backtest_evidence={
            "source_performance_accepted": False,
            "source_code_executed": False,
        },
        known_unknowns=tuple(sorted(set(unsupported))),
    )
    return StrategyExtractionResult(
        strategy_ir=ir,
        evidence_spans=tuple(evidence.spans),
        unsupported_assertions=tuple(sorted(set(unsupported))),
    )


def ir_evidence_ids(strategy_ir: StrategyIR) -> set[str]:
    groups: Iterable[object] = (
        strategy_ir.universe_eligibility_rules,
        strategy_ir.features,
        strategy_ir.signals,
        strategy_ir.entries,
        strategy_ir.exits,
        strategy_ir.position_sizing,
        strategy_ir.rebalance,
        strategy_ir.execution_assumptions,
        strategy_ir.risk_controls,
        strategy_ir.parameters,
    )
    return {
        evidence_id
        for group in groups
        for item in cast("Iterable[FeatureIR | StrategyRuleIR | ParameterIR]", group)
        for evidence_id in item.evidence_ids
    }


def validate_ai_knowledge_proposal(
    proposal: KnowledgeProposal,
    evidence_spans: Iterable[EvidenceSpan],
) -> KnowledgeProposal:
    """Fail closed unless every AI assertion is evidence-bound and remains non-executable."""
    available = {item.evidence_id for item in evidence_spans}
    claimed = set(proposal.claimed_evidence_ids)
    referenced = ir_evidence_ids(proposal.candidate_ir)
    if proposal.strategy_id != proposal.candidate_ir.strategy_id:
        raise ValueError("AI proposal strategy ID does not match candidate IR")
    if set(proposal.source_ids) != set(proposal.candidate_ir.source_ids):
        raise ValueError("AI proposal sources do not match candidate IR")
    if claimed != referenced or not claimed.issubset(available):
        raise ValueError("AI proposal contains missing, unused, or fabricated evidence")
    return proposal
