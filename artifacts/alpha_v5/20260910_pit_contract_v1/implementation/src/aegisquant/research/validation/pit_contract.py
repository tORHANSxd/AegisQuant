"""One B2 data-quality job over explicitly registered PIT evidence; never run a strategy."""

from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree

from pydantic import TypeAdapter, model_validator

from aegisquant.data.hashing import ensure_sha256, sha256_file
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.research.datasets.pit_universe import (
    LiquidityObservation,
    PITUniverseSnapshot,
    RuleProvenance,
    audit_universe_at,
)
from aegisquant.research.datasets.universe import PointInTimeUniverse, UniverseMembership
from aegisquant.research.validation.evidence_contract import (
    BASE,
    LOCKS,
    ZERO_BUDGETS,
    EvidenceReader,
    audit_existing_files,
    checked_path,
    claim_output,
    require,
    safety_literals,
    seal_output,
    write_json_exclusive,
    zero_budget_guard,
)
from aegisquant.research.validation.experiment_registry import registered_run

MODIFIED_FILES = (
    "src/aegisquant/research/datasets/universe.py",
    "src/aegisquant/research/datasets/pit_universe.py",
    "scripts/run_alpha_v5_research.py",
    "tests/alpha_v5/test_research_guards.py",
    "tests/alpha_v5/test_no_future_mutation.py",
)
NEW_FILES = (
    "src/aegisquant/research/validation/pit_contract.py",
    "configs/research/alpha_v5_pit_contract.yaml",
    "docs/research/alpha_v5_pit_contract.md",
)
B2_FILES = (*MODIFIED_FILES, *NEW_FILES)
INPUTS = ("universe_events", "liquidity_windows", "rules_provenance", "coverage_manifest")


class PITCoverageManifest(DomainModel):
    schema_version: Literal["pit-coverage-b2-v1"]
    classification: Literal["PREVIOUSLY_USED_DEVELOPMENT_METADATA"]
    period_start: UtcDateTime
    period_end_exclusive: UtcDateTime
    candidate_instrument_uids: tuple[str, ...]
    event_stream_complete: bool
    includes_delisted_instruments: bool
    source_files: dict[str, str]

    @model_validator(mode="after")
    def validate_coverage(self) -> PITCoverageManifest:
        require(self.period_start < self.period_end_exclusive, "AQ-PIT-COVERAGE-PERIOD")
        require(
            len(set(self.candidate_instrument_uids)) == len(self.candidate_instrument_uids),
            "AQ-PIT-DUPLICATE-COVERAGE-UID",
        )
        for digest in self.source_files.values():
            ensure_sha256(digest, field_name="PIT archive source")
        return self


class PITDataQualityError(ValueError):
    """A retained data-quality failure is not an unsuccessful alpha candidate."""


def validate_pit_config(config: dict[str, Any]) -> None:
    match = re.fullmatch(r"alpha-r5-pit-contract-(\d{8})-v([1-9]\d*)", config["generation"])
    require(match is not None, "AQ-PIT-GENERATION")
    if match is None:
        return
    require(
        config["output"] == f"artifacts/alpha_v5/{match[1]}_pit_contract_v{match[2]}",
        "AQ-PIT-GENERATION-OUTPUT",
    )
    require(
        config["scope"] == "B2_PIT_CONTRACTS_AND_SYNTHETIC_TESTS"
        and config["mode"] == "PIT_DATA_QUALITY_ONLY",
        "AQ-PIT-SCOPE",
    )
    require(config["source_head"] == BASE and config["branch_required"] == "main", "AQ-PIT-BASE")
    require(
        config["budgets"] == {"data_quality_jobs": 1, **dict.fromkeys(ZERO_BUDGETS, 0)},
        "AQ-PIT-NONZERO-RESEARCH-BUDGET",
    )
    require(
        config["production_policy"] == "CASH"
        and config["research_conclusion"] == "NO_PROVEN_ALPHA"
        and all(config[key] is False for key in LOCKS),
        "AQ-PIT-SAFETY-LOCK",
    )
    require(
        config["allow_synthetic_historical_evidence"] is False
        and config["strict_data_quality"] is True,
        "AQ-PIT-EVIDENCE-DOWNGRADE",
    )
    require(set(config["inputs"]) == set(INPUTS), "AQ-PIT-INPUT-COVERAGE")
    require(config["input_root"] == "data/research/pit", "AQ-PIT-INPUT-ROOT")
    for value in config["inputs"].values():
        require((value["path"] is None) == (value["sha256"] is None), "AQ-PIT-UNBOUND-INPUT")
        if value["sha256"] is not None:
            ensure_sha256(value["sha256"], field_name="PIT registered input")
    require(
        config["warmup_requirements"]
        == {"trend_40d": 241, "trend_80d": 481, "trend_160d": 961, "volatility_42_returns": 43},
        "AQ-PIT-DEPENDENCY-WARMUP",
    )


