"""Generate or verify deterministic P09 external-knowledge intelligence evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

import polars as pl

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256
from aegisquant.intelligence.static_analysis.archive import ManualExportImporter
from aegisquant.intelligence.static_analysis.audit import audit_strategy
from aegisquant.intelligence.static_analysis.dedupe import build_fingerprint, cluster_duplicates
from aegisquant.intelligence.static_analysis.discovery import normalize_public_candidates
from aegisquant.intelligence.static_analysis.extraction import extract_strategy_ir
from aegisquant.intelligence.static_analysis.models import (
    ArtifactKind,
    RightsRecord,
    RightsStatus,
    SourceArtifact,
    StaticReviewState,
)
from aegisquant.intelligence.static_analysis.scanner import scan_source_bytes
from aegisquant.intelligence.static_analysis.translation import (
    MigrationCandidateKind,
    run_all_translation_candidates,
    run_translation_candidate,
    translation_records,
)

ROOT: Final = Path(__file__).resolve().parents[1]
FIXTURES: Final = ROOT / "tests/fixtures/p09"
DATA: Final = ROOT / "reports/data"
INTELLIGENCE: Final = ROOT / "reports/intelligence"
STATIC_REPORTS: Final = INTELLIGENCE / "static_analysis"
RUNTIME: Final = ROOT / ".runtime/p09-evidence"
OBSERVED_AT: Final = datetime(2026, 9, 2, 2, tzinfo=UTC)
AI_TRADER_COMMIT: Final = "d03ff6c056b32ced735adf7c19ed8175adb1c8df"

JSON_OUTPUTS: Final = (
    "P09_IMPORT_EVIDENCE.json",
    "P09_STATIC_ANALYSIS_EVIDENCE.json",
    "P09_STRATEGY_IR_EVIDENCE.json",
    "P09_RIGHTS_EVIDENCE.json",
    "P09_DEDUPE_EVIDENCE.json",
    "P09_TRANSLATION_EVIDENCE.json",
    "P09_FRAMEWORK_REVIEW_EVIDENCE.json",
    "P09_DISCOVERY_EVIDENCE.json",
    "P09_DEPENDENCY_CONTRACT.json",
)

ALPHA_PRIMITIVES: Final = (
    "trend_slope",
    "breakout",
    "cross_sectional_rank",
    "short_term_reversal",
    "volatility_scaling",
    "carry",
    "basis_convergence",
    "funding_crowding",
    "term_structure",
    "liquidity_imbalance",
    "order_flow_pressure",
    "open_interest_change",
    "liquidation_shock",
    "seasonality",
    "event_surprise",
    "regime_filter",
    "risk_overlay",
)

FRAMEWORKS: Final[tuple[dict[str, str], ...]] = (
    {
        "source_id": "framework-nautilus-trader",
        "name": "NautilusTrader",
        "url": "https://nautilustrader.io/docs/",
        "observed_contract": "事件驱动、统一研究/仿真/实盘语义、模块化 Adapter 和显式恢复。",
        "decision": "retain_pinned_runtime",
        "reason": "项目继续锁定已通过契约的 GA 1.231.0；官方 Python API 的 2.0.0rc3 属预发布，不升级。",
        "rights_status": "public_license",
        "revision": "project-contract-1.231.0",
    },
    {
        "source_id": "framework-lean",
        "name": "QuantConnect LEAN",
        "url": "https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview",
        "observed_contract": "Universe→Alpha/Insight→Portfolio Construction→Risk→Execution 的模块边界。",
        "decision": "reference_only",
        "reason": "吸收关注点分离；C# 内核与 Python 3.11 桥接不作为本项目依赖。",
        "rights_status": "public_license",
        "revision": "official-docs-observed-2026-09-02",
    },
    {
        "source_id": "framework-qlib",
        "name": "Microsoft Qlib",
        "url": "https://qlib.readthedocs.io/en/latest/component/strategy.html",
        "observed_contract": "预测信号、组合策略、工作流和回测松耦合。",
        "decision": "reference_only",
        "reason": "吸收实验/信号/组合分层；不引入新的数据语义或运行时依赖。",
        "rights_status": "public_license",
        "revision": "official-docs-0.9.8.dev11-observed",
    },
    {
        "source_id": "framework-veighna",
        "name": "VeighNa",
        "url": "https://www.vnpy.com/docs/cn/index.html",
        "observed_contract": "CTA、组合、价差、期权、算法执行与回测模块化。",
        "decision": "reference_only",
        "reason": "吸收国内平台 API 识别词典和模块分类，不加载策略或交易接口。",
        "rights_status": "public_license",
        "revision": "official-docs-observed-2026-09-02",
    },
    {
        "source_id": "framework-hummingbot",
        "name": "Hummingbot",
        "url": "https://hummingbot.org/strategies/v2-strategies/",
        "observed_contract": "V2 Controller 产生 ExecutorAction，Executor 管理有限订单生命周期。",
        "decision": "reference_only",
        "reason": "吸收 Controller/Executor 分离；Dashboard 已标记不再积极维护，不作为产品底座。",
        "rights_status": "public_license",
        "revision": "strategy-v2-docs-observed-2026-09-02",
    },
    {
        "source_id": "framework-freqtrade",
        "name": "Freqtrade/FreqUI",
        "url": "https://docs.freqtrade.io/en/stable/backtesting/",
        "observed_contract": "加密回测、Dry Run、lookahead-analysis 和 recursive-analysis。",
        "decision": "reference_only",
        "reason": "吸收前视/递归偏差检查；其全量 DataFrame 回测语义必须由 AegisQuant PIT 门禁复核。",
        "rights_status": "public_license",
        "revision": "stable-docs-observed-2026-09-02",
    },
    {
        "source_id": "framework-openbb",
        "name": "OpenBB Workspace",
        "url": "https://docs.openbb.co/workspace",
        "observed_contract": "Widget 元数据把后端 API 映射为可组合研究工作区。",
        "decision": "design_reference",
        "reason": "仅吸收可组合工作区和元数据思想，P09 不实现看板或复制视觉资产。",
        "rights_status": "public_license",
        "revision": "official-docs-observed-2026-09-02",
    },
    {
        "source_id": "framework-grafana",
        "name": "Grafana",
        "url": "https://grafana.com/docs/grafana/latest/administration/provisioning/",
        "observed_contract": "数据源和 Dashboard 可通过版本化文件配置。",
        "decision": "defer_to_p16",
        "reason": "作为运维可观测性而非主业务看板；P09 只记录评审。",
        "rights_status": "public_license",
        "revision": "official-docs-observed-2026-09-02",
    },
    {
        "source_id": "user-reference-hkuds-ai-trader",
        "name": "HKUDS/AI-Trader",
        "url": "https://github.com/HKUDS/AI-Trader",
        "observed_contract": "README/OpenAPI 展示 FastAPI/React、Agent 注册、信号市场与复制交易接口。",
        "decision": "metadata_only_reject_active_integration",
        "reason": "未观察到根许可证文件；不调用 Skill、注册、外部 API、信号发布或复制交易，只借鉴显式 API 契约和前后台任务隔离。",
        "rights_status": "unknown",
        "revision": AI_TRADER_COMMIT,
    },
)


def _source_artifact(path: Path, *, source_id: str) -> SourceArtifact:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    return SourceArtifact(
        artifact_id=canonical_sha256(
            {"source_id": source_id, "relative_path": path.name, "sha256": digest}
        ),
        source_id=source_id,
        relative_path=path.name,
        kind=ArtifactKind.PYTHON,
        sha256=digest,
        size_bytes=len(raw),
        media_type="text/x-python",
        static_review_state=StaticReviewState.QUARANTINED,
    )


def _build_evidence() -> tuple[
    dict[str, dict[str, object]],
    dict[str, str],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, str],
]:
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    archive_root = RUNTIME / "archive"
    imported = ManualExportImporter(archive_root).import_path(FIXTURES / "joinquant_manual_export")
    package = archive_root / imported.archive_relative_path
    safe_artifact = next(item for item in imported.artifacts if item.kind is ArtifactKind.PYTHON)
    safe_path = package / "raw" / safe_artifact.relative_path
    safe_raw = safe_path.read_bytes()
    safe_scan = scan_source_bytes(
        source_id=imported.source_manifest.source_id,
        artifact=safe_artifact,
        raw=safe_raw,
    )
    extracted = extract_strategy_ir(
        strategy_id="p09-source-strategy",
        source_id=imported.source_manifest.source_id,
        artifact=safe_artifact,
        raw=safe_raw,
        scan=safe_scan,
    )
    audit = audit_strategy(
        strategy_ir=extracted.strategy_ir,
        scan=safe_scan,
        evidence_spans=extracted.evidence_spans,
        rights_status=RightsStatus.PUBLIC_LICENSE,
    )

    unsafe_path = FIXTURES / "unsafe_strategy.py"
    unsafe_artifact = _source_artifact(unsafe_path, source_id="p09-unsafe-fixture")
    unsafe_scan = scan_source_bytes(
        source_id=unsafe_artifact.source_id,
        artifact=unsafe_artifact,
        raw=unsafe_path.read_bytes(),
    )

    copied_ir = extracted.strategy_ir.model_copy(update={"strategy_id": "p09-source-strategy-copy"})
    behavior = (0, 1, 1, 0, -1, -1, 0, 1)
    fingerprints = tuple(
        build_fingerprint(
            strategy_ir=strategy_ir,
            raw_source=safe_raw,
            signal_series=behavior,
            trade_holding_series=behavior,
            factor_regime_series=(1, 1, 0, 0, -1, -1, 0, 1),
            residual_alpha_series=(0, 1, 2, 1, 0, -1, -2, -1),
        )
        for strategy_ir in (extracted.strategy_ir, copied_ir)
    )
    duplicate_clusters = cluster_duplicates(fingerprints)
    translations = translation_records()
    backtests = run_all_translation_candidates(ROOT)

    rights = (
        RightsRecord(
            source_id=imported.source_manifest.source_id,
            status=RightsStatus.PUBLIC_LICENSE,
            license_identifier="AegisQuant-Synthetic-Fixture-1.0",
            evidence_url="https://example.invalid/aegisquant-owned-fixture",
            public_text_export_allowed=True,
            internal_research_allowed=True,
            reviewed_at_utc=OBSERVED_AT,
        ),
        RightsRecord(
            source_id="joinquant-user-exports",
            status=RightsStatus.UNKNOWN,
            evidence_url="https://www.joinquant.com/",
            public_text_export_allowed=False,
            internal_research_allowed=True,
            reviewed_at_utc=OBSERVED_AT,
        ),
        RightsRecord(
            source_id="hkuds-ai-trader",
            status=RightsStatus.UNKNOWN,
            evidence_url="https://github.com/HKUDS/AI-Trader",
            public_text_export_allowed=False,
            internal_research_allowed=True,
            reviewed_at_utc=OBSERVED_AT,
        ),
    )
    discovery = normalize_public_candidates(
        (
            {
                "platform": "joinquant",
                "url": "https://www.joinquant.com/view/community",
                "title": "聚宽公开社区索引入口",
                "summary": "仅用于候选发现；正文等待用户合法手工导出。",
                "keywords": ["strategy", "backtest"],
            },
            {
                "platform": "github",
                "url": "https://github.com/HKUDS/AI-Trader",
                "title": "HKUDS/AI-Trader",
                "summary": "用户推荐的公开仓库元数据；不执行、不注册、不复制源码。",
                "keywords": ["agent", "trading", "api"],
            },
        )
    )

    payloads: dict[str, dict[str, object]] = {
        "P09_IMPORT_EVIDENCE.json": {
            "schema_version": "p09-import-evidence-v1",
            "fixture_source_id": imported.source_manifest.source_id,
            "package_sha256": imported.package_sha256,
            "raw_files_preserved": imported.raw_files_preserved,
            "sanitized_files_created": imported.sanitized_files_created,
            "artifact_hashes": {item.relative_path: item.sha256 for item in imported.artifacts},
            "source_code_executed": imported.source_code_executed,
            "notebook_kernel_started": imported.notebook_kernel_started,
            "real_user_export_imported": False,
            "real_source_status": "awaiting_user_export",
        },
        "P09_STATIC_ANALYSIS_EVIDENCE.json": {
            "schema_version": "p09-static-analysis-evidence-v1",
            "safe_report": safe_scan.model_dump(mode="json"),
            "unsafe_report": unsafe_scan.model_dump(mode="json"),
            "unsafe_categories": sorted({item.category for item in unsafe_scan.findings}),
            "source_code_executed": False,
            "execution_api_exposed": False,
        },
        "P09_STRATEGY_IR_EVIDENCE.json": {
            "schema_version": "p09-strategy-ir-evidence-v1",
            "strategy_ir": extracted.strategy_ir.model_dump(mode="json"),
            "evidence_spans": [item.model_dump(mode="json") for item in extracted.evidence_spans],
            "evidence_coverage": 1.0,
            "unsupported_assertions": list(extracted.unsupported_assertions),
            "audit": audit.model_dump(mode="json"),
            "source_performance_accepted": False,
            "ai_missing_parameters_fabricated": False,
        },
        "P09_RIGHTS_EVIDENCE.json": {
            "schema_version": "p09-rights-evidence-v1",
            "records": [item.model_dump(mode="json") for item in rights],
            "unknown_rights_public_text_exports": 0,
            "prohibited_content_exported": False,
        },
        "P09_DEDUPE_EVIDENCE.json": {
            "schema_version": "p09-dedupe-evidence-v1",
            "fingerprints": [item.model_dump(mode="json") for item in fingerprints],
            "clusters": [item.model_dump(mode="json") for item in duplicate_clusters],
            "layers": 7,
            "renamed_copy_detected": bool(duplicate_clusters),
        },
        "P09_TRANSLATION_EVIDENCE.json": {
            "schema_version": "p09-translation-evidence-v1",
            "translations": [item.model_dump(mode="json") for item in translations],
            "backtests": [item.model_dump(mode="json") for item in backtests],
            "candidate_count": len(backtests),
            "common_engine": "EVENT",
            "common_policy": "p06-backtest-v1",
            "synthetic_fixture": True,
            "source_code_reused": False,
            "source_return_used_as_evidence": False,
            "alpha_or_profit_claim": False,
        },
        "P09_FRAMEWORK_REVIEW_EVIDENCE.json": {
            "schema_version": "p09-framework-review-evidence-v1",
            "observed_at_utc": OBSERVED_AT.isoformat().replace("+00:00", "Z"),
            "frameworks": list(FRAMEWORKS),
            "required_framework_count": 8,
            "user_reference_count": 1,
            "external_framework_code_executed": False,
            "ai_trader_commit_observed": AI_TRADER_COMMIT,
            "ai_trader_license_file_observed": False,
            "ai_trader_active_integration": False,
        },
        "P09_DISCOVERY_EVIDENCE.json": {
            "schema_version": "p09-discovery-evidence-v1",
            "candidates": [item.model_dump(mode="json") for item in discovery],
            "network_fetch_performed_by_discovery_component": False,
            "access_bypass_attempted": False,
            "credentials_requested": False,
        },
        "P09_DEPENDENCY_CONTRACT.json": {
            "schema_version": "p09-dependency-contract-v1",
            "python_runtime": ".".join(map(str, sys.version_info[:3])),
            "versions": {
                name: importlib.metadata.version(name) for name in ("polars", "pydantic", "PyYAML")
            },
            "new_runtime_dependencies_added": False,
            "external_frameworks_installed_or_imported": False,
            "live_trading_locked": True,
        },
    }

    static_reports = {
        f"{safe_scan.source_id}.json": json.dumps(
            safe_scan.model_dump(mode="json"), ensure_ascii=False, indent=2
        )
        + "\n",
        f"{unsafe_scan.source_id}.json": json.dumps(
            unsafe_scan.model_dump(mode="json"), ensure_ascii=False, indent=2
        )
        + "\n",
        f"{safe_scan.source_id}.md": _static_markdown(safe_scan.model_dump(mode="json")),
        f"{unsafe_scan.source_id}.md": _static_markdown(unsafe_scan.model_dump(mode="json")),
    }
    markdown = _markdown_outputs(
        payloads=payloads,
        frameworks=FRAMEWORKS,
        duplicate_clusters=cast(
            "list[dict[str, object]]", payloads["P09_DEDUPE_EVIDENCE.json"]["clusters"]
        ),
        translations=cast(
            "list[dict[str, object]]", payloads["P09_TRANSLATION_EVIDENCE.json"]["translations"]
        ),
        backtests=cast(
            "list[dict[str, object]]", payloads["P09_TRANSLATION_EVIDENCE.json"]["backtests"]
        ),
    )
    source_rows = _source_catalog_rows(imported.package_sha256)
    strategy_rows = _strategy_catalog_rows(payloads)
    return payloads, markdown, source_rows, strategy_rows, static_reports


def _static_markdown(report: dict[str, object]) -> str:
    findings = cast("list[dict[str, object]]", report["findings"])
    lines = [
        f"# Static analysis: {report['source_id']}",
        "",
        f"- Artifact SHA-256: `{report['artifact_sha256']}`",
        f"- Review state: `{report['review_state']}`",
        "- Executable allowed: `false`",
        "- Source executed: `false`",
        "",
        "| Severity | Category | Line | Symbol | Message |",
        "|---|---|---:|---|---|",
    ]
    if findings:
        for item in findings:
            lines.append(
                f"| {item['severity']} | {item['category']} | {item['line']} | "
                f"`{item['symbol']}` | {item['message']} |"
            )
    else:
        lines.append("| INFO | none | 1 | `-` | 无危险调用；仍需人工语义审查。 |")
    lines.extend(("", "该报告只来自 AST/格式解析，未导入或执行来源代码。", ""))
    return "\n".join(lines)


def _markdown_outputs(
    *,
    payloads: dict[str, dict[str, object]],
    frameworks: tuple[dict[str, str], ...],
    duplicate_clusters: list[dict[str, object]],
    translations: list[dict[str, object]],
    backtests: list[dict[str, object]],
) -> dict[str, str]:
    primitive_lines = [
        "# Alpha Primitive Catalog",
        "",
        "这些原语是经济语义索引，不代表独立 Alpha，更不代表盈利。",
        "",
        "| Primitive | P09 state | Notes |",
        "|---|---|---|",
    ]
    translated = {
        "trend_slope",
        "breakout",
        "short_term_reversal",
        "carry",
        "basis_convergence",
        "seasonality",
    }
    for primitive in ALPHA_PRIMITIVES:
        state = "translated_candidate" if primitive in translated else "catalogued"
        primitive_lines.append(f"| `{primitive}` | {state} | 需要 PIT、成本和状态验证。 |")
    primitive_lines.append("")

    duplicate_lines = [
        "# Duplicate Clusters",
        "",
        "复制、改名或行为高度相关的策略只计一个独立 Alpha。",
        "",
    ]
    for cluster in duplicate_clusters:
        duplicate_lines.extend(
            (
                f"## `{cluster['cluster_id']}`",
                "",
                f"- Strategies: {', '.join(f'`{item}`' for item in cast('list[str]', cluster['strategy_ids']))}",
                f"- Matching layers: {', '.join(cast('list[str]', cluster['matching_layers']))}",
                "- Independent alpha count: `1`",
                "",
            )
        )

    failure_lines = [
        "# Failure Taxonomy",
        "",
        "| Tag | Meaning | Default action |",
        "|---|---|---|",
        "| INFORMATION_MISSING | 参数、规则或证据不完整 | 保持缺失，不允许 AI 补造 |",
        "| LEAKAGE | 未来函数或 available-time 风险 | 拒绝 |",
        "| SURVIVORSHIP_BIAS | 历史成分/可交易集合不可信 | 隔离并重建 PIT Universe |",
        "| COST_SENSITIVE | 成本未给出或结果对成本脆弱 | 使用统一成本重跑 |",
        "| EXECUTION_UNREALISTIC | 成交时点或可成交性不现实 | 使用事件引擎重写 |",
        "| OVERFIT_RISK | 参数/试验选择风险 | 记录预算、PBO/DSR 和负结果 |",
        "| TAIL_RISK_HIDDEN | 马丁格尔、无限补仓或风险控制缺失 | 拒绝/强制上限 |",
        "| LICENSE_RESTRICTED | 权利不允许公开或复用 | 只保留允许的内部元数据 |",
        "| DUPLICATE | 多名称共享同一经济语义 | 合并谱系，只计一个 Alpha |",
        "| REJECTED | 关键门禁失败 | 不执行、不发布 |",
        "",
    ]

    queue_lines = [
        "# Crypto Translation Queue",
        "",
        "| Target | Source concept | State | Required rechecks |",
        "|---|---|---|---|",
    ]
    for item in translations:
        queue_lines.append(
            f"| `{item['target_strategy_id']}` | {item['source_market_concept']} | "
            f"implemented_synthetic_validation | {', '.join(cast('list[str]', item['required_rechecks']))} |"
        )
    queue_lines.extend(
        (
            "",
            "真实来源导出到达后必须重新建立证据、审计和经济语义；当前三项不是来源策略复现。",
            "",
        )
    )

    scoreboard_lines = [
        "# Reproduction Scoreboard",
        "",
        "三项均为 AegisQuant 从零重写并使用同一 P06 事件引擎、规则和成本政策运行的合成验证。",
        "结果只证明订单→成交→账本→指标可复现，不证明 Alpha 或未来盈利。",
        "",
        "| Candidate | Engine | Orders/Fills | Net PnL | Total return | Economic hash |",
        "|---|---|---:|---:|---:|---|",
    ]
    for item in backtests:
        scoreboard_lines.append(
            f"| `{item['candidate']}` | {item['engine']} | {item['orders']}/{item['fills']} | "
            f"{item['net_pnl']} | {item['total_return']} | `{item['economic_event_hash']}` |"
        )
    scoreboard_lines.extend(
        (
            "",
            "真实聚宽来源复现：`NOT_RUN_STATIC_ONLY / awaiting_user_export`。",
            "外部来源收益采用：`false`；来源代码执行：`false`；Live trading：`locked`。",
            "",
        )
    )

    framework_lines = [
        "# Framework Review",
        "",
        "评审基于 2026-09-02 读取的官方稳定文档或项目主仓库元数据；未安装、导入或执行新框架。",
        "",
        "| Framework | Observed contract | Decision | Reason |",
        "|---|---|---|---|",
    ]
    for item in frameworks:
        framework_lines.append(
            f"| [{item['name']}]({item['url']}) | {item['observed_contract']} | "
            f"`{item['decision']}` | {item['reason']} |"
        )
    framework_lines.extend(
        (
            "",
            f"AI-Trader 固定观察 revision：`{AI_TRADER_COMMIT}`。根许可证文件未观察到，故权利为 `unknown`；",
            "其 Agent 注册、信号发布、复制交易和生产 API 与 AegisQuant 安全边界冲突，未接入。",
            "",
        )
    )

    request_lines = [
        "# P09 Source Request Queue",
        "",
        "当前状态：`awaiting_user_export`。后续如用户愿意，可在本人有权访问的页面手工导出以下资料；",
        "不要在聊天、Markdown 或命令行中提供密码、Cookie、验证码、API Secret 或 session 文件。",
        "",
        "1. manifest.yaml（URL、标题、作者、发布时间、导出时间、访问权和许可状态）。",
        "2. 正文 Markdown/原始 HTML、完整 Python、Notebook、评论和允许的附件。",
        "3. 回测逐笔成交、费用、滑点、样本外说明和作者后续修正。",
        "4. 评论中关于未来函数、幸存者、不可成交、失效状态和负结果的讨论。",
        "5. 米筐、BigQuant 或其他平台的同类合法手工导出，可使用相同包结构。",
        "",
        "JQData 仅在未来明确数据假设需要且用户已在本地秘密库配置只读引用时评估；它不是社区文章 API。",
        "",
    ]
    del payloads
    return {
        "ALPHA_PRIMITIVE_CATALOG.md": "\n".join(primitive_lines),
        "DUPLICATE_CLUSTERS.md": "\n".join(duplicate_lines),
        "FAILURE_TAXONOMY.md": "\n".join(failure_lines),
        "CRYPTO_TRANSLATION_QUEUE.md": "\n".join(queue_lines),
        "REPRODUCTION_SCOREBOARD.md": "\n".join(scoreboard_lines),
        "FRAMEWORK_REVIEW.md": "\n".join(framework_lines),
        "SOURCE_REQUEST_QUEUE.md": "\n".join(request_lines),
    }


def _source_catalog_rows(package_sha256: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "source_id": "jq_synthetic_trend_20260902",
            "source_type": "manual_export_fixture",
            "platform": "joinquant",
            "title": "P09 项目自有合成趋势示例",
            "url": "https://www.joinquant.com/view/community/detail/synthetic",
            "rights_status": "public_license",
            "access_status": "synthetic_fixture_only",
            "observed_revision": package_sha256,
            "content_archived": True,
            "public_text_export_allowed": True,
            "notes": "项目自有夹具，不是真实聚宽正文。",
        },
        {
            "source_id": "joinquant-user-exports",
            "source_type": "manual_export_queue",
            "platform": "joinquant",
            "title": "用户合法手工导出队列",
            "url": "https://www.joinquant.com/",
            "rights_status": "unknown",
            "access_status": "awaiting_user_export",
            "observed_revision": "none",
            "content_archived": False,
            "public_text_export_allowed": False,
            "notes": "未请求密码、Cookie 或验证码。",
        },
    ]
    for item in FRAMEWORKS:
        rows.append(
            {
                "source_id": item["source_id"],
                "source_type": "framework_review",
                "platform": "github" if "github.com" in str(item["url"]) else "official_docs",
                "title": item["name"],
                "url": item["url"],
                "rights_status": item["rights_status"],
                "access_status": "metadata_reviewed",
                "observed_revision": item["revision"],
                "content_archived": False,
                "public_text_export_allowed": False,
                "notes": item["decision"],
            }
        )
    return sorted(rows, key=lambda item: str(item["source_id"]))


def _strategy_catalog_rows(payloads: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    dedupe = payloads["P09_DEDUPE_EVIDENCE.json"]
    clusters = cast("list[dict[str, object]]", dedupe["clusters"])
    cluster_id = str(clusters[0]["cluster_id"])
    ir = cast("dict[str, object]", payloads["P09_STRATEGY_IR_EVIDENCE.json"]["strategy_ir"])
    rows: list[dict[str, object]] = []
    for strategy_id, state in (
        ("p09-source-strategy", "static_only"),
        ("p09-source-strategy-copy", "synthetic_duplicate_control"),
    ):
        rows.append(
            {
                "strategy_id": strategy_id,
                "source_id": "jq_synthetic_trend_20260902",
                "rights_status": "public_license",
                "strategy_ir_sha256": canonical_sha256(ir),
                "audit_tags": "PARTIAL|SURVIVORSHIP_BIAS",
                "duplicate_cluster_id": cluster_id,
                "translation_status": "not_translated",
                "reproduction_status": state,
                "external_source_return_used": False,
                "execution_allowed": False,
            }
        )
    translation_payload = payloads["P09_TRANSLATION_EVIDENCE.json"]
    for item in cast("list[dict[str, object]]", translation_payload["backtests"]):
        rows.append(
            {
                "strategy_id": item["candidate"],
                "source_id": "aegisquant-from-scratch",
                "rights_status": "project_owned",
                "strategy_ir_sha256": item["code_sha256"],
                "audit_tags": "PARTIAL|REGIME_DEPENDENT",
                "duplicate_cluster_id": "none",
                "translation_status": "implemented",
                "reproduction_status": "synthetic_event_backtest_passed",
                "external_source_return_used": False,
                "execution_allowed": False,
            }
        )
    return sorted(rows, key=lambda item: str(item["strategy_id"]))


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    frame = pl.DataFrame(rows, orient="row")
    frame.write_parquet(path, compression="zstd", statistics=True)


def _verify_parquet(path: Path, expected: list[dict[str, object]]) -> None:
    if not path.is_file() or pl.read_parquet(path).to_dicts() != expected:
        raise RuntimeError(f"stale P09 Parquet catalog: {path.relative_to(ROOT)}")


def generate(*, check: bool) -> None:
    payloads, markdown, source_rows, strategy_rows, static_reports = _build_evidence()
    if check:
        for name, expected in payloads.items():
            path = DATA / name
            if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != expected:
                raise RuntimeError(f"stale P09 JSON evidence: {name}")
        for name, expected in markdown.items():
            path = INTELLIGENCE / name
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                raise RuntimeError(f"stale P09 report: {name}")
        for name, expected in static_reports.items():
            path = STATIC_REPORTS / name
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                raise RuntimeError(f"stale P09 static report: {name}")
        _verify_parquet(INTELLIGENCE / "SOURCE_CATALOG.parquet", source_rows)
        _verify_parquet(INTELLIGENCE / "STRATEGY_CATALOG.parquet", strategy_rows)
        print("P09 evidence verified: 9 JSON, 7 Markdown, 4 static reports, 2 Parquet")
        return
    DATA.mkdir(parents=True, exist_ok=True)
    INTELLIGENCE.mkdir(parents=True, exist_ok=True)
    STATIC_REPORTS.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (DATA / name).write_bytes(canonical_json_bytes(payload))
    for name, content in markdown.items():
        (INTELLIGENCE / name).write_text(content, encoding="utf-8", newline="\n")
    for name, content in static_reports.items():
        (STATIC_REPORTS / name).write_text(content, encoding="utf-8", newline="\n")
    _write_parquet(INTELLIGENCE / "SOURCE_CATALOG.parquet", source_rows)
    _write_parquet(INTELLIGENCE / "STRATEGY_CATALOG.parquet", strategy_rows)
    print("P09 evidence generated: 9 JSON, 7 Markdown, 4 static reports, 2 Parquet")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--candidate", choices=tuple(item.value for item in MigrationCandidateKind))
    arguments = parser.parse_args()
    if arguments.candidate is not None:
        _, evidence = run_translation_candidate(
            candidate=MigrationCandidateKind(arguments.candidate), project_root=ROOT
        )
        print(json.dumps(evidence.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0
    generate(check=arguments.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