def read_bound_input(reader: EvidenceReader, input_root: str, name: str, digest: str) -> Path:
    path = checked_path(reader.root, name)
    require(
        path.resolve().is_relative_to((reader.root / input_root).resolve()),
        "AQ-PIT-UNREGISTERED-INPUT-ROOT",
    )
    ensure_sha256(digest, field_name="PIT input SHA256")
    require(sha256_file(path) == digest, "AQ-PIT-INPUT-HASH-CONFLICT")
    return reader.path(name, "REGISTERED_PIT_METADATA_OR_ARCHIVE_HASH")


def validate_pit_tables(
    reader: EvidenceReader, config: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    documents: dict[str, Any] = {}
    gaps: list[dict[str, Any]] = []
    for name, binding in config["inputs"].items():
        if binding["path"] is None:
            gaps.append(
                {
                    "item": name,
                    "status": "NOT_RECEIVED",
                    "reason": "No registered historical PIT file; no zero-row universe inferred.",
                }
            )
            continue
        path = read_bound_input(reader, config["input_root"], binding["path"], binding["sha256"])
        documents[name] = json.loads(path.read_text(encoding="utf-8"))
    if config["minimum_trailing_30d_quote_volume"] is None:
        gaps.append(
            {
                "item": "minimum_trailing_30d_quote_volume",
                "status": "NOT_REGISTERED",
                "reason": "No historical threshold is invented from synthetic examples.",
            }
        )
    schemas = {
        "universe_events": UniverseMembership.model_json_schema(),
        "liquidity_windows": LiquidityObservation.model_json_schema(),
        "rules_provenance": RuleProvenance.model_json_schema(),
        "coverage_manifest": PITCoverageManifest.model_json_schema(),
    }
    result: dict[str, Any] = {
        "tables": {
            name: {
                "status": "NOT_RECEIVED" if name not in documents else "RECEIVED_NOT_YET_VERIFIED",
                "schema": schema,
                "source": config["inputs"][name],
                "records": None,
            }
            for name, schema in schemas.items()
        },
        "historical_snapshots": None,
        "historical_coverage": {
            "candidate_count": None,
            "delisted_count": None,
            "unknown_exclusion_fraction": None,
            "real_history_coverage": "NOT_VERIFIED",
        },
        "legacy_five_asset_comparison": None,
    }
    if set(documents) != set(INPUTS):
        return result, gaps
    members = TypeAdapter(tuple[UniverseMembership, ...]).validate_json(
        json.dumps(documents["universe_events"]["records"])
    )
    observations = TypeAdapter(tuple[LiquidityObservation, ...]).validate_json(
        json.dumps(documents["liquidity_windows"]["records"])
    )
    rules = TypeAdapter(tuple[RuleProvenance, ...]).validate_json(
        json.dumps(documents["rules_provenance"]["records"])
    )
    coverage = PITCoverageManifest.model_validate_json(json.dumps(documents["coverage_manifest"]))
    universe = PointInTimeUniverse(members)
    require(
        set(coverage.candidate_instrument_uids) == {row.instrument_id for row in members},
        "AQ-PIT-CANDIDATE-COVERAGE-CONFLICT",
    )
    require(bool(members) and bool(observations) and bool(rules), "AQ-PIT-EMPTY-HISTORICAL-TABLE")
    require(
        coverage.period_start.isoformat() == config["period_start"]
        and coverage.period_end_exclusive.isoformat() == config["period_end_exclusive"],
        "AQ-PIT-COVERAGE-PERIOD-BINDING",
    )
    if not coverage.event_stream_complete or not coverage.includes_delisted_instruments:
        gaps.append(
            {
                "item": "historical_universe_coverage",
                "status": "NOT_VERIFIED",
                "reason": "Coverage attestation is incomplete or omits delisted assets.",
            }
        )
    if not any(
        row.evidence is not None and row.evidence.event_kind == "DELISTED" for row in members
    ):
        gaps.append(
            {
                "item": "delisted_instruments",
                "status": "NOT_VERIFIED",
                "reason": "No delisting event supports the required historical coverage.",
            }
        )
    for name, digest in coverage.source_files.items():
        read_bound_input(reader, config["input_root"], name, digest)
    source_hashes = set(coverage.source_files.values())
    required_hashes = {row.source_sha256 for row in observations} | {
        row.source_sha256 for row in rules
    }
    required_hashes |= {row.evidence.source_sha256 for row in members if row.evidence is not None}
    required_hashes |= {
        bar.source_sha256
        for row in observations
        if row.evidence is not None
        for bar in row.evidence.bars
    }
    require(required_hashes <= source_hashes, "AQ-PIT-ARCHIVE-SOURCE-NOT-BOUND")
    for name, rows in (
        ("universe_events", members),
        ("liquidity_windows", observations),
        ("rules_provenance", rules),
    ):
        result["tables"][name].update(
            status="SCHEMA_AND_SOURCE_HASH_VERIFIED",
            records=[row.model_dump(mode="json") for row in rows],
        )
    result["tables"]["coverage_manifest"].update(
        status="SOURCE_ATTESTATION_NOT_INDEPENDENT_CENSUS", records=coverage.model_dump(mode="json")
    )
    if config["minimum_trailing_30d_quote_volume"] is None:
        return result, gaps
    for bound in (coverage.period_start, coverage.period_end_exclusive):
        require(
            bound.hour % 4 == 0 and not bound.minute and not bound.second and not bound.microsecond,
            "AQ-PIT-COVERAGE-CALENDAR-ALIGNMENT",
        )
    cutoff_times: list[datetime] = []
    cutoff = coverage.period_start
    while cutoff < coverage.period_end_exclusive:
        cutoff_times.append(cutoff)
        cutoff += timedelta(hours=4)
    snapshots: list[PITUniverseSnapshot] = []
    # ponytail: direct pure queries suit the current contract/no-data job. Index the
    # same as-of semantics before ingesting a large full-market archive.
    for cutoff in cutoff_times:
        snapshots.append(
            audit_universe_at(
                universe,
                observations,
                rules=rules,
                decision_time=cutoff,
                minimum_quote_volume=Decimal(config["minimum_trailing_30d_quote_volume"]),
                warmup_requirements=config["warmup_requirements"],
                minimum_history_bars=config["minimum_history_4h_bars"],
                maximum_age=timedelta(hours=config["maximum_liquidity_age_hours"]),
            )
        )
    dispositions = Counter(row.disposition for snapshot in snapshots for row in snapshot.decisions)
    if dispositions["UNKNOWN"]:
        gaps.append(
            {
                "item": "strict_asof_coverage",
                "status": "NOT_VERIFIED",
                "reason": "At least one decision requires unknown membership, liquidity or rules evidence.",
            }
        )
    result["historical_snapshots"] = [snapshot.model_dump(mode="json") for snapshot in snapshots]
    result["historical_coverage"] = {
        "candidate_count": len(coverage.candidate_instrument_uids),
        "delisted_count": len(
            {
                row.instrument_id
                for row in members
                if row.evidence is not None and row.evidence.event_kind == "DELISTED"
            }
        ),
        "snapshot_count": len(snapshots),
        "dispositions": dict(dispositions),
        "unknown_exclusion_fraction": str(
            Decimal(dispositions["UNKNOWN"]) / sum(dispositions.values())
        )
        if dispositions
        else None,
        "real_history_coverage": "SOURCE_MANIFEST_ATTESTED_NOT_INDEPENDENT_CENSUS",
    }
    comparison: list[dict[str, Any]] = []
    for snapshot in snapshots:
        current = universe.current_memberships(as_of_time=snapshot.membership_snapshot.as_of_time)
        selected = {
            row.evidence.symbol
            for row in current
            if row.evidence is not None and row.instrument_id in snapshot.eligible_instrument_ids
        }
        legacy = set(config["legacy_symbols"])
        comparison.append(
            {
                "as_of": snapshot.membership_snapshot.as_of_time,
                "pit_only": sorted(selected - legacy),
                "legacy_only": sorted(legacy - selected),
                "interpretation": "COMPONENT_BIAS_DIAGNOSTIC_NO_PERFORMANCE_SELECTION",
            }
        )
    result["legacy_five_asset_comparison"] = comparison
    return result, gaps


def test_receipts(root: Path, stage: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = json.loads((stage / "validation_records.json").read_text(encoding="utf-8"))
    latest = {row["check"]: row for row in records}
    hashes = {name: sha256_file(checked_path(root, name)) for name in B2_FILES}
    for check in ("pytest", "ruff", "format", "pyright"):
        require(
            check in latest
            and latest[check]["exit_code"] == 0
            and latest[check]["source_sha256"] == hashes,
            f"AQ-PIT-VALIDATION-NOT-CURRENT:{check}",
        )
    xml = stage / "pytest_results.xml"
    cases = ElementTree.parse(xml).getroot().findall(".//testcase")  # noqa: S314 -- locally generated pytest receipt.
    require(
        bool(cases)
        and all(
            not any(row.tag in {"failure", "error", "skipped"} for row in case) for case in cases
        ),
        "AQ-PIT-TEST-FAILURE-OR-SKIP",
    )
    future = [case.attrib["name"] for case in cases if "test_b2_future" in case.attrib["name"]]
    require(len(future) >= 9, "AQ-PIT-FUTURE-CONTRACT-TESTS-MISSING")
    return records, {
        "kind": "SYNTHETIC_ONLY_NOT_HISTORICAL_COVERAGE",
        "passed_tests": len(cases),
        "future_mutation_cases": future,
        "real_engine_prefix_checks": "NOT_RUN_B2_SCOPE",
        "source_sha256": hashes,
        "pytest_xml_sha256": sha256_file(xml),
    }


def run_pit_quality_job(
    root: Path, config: dict[str, Any], stage: Path, git_state: dict[str, str]
) -> tuple[Path, int]:
    validate_pit_config(config)
    require(
        git_state["branch"] == "main" and git_state["head"] == BASE, "AQ-PIT-WORKSPACE-IDENTITY"
    )
    baseline = json.loads((stage / "baseline_workspace.json").read_text(encoding="utf-8"))
    require(
        baseline["head"] == BASE
        and baseline["branch"] == "main"
        and Path(baseline["root"]).resolve() == root.resolve(),
        "AQ-PIT-PREFLIGHT-IDENTITY",
    )
    require(
        set(baseline["allowed_modifications"]) == set(MODIFIED_FILES), "AQ-PIT-MODIFICATION-SCOPE"
    )
    preserved = {
        **baseline,
        "files": {
            name: row for name, row in baseline["files"].items() if name not in MODIFIED_FILES
        },
    }
    records, receipts = test_receipts(root, stage)
    output = claim_output(
        root,
        config["output"],
        frozen_roots=[root / config["r5_frozen_root"], root / config["b0_frozen_root"]],
    )
    counters: dict[str, int] = dict.fromkeys(ZERO_BUDGETS, 0)
    reader = EvidenceReader(root)
    run_id = config["generation"] + ":DATA_QUALITY"
    exit_code = 0
    try:
        with registered_run(  # noqa: SIM117 -- keep the journal scope outside the write guard.
            output,
            run_id,
            planned_run_ids=[run_id],
            bindings={"kind": "PIT_DATA_QUALITY_NOT_ALPHA_TRIAL"},
        ):
            with zero_budget_guard(output, root, counters):
                write_json_exclusive(
                    output / "preregistration.json",
                    {
                        "registered_at": datetime.now(UTC),
                        "config": config,
                        "planned_run_ids": [run_id],
                        "kind": "PIT_DATA_QUALITY_NOT_ALPHA_TRIAL",
                    },
                )
                before = audit_existing_files(root, preserved)
                for name in (
                    "baseline_workspace.json",
                    "workspace_before.patch",
                    "version_graph.txt",
                    "validation_records.json",
                    "test_commands_and_results.txt",
                    "pytest_results.xml",
                ):
                    path = checked_path(stage, name)
                    target = (
                        output
                        / (
                            "validation"
                            if name
                            in {
                                "validation_records.json",
                                "test_commands_and_results.txt",
                                "pytest_results.xml",
                            }
                            else "preflight"
                        )
                        / name
                    )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        stream.write(path.read_bytes())
                patch = ""
                for name in B2_FILES:
                    path = checked_path(root, name)
                    old = checked_path(stage, "before/" + name) if name in MODIFIED_FILES else None
                    if old is not None:
                        require(
                            sha256_file(old) == baseline["files"][name]["sha256"],
                            "AQ-PIT-BASELINE-COPY-CONFLICT",
                        )
                        target = output / "before" / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("xb") as stream:
                            stream.write(old.read_bytes())
                    target = output / "implementation" / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        stream.write(path.read_bytes())
                    patch += "".join(
                        difflib.unified_diff(
                            old.read_text(encoding="utf-8").splitlines(keepends=True)
                            if old is not None
                            else [],
                            path.read_text(encoding="utf-8").splitlines(keepends=True),
                            fromfile="a/" + name if old is not None else "/dev/null",
                            tofile="b/" + name,
                        )
                    )
                with (output / "changes_this_batch.patch").open(
                    "x", encoding="utf-8", newline="\n"
                ) as stream:
                    stream.write(patch)
                manifest_path = reader.path(config["r5_frozen_root"] + "/audit_manifest.json")
                require(
                    sha256_file(manifest_path) == config["r5_manifest_sha256"],
                    "AQ-PIT-R5-FROZEN-IDENTITY",
                )
                b0_path = reader.path(config["b0_frozen_root"] + "/OUTPUT_MANIFEST.json")
                require(
                    sha256_file(b0_path) == config["b0_manifest_sha256"],
                    "AQ-PIT-B0-FROZEN-IDENTITY",
                )
                locks = safety_literals(
                    reader,
                    reader.json(config["r5_frozen_root"] + "/audit_manifest.json", native=True),
                )
                products, gaps = validate_pit_tables(reader, config)
                for name, table in products["tables"].items():
                    write_json_exclusive(output / f"{name}.json", table)
                write_json_exclusive(
                    output / "asof_snapshot_manifest.json",
                    {key: value for key, value in products.items() if key != "tables"},
                )
                write_json_exclusive(output / "future_mutation_report.json", receipts)
                write_json_exclusive(
                    output / "evidence_gaps.json",
                    {"gaps": gaps, "synthetic_evidence_is_historical": False},
                )
                status = (
                    "FAILED_CLOSED_INSUFFICIENT_PIT_EVIDENCE"
                    if gaps
                    else "SCHEMA_AND_BOUND_EVIDENCE_CHECKS_PASSED"
                )
                after = audit_existing_files(root, preserved)
                write_json_exclusive(
                    output / "safety_and_budget_audit.json",
                    {
                        "authorized": config["budgets"],
                        "actual": {"data_quality_jobs": 1, **counters},
                        "strict_data_quality": status,
                        "new_alpha_trials": 0,
                        "significance_recalculations": 0,
                        "historical_pit_snapshots": None
                        if products["historical_snapshots"] is None
                        else len(products["historical_snapshots"]),
                        "before": before,
                        "after": after,
                        "live_lock_literals": locks,
                        "production_policy": "CASH",
                        "research_conclusion": "NO_PROVEN_ALPHA",
                        **dict.fromkeys(LOCKS, False),
                        "promotion_admitted": False,
                    },
                )
                write_json_exclusive(
                    output / "source_and_version_bindings.json",
                    {
                        "generation": config["generation"],
                        "head": BASE,
                        "branch": "main",
                        "reads": reader.reads,
                        "modified_files": {
                            name: {
                                "before": baseline["files"][name]["sha256"],
                                "after": sha256_file(root / name),
                            }
                            for name in MODIFIED_FILES
                        },
                        "new_files": {name: sha256_file(root / name) for name in NEW_FILES},
                        "commits_created": 0,
                        "pushes": 0,
                        "branches_created": 0,
                    },
                )
                report = "\n".join(
                    [
                        "# B2 PIT 数据契约与合成验证",
                        "",
                        "**NO_PROVEN_ALPHA / CASH；ML、纸面准入、实盘和订单提交全部关闭。**",
                        "",
                        f"Generation：`{config['generation']}`；身份：已有 main `{BASE}` + 冻结 R5 v3 + B0/B1 v2。",
                        "历史策略回放、真实模型拟合、真实校准拟合、最终留出访问、真实订单全部为 0。",
                        "",
                        f"工程验证：{receipts['passed_tests']} 项限定纯测试通过；Ruff、格式和类型检查通过。实际 {len(records)} 次检查记录及失败尝试均保留。",
                        f"严格数据质量状态：`{status}`；独占数据质量作业 1 次，不因缺件重开。",
                        "",
                        "新增事件级修订与同键冲突检查，区分公告、接收、修订和生效时间；重上市使用独立 instrument UID。",
                        "连续历史按已登记依赖取最大值：40/80/160 日趋势分别需 241/481/961 根闭合四小时数据，42 个收益的波动窗口需 43 根。",
                        "30 日 quote turnover 直接对带哈希明细求和；零量、缺口、proxy、短历史及未知规则不能打开新风险。",
                        "新严格模式按交易状态变化重新证明连续 warm-up；不修改冻结 G1 的 gap、参数、费用或下单行为。",
                        "仅返回新开风险资格，已有持仓身份原样保留；不删除、免费平仓或借用未来退市价格。",
                        "",
                        "future-mutation 只覆盖本批 PIT 的事件、流动性、规则和跨币资格快照；合成测试不代表真实行情、特征、风险、订单或成交前缀已经重验。",
                        "旧 legacy 五币研究函数体保持冻结语义；旧回放测试未运行。新入口 pit-audit 只进入数据质量作业。",
                        "",
                        "实际数据表、来源和 schema 见 universe_events/liquidity_windows/rules_provenance/coverage_manifest；未收到用 records=null 表达，不把缺件变成空市场。",
                        "缺全历史候选/退市证据或未登记流动性阈值时，历史覆盖率、独立全市场核验与成分差异保持未知；不把今天的币表或 base_volume×close 回填成真实 PIT。",
                        f"保护范围内 {after['files_checked']} 个既有文件哈希未变；本批五个允许修改文件的原字节、八个实施文件与补丁均保存。",
                        "",
                        "下一步所需输入仅列于 evidence_gaps.json；取得真实来源及新 generation 后才能重新开展严格数据质量核验。本批不进入 B3 或任何收益/交易实验。",
                        "",
                    ]
                )
                with (output / "report.md").open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(report)
                if gaps:
                    raise PITDataQualityError("AQ-PIT-STRICT-DATA-QUALITY-INSUFFICIENT-EVIDENCE")
    except BaseException as error:
        exit_code = 2
        write_json_exclusive(
            output / "failure.json",
            {
                "status": "FAILED_RETAINED_DO_NOT_REOPEN",
                "error": f"{type(error).__name__}: {error}",
                "kind": "PIT_DATA_QUALITY_NOT_ALPHA_TRIAL",
                "actual": {"data_quality_jobs": 1, **counters},
                "research_conclusion": "NO_PROVEN_ALPHA",
                "production_policy": "CASH",
            },
        )
        if not isinstance(error, PITDataQualityError):
            seal_output(output)
            raise
    seal_output(output)
    return output, exit_code
