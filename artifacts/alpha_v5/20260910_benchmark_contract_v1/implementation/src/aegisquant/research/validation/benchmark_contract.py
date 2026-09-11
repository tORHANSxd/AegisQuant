"""B3 benchmark contracts and one read-only report job; no strategy/market loader."""

from __future__ import annotations

import csv
import difflib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from aegisquant.data.hashing import canonical_sha256, ensure_sha256, sha256_file
from aegisquant.research.validation.evidence_contract import (
    BASE,
    LOCKS,
    MONEY_TOLERANCE,
    ZERO_BUDGETS,
    EvidenceReader,
    Row,
    audit_existing_files,
    check_calendar_contract,
    checked_path,
    claim_output,
    decimal,
    require,
    safety_literals,
    seal_output,
    statistics_identity,
    utc,
    write_json_exclusive,
    zero_budget_guard,
)
from aegisquant.research.validation.experiment_registry import registered_run
from aegisquant.research.validation.paired_bootstrap import LOG_GROWTH_ESTIMAND

ARMS = {
    "F5_MATCHED": ("ALWAYS_HOLD", "G0"),
    "SIMPLE_TREND": ("TREND_10_40", "G0"),
    "G1_PASSIVE": ("ALWAYS_HOLD", "G1"),
    "G1": ("TREND_10_40", "G1"),
    "PASSIVE_FIXED_QTY": ("ALWAYS_HOLD", "FIXED_QTY"),
    "TREND_FIXED_QTY": ("TREND_10_40", "FIXED_QTY"),
}
PRIMARY_COMPARISONS = ("G1-CASH", "G1-F5_MATCHED", "G1-G1_PASSIVE", "G1-SIMPLE_TREND")
SYMBOLS = ("BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
MODIFIED_FILES = (
    "src/aegisquant/research/validation/paired_bootstrap.py",
    "scripts/audit_alpha_profitability_root_causes.py",
)
NEW_FILES = (
    "src/aegisquant/research/validation/benchmark_contract.py",
    "scripts/run_alpha_v5_benchmark_diagnostics.py",
    "configs/research/alpha_v5_benchmark_contract.yaml",
    "tests/alpha_v5/test_benchmark_contract.py",
    "docs/research/alpha_v5_benchmark_contract.md",
)
B3_FILES = (*MODIFIED_FILES, *NEW_FILES)
COMMON_FIELDS = (
    "input_snapshot_sha256",
    "risk_policy_sha256",
    "execution_policy_sha256",
    "capital_mode",
    "cost_mode",
    "cost_multiplier",
    "initial_cash",
    "symbols",
    "terminal_exit",
    "risk_sizing_basis",
)


def validate_config(config: dict[str, Any]) -> None:
    match = re.fullmatch(r"alpha-r5-benchmark-contract-(\d{8})-v([1-9]\d*)", config["generation"])
    require(match is not None, "AQ-BENCHMARK-GENERATION")
    if match is None:
        return
    require(
        config["output"] == f"artifacts/alpha_v5/{match[1]}_benchmark_contract_v{match[2]}",
        "AQ-BENCHMARK-OUTPUT",
    )
    require(
        config["scope"] == "B3_CONTRACTS_READ_ONLY_AND_SYNTHETIC_TESTS"
        and config["branch_required"] == "main"
        and config["source_head"] == BASE,
        "AQ-BENCHMARK-SCOPE",
    )
    require(
        config["budgets"]
        == {"contract_jobs": 1, "historical_bootstrap_runs": 0, **dict.fromkeys(ZERO_BUDGETS, 0)},
        "AQ-BENCHMARK-NONZERO-RESEARCH-BUDGET",
    )
    require(
        config["production_policy"] == "CASH"
        and config["research_conclusion"] == "NO_PROVEN_ALPHA"
        and all(config[key] is False for key in LOCKS),
        "AQ-BENCHMARK-SAFETY-LOCK",
    )
    require(tuple(config["symbols"]) == SYMBOLS, "AQ-BENCHMARK-SYMBOLS")
    require(config["cost_multipliers"] == ["1", "1.5", "2"], "AQ-BENCHMARK-COST-SCENARIOS")
    require(
        config["period_start"] == "2022-04-01T00:00:00+00:00"
        and config["period_end"] == "2025-10-01T00:00:00+00:00"
        and config["initial_cash_per_symbol"] == "10000",
        "AQ-BENCHMARK-DEVELOPMENT-BOUNDARY",
    )
    stats = config["statistics"]
    require(
        stats["estimand_id"] == LOG_GROWTH_ESTIMAND
        and stats["sampling"] == "UTC_DAY"
        and tuple(stats["comparisons"]) == PRIMARY_COMPARISONS
        and stats["repetitions"] == 10000
        and stats["seed"] == 20260910
        and stats["block_rule"] == "AUTO_MAX_RETURN_AND_SQUARED_RETURN_CLIPPED_2_TO_N_DIV_4"
        and stats["correction"] == "HOLM_ALL_FOUR"
        and stats["block_sensitivity_multipliers"] == ["0.5", "2"],
        "AQ-BENCHMARK-STATISTICAL-REGISTRATION",
    )
    require(
        config["historical_matrix_inputs"] is None
        and config["historical_matrix_executed"] is False,
        "AQ-BENCHMARK-HISTORICAL-INPUT-NOT-AUTHORIZED",
    )


def build_benchmark_contract(r5_manifest: dict[str, Any]) -> dict[str, Any]:
    # Reuse the actual frozen control constructors, without calling a replay entry.
    from scripts.run_alpha_v5_research import controls

    config = r5_manifest["config"]
    policies: dict[str, Any] = {}
    for name in ("G0", "G1"):
        buffer, resize = controls(config, name)
        serialized: list[dict[str, Any] | None] = []
        for policy in (buffer, resize):
            serialized.append(
                {
                    key: str(value)
                    if isinstance(value, Decimal)
                    else int(value.total_seconds())
                    if isinstance(value, timedelta)
                    else value
                    for key, value in asdict(policy).items()
                }
                if policy is not None
                else None
            )
        policies[name] = {"buffer": serialized[0], "resize": serialized[1]}
    policies["FIXED_QTY"] = {
        "ordinary_target": "CURRENT_EXECUTED_QUANTITY_AFTER_ENTRY",
        "entry_sizing": "SAME_FROZEN_A1_GATE",
        "hard_exit_and_cap": "EXISTING_SHARED_HARD_RISK_PATH",
        "pending_and_partial_fills": "EXISTING_SIGNED_PENDING_MANAGER_AND_ACTUAL_FILLED_QUANTITY",
        "execution_adapter": "NOT_IMPLEMENTED_IN_ZERO_REPLAY_CONTRACT_BATCH",
    }
    return {
        "status": "CONTRACT_DEFINED_HISTORY_NOT_COLLECTED",
        "candidate": "G1",
        "arms": {
            arm: {
                "signal": signal,
                "control": control,
                "control_sha256": canonical_sha256(policies[control]),
                "configuration_sha256": canonical_sha256(
                    {"signal": signal, "control": policies[control]}
                ),
            }
            for arm, (signal, control) in ARMS.items()
        },
        "controls": policies,
        "shared_gate": r5_manifest["gate"],
        "shared_gate_sha256": canonical_sha256(r5_manifest["gate"]),
        "risk_matching": "SAME_EX_ANTE_LIMITS_AND_INPUTS_NOT_EQUAL_REALIZED_VOLATILITY",
        "capital_mode": "FIVE_EQUAL_INITIAL_SLEEVES_NO_TRANSFERS",
        "initial_cash_per_symbol": "10000",
        "initial_total_cash": "50000",
        "terminal_exit": "EVALUATION_END_NEXT_OPEN_EXIT_PAID_BOUNDARY_INCLUDED",
        "signal_source": "scripts/run_alpha_r4.py::run_sleeve; F5 always-true override; existing 10/40 trend",
        "controls_source": "scripts/run_alpha_v5_research.py::controls; frozen G0/G1",
        "engine_source": "aegisquant.research.validation.cat_replay::replay_cat",
        "historical_evidence": "NOT_COLLECTED",
        "legacy_reference_only": ["F0", "F3", "F5", "99PCT_BUY_AND_HOLD"],
        "f5_matched_is_not_relabelled_old_f5": True,
        "future_matrix_slots": len(ARMS) * len(SYMBOLS) * 3,
        "future_matrix_slots_authorized_now": 0,
        "synthetic_equivalence_is_engine_proof": False,
    }


def cash_reference(*, start: str, end: str, capital: Decimal) -> list[dict[str, Any]]:
    require(capital.is_finite() and capital > 0, "AQ-BENCHMARK-CASH-CAPITAL")
    begin, finish = utc(start), utc(end)
    require(begin < finish, "AQ-BENCHMARK-CASH-PERIOD")
    require(
        all(
            t.hour % 4 == 0 and not t.minute and not t.second and not t.microsecond
            for t in (begin, finish)
        ),
        "AQ-BENCHMARK-CALENDAR-GRID",
    )
    rows: list[dict[str, Any]] = []
    time = begin
    while time <= finish:
        rows.append(
            {
                "time": time.isoformat(),
                "equity": str(capital),
                "cash": str(capital),
                "position_value": "0",
                "cash_flow": "0",
                "cost": "0",
                "orders": 0,
                "fills": 0,
            }
        )
        time += timedelta(hours=4)
    return rows


def validate_benchmark_paths(
    paths: Mapping[str, Row], contract: Row, *, start: str, end: str
) -> dict[str, Any]:
    """Check supplied economic paths; this does not prove an engine generated them."""
    require(set(paths) == {*ARMS, "CASH"}, "AQ-BENCHMARK-INCOMPLETE-MATRIX")
    reference = paths["G1"]["common"]
    require(set(reference) == set(COMMON_FIELDS), "AQ-BENCHMARK-COMMON-CONTRACT-FIELDS")
    require(
        reference["capital_mode"] == "FIVE_EQUAL_INITIAL_SLEEVES_NO_TRANSFERS"
        and reference["cost_mode"] == "REDECIDE_FUNDED"
        and reference["cost_multiplier"] in {"1", "1.5", "2"}
        and decimal(reference["initial_cash"]) == Decimal("50000")
        and reference["symbols"] == list(SYMBOLS)
        and reference["terminal_exit"] == "EVALUATION_END_NEXT_OPEN_EXIT_PAID_BOUNDARY_INCLUDED"
        and reference["risk_sizing_basis"] == "EX_ANTE_PRECEDING_DATA",
        "AQ-BENCHMARK-COMMON-ACCOUNT-OR-RISK",
    )
    for field in COMMON_FIELDS[:3]:
        ensure_sha256(reference[field], field_name=field)
    require(
        reference["risk_policy_sha256"] == contract["shared_gate_sha256"],
        "AQ-BENCHMARK-UNBOUND-RISK-POLICY",
    )
    cash = paths["CASH"]
    expected_cash = cash_reference(start=start, end=end, capital=Decimal("50000"))
    require(cash["orders"] == [] and cash["fills"] == [], "AQ-BENCHMARK-CASH-TRADES")
    calendars: list[list[Any]] = []
    all_ready: list[list[bool]] = []
    risk_ready: list[list[bool]] = []
    for arm, path in paths.items():
        require(
            path["definition"]
            == ({"signal": "CASH", "control": "CASH"} if arm == "CASH" else contract["arms"][arm]),
            "AQ-BENCHMARK-ARM-DEFINITION-CONFLICT",
        )
        require(path["common"] == reference, "AQ-BENCHMARK-MIXED-COMMON-CONTRACT")
        rows = path["rows"]
        calendars.append(
            check_calendar_contract(rows, start=start, end=end, interval=timedelta(hours=4))
        )
        require(decimal(rows[0]["equity"]) == Decimal("50000"), "AQ-BENCHMARK-INITIAL-CASH")
        require(
            decimal(rows[0]["position_value"]) == 0 and decimal(rows[-1]["position_value"]) == 0,
            "AQ-BENCHMARK-NONFLAT-ACCOUNT-BOUNDARY",
        )
        ready: list[bool] = []
        risk: list[bool] = []
        for index, row in enumerate(rows):
            equity, available_cash, position = (
                decimal(row[name]) for name in ("equity", "cash", "position_value")
            )
            require(
                equity > 0
                and available_cash >= 0
                and position >= 0
                and abs(equity - available_cash - position) <= MONEY_TOLERANCE
                and decimal(row["cash_flow"]) == 0,
                "AQ-BENCHMARK-CAPITAL-IDENTITY",
            )
            require(
                type(row["risk_ready"]) is bool and type(row["signal_ready"]) is bool,
                "AQ-BENCHMARK-UNKNOWN-READINESS",
            )
            ready.append(row["risk_ready"] and row["signal_ready"])
            risk.append(row["risk_ready"])
            if arm == "CASH":
                require(row["risk_ready"] and row["signal_ready"], "AQ-BENCHMARK-CASH-READINESS")
                require(
                    all(row[key] == value for key, value in expected_cash[index].items()),
                    "AQ-BENCHMARK-CASH-IDENTITY",
                )
        all_ready.append(ready)
        if arm != "CASH":
            risk_ready.append(risk)
    require(all(times == calendars[0] for times in calendars), "AQ-BENCHMARK-MIXED-CALENDAR")
    require(
        all(flags == risk_ready[0] for flags in risk_ready), "AQ-BENCHMARK-MIXED-RISK-READINESS"
    )
    return {
        "kind": "SUPPLIED_PATH_CONTRACT_CHECK_NOT_ENGINE_OR_LEDGER_PROOF",
        "full_calendar": [time.isoformat() for time in calendars[0]],
        "common_ready": [all(flags) for flags in zip(*all_ready, strict=True)],
        "full_calendar_observations": len(calendars[0]),
        "engine_equivalence": "NOT_VERIFIED",
    }


def assert_same_configuration_paths(left: Row, right: Row) -> None:
    """Compare normalized economic payloads supplied by the caller, not run IDs."""
    require(
        left["definition"] == right["definition"] and left["common"] == right["common"],
        "AQ-BENCHMARK-DIFFERENT-CONFIGURATION",
    )
    require(
        all(left[key] == right[key] for key in ("rows", "orders", "fills")),
        "AQ-BENCHMARK-SAME-CONFIG-DIFFERENT-ECONOMIC-PATH",
    )


def _test_receipts(root: Path, stage: Path) -> tuple[list[dict[str, Any]], int]:
    records = json.loads((stage / "validation_records.json").read_text(encoding="utf-8"))
    latest = {row["check"]: row for row in records}
    hashes = {name: sha256_file(checked_path(root, name)) for name in B3_FILES}
    for check in ("pytest", "ruff", "format", "pyright"):
        require(
            latest.get(check, {}).get("exit_code") == 0
            and latest[check]["source_sha256"] == hashes,
            f"AQ-BENCHMARK-STALE-VALIDATION:{check}",
        )
    require(NEW_FILES[3] in latest["pytest"]["command"], "AQ-BENCHMARK-MISSING-PURE-TEST")
    cases = ElementTree.parse(stage / "pytest_results.xml").getroot().findall(".//testcase")  # noqa: S314 -- local pytest receipt.
    require(
        bool(cases)
        and all(not any(c.tag in {"failure", "error", "skipped"} for c in case) for case in cases),
        "AQ-BENCHMARK-TEST-FAILURE-OR-SKIP",
    )
    return records, len(cases)


def run_contract_job(
    root: Path, config: dict[str, Any], stage: Path, git_state: dict[str, str]
) -> Path:
    validate_config(config)
    require(git_state == {"head": BASE, "branch": "main"}, "AQ-BENCHMARK-GIT-IDENTITY")
    baseline = json.loads((stage / "baseline_workspace.json").read_text(encoding="utf-8"))
    require(
        baseline["head"] == BASE
        and baseline["branch"] == "main"
        and Path(baseline["root"]).resolve() == root.resolve()
        and set(baseline["allowed_modifications"]) == set(MODIFIED_FILES),
        "AQ-BENCHMARK-PREFLIGHT",
    )
    protected = {
        **baseline,
        "files": {
            name: row for name, row in baseline["files"].items() if name not in MODIFIED_FILES
        },
    }
    records, count = _test_receipts(root, stage)
    frozen = [root / Path(binding["path"]).parent for binding in config["sources"].values()]
    output = claim_output(root, config["output"], frozen_roots=frozen)
    counters: dict[str, int] = dict.fromkeys(ZERO_BUDGETS, 0)
    reader = EvidenceReader(root)
    run_id = config["generation"] + ":CONTRACT_REPORT"
    try:
        with registered_run(  # noqa: SIM117 -- journal remains outside the write guard.
            output,
            run_id,
            planned_run_ids=[run_id],
            bindings={"kind": "B3_CONTRACT_REPORT_NOT_ALPHA_TRIAL"},
        ):
            with zero_budget_guard(output, root, counters):
                write_json_exclusive(
                    output / "preregistration.json", {"config": config, "planned_run_ids": [run_id]}
                )
                before = audit_existing_files(root, protected)
                for name in (
                    "baseline_workspace.json",
                    "workspace_before.patch",
                    "version_graph.txt",
                    "validation_records.json",
                    "test_commands_and_results.txt",
                    "pytest_results.xml",
                ):
                    group = (
                        "validation"
                        if name
                        in {
                            "validation_records.json",
                            "test_commands_and_results.txt",
                            "pytest_results.xml",
                        }
                        else "preflight"
                    )
                    target = output / group / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        stream.write(checked_path(stage, name).read_bytes())
                patch = ""
                for name in B3_FILES:
                    source = checked_path(root, name)
                    previous = (
                        checked_path(stage, "before/" + name) if name in MODIFIED_FILES else None
                    )
                    if previous is not None:
                        require(
                            sha256_file(previous) == baseline["files"][name]["sha256"],
                            "AQ-BENCHMARK-BEFORE-COPY",
                        )
                        target = output / "before" / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("xb") as stream:
                            stream.write(previous.read_bytes())
                    target = output / "implementation" / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        stream.write(source.read_bytes())
                    patch += "".join(
                        difflib.unified_diff(
                            previous.read_text(encoding="utf-8").splitlines(keepends=True)
                            if previous
                            else [],
                            source.read_text(encoding="utf-8").splitlines(keepends=True),
                            fromfile="a/" + name if previous else "/dev/null",
                            tofile="b/" + name,
                        )
                    )
                with (output / "changes_this_batch.patch").open(
                    "x", encoding="utf-8", newline="\n"
                ) as stream:
                    stream.write(patch)
                sources: dict[str, Any] = {}
                for name, binding in config["sources"].items():
                    path = reader.path(binding["path"])
                    require(
                        sha256_file(path) == binding["sha256"], f"AQ-BENCHMARK-FROZEN-SOURCE:{name}"
                    )
                    sources[name] = (
                        json.loads(path.read_text(encoding="utf-8"), parse_float=str)
                        if name == "r5_statistics"
                        else json.loads(path.read_text(encoding="utf-8"))
                    )
                r5 = sources["r5_manifest"]
                require(r5["source_head"] == BASE, "AQ-BENCHMARK-SOURCE-HEAD")
                locks = safety_literals(reader, r5)
                contract = build_benchmark_contract(r5)
                write_json_exclusive(output / "benchmark_contract.json", contract)
                write_json_exclusive(
                    output / "legacy_statistics_identity.json",
                    statistics_identity(sources["r5_statistics"], r5["config"]["statistics"]),
                )
                with (output / "legacy_paired_statistics_original.json").open("xb") as stream:
                    stream.write(
                        reader.path(config["sources"]["r5_statistics"]["path"]).read_bytes()
                    )
                write_json_exclusive(
                    output / "primary_comparisons.json",
                    {
                        "status": "NOT_COLLECTED",
                        "statistics": config["statistics"],
                        "comparisons": {
                            name: {
                                "estimand_id": LOG_GROWTH_ESTIMAND,
                                "observed": None,
                                "ci95": None,
                                "one_sided_p_value": None,
                                "holm_adjusted_p_value": None,
                            }
                            for name in PRIMARY_COMPARISONS
                        },
                        "legacy_results_cannot_populate_new_comparisons": True,
                    },
                )
                cash = cash_reference(
                    start=config["period_start"], end=config["period_end"], capital=Decimal("50000")
                )
                with (output / "cash_full_calendar.csv").open(
                    "x", encoding="utf-8", newline=""
                ) as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(cash[0]))
                    writer.writeheader()
                    writer.writerows(cash)
                write_json_exclusive(
                    output / "calendar_contract.json",
                    {
                        "kind": "DETERMINISTIC_CASH_REFERENCE_NOT_NEW_MARKET_EVIDENCE",
                        "start": config["period_start"],
                        "end_inclusive_paid_terminal_boundary": config["period_end"],
                        "interval_seconds": 14400,
                        "cash_four_hour_points": len(cash),
                        "cash_utc_daily_points": sum(utc(row["time"]).hour == 0 for row in cash),
                        "required_arms": [*ARMS, "CASH"],
                        "historical_common_ready": None,
                        "risk_arm_calendars": "NOT_COLLECTED",
                        "flat_periods_must_remain": True,
                        "common_ready_is_supplement_not_date_selection": True,
                    },
                )
                write_json_exclusive(
                    output / "risk_and_factor_attribution.json",
                    {
                        "status": "NOT_COLLECTED",
                        "factorial_summary": None,
                        "estimator": "scripts.audit_alpha_profitability_root_causes::benchmark_factorial_attribution",
                        "pit_market_factor": "NOT_RECEIVED",
                        "ex_ante_risk_forecasts": "NOT_RECEIVED",
                        "market_alpha_regression": None,
                        "full_sample_realized_vol_sizing_allowed": False,
                        "factorial_effects_are_descriptive_not_causal_alpha": True,
                    },
                )
                write_json_exclusive(
                    output / "same_fill_shadow_contract.json",
                    {
                        "new_matrix_shadow": "NOT_COLLECTED",
                        "cost_mode": "SAME_FILL_SHADOW",
                        "reuse": "aegisquant.research.validation.evidence_contract::audit_cost_path",
                        "required_identity": [
                            "time",
                            "quantity",
                            "side",
                            "reference_price",
                            "inventory",
                        ],
                        "worse_cost_must_not_improve_shadow_wealth": True,
                        "funded_monotonicity_required": False,
                        "funding_feasibility_claimed": False,
                        "old_audit_reference": config["sources"]["b0_cost_audit"],
                        "old_audit": sources["b0_cost_audit"],
                    },
                )
                gaps = [
                    {"item": "six_risk_arm_history_and_raw_paths", "status": "NOT_COLLECTED"},
                    {
                        "item": "fixed_quantity_engine_adapter",
                        "status": "NOT_IMPLEMENTED_ZERO_REPLAY_BATCH",
                    },
                    {
                        "item": "actual_engine_same_configuration_equivalence",
                        "status": "NOT_VERIFIED",
                    },
                    {"item": "historical_primary_statistics_and_holm", "status": "NOT_COLLECTED"},
                    {"item": "pit_universe", "status": sources["b2_safety"]["strict_data_quality"]},
                    {"item": "pit_factor_and_causal_risk_forecasts", "status": "NOT_RECEIVED"},
                ]
                write_json_exclusive(
                    output / "evidence_gaps.json", {"gaps": gaps, "promotion_admitted": False}
                )
                after = audit_existing_files(root, protected)
                write_json_exclusive(
                    output / "safety_and_budget_audit.json",
                    {
                        "actual": {"contract_jobs": 1, "historical_bootstrap_runs": 0, **counters},
                        "authorized": config["budgets"],
                        "before": before,
                        "after": after,
                        "live_lock_literals": locks,
                        "production_policy": "CASH",
                        "research_conclusion": "NO_PROVEN_ALPHA",
                        **dict.fromkeys(LOCKS, False),
                        "alpha_trials": 0,
                        "promotion_admitted": False,
                    },
                )
                write_json_exclusive(
                    output / "source_and_version_bindings.json",
                    {
                        "generation": config["generation"],
                        **git_state,
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
                report = [
                    "# B3 共同风险基准：契约与合成验证",
                    "",
                    "**NO_PROVEN_ALPHA / CASH；ML、纸面准入、实盘及订单提交全部关闭。**",
                    "",
                    f"Generation：{config['generation']}；已有 main {BASE}，绑定冻结 R5 v3、B0/B1 v2 和 B2 v1。",
                    f"本批 {count} 项限定纯测试、Ruff、格式和类型检查通过；{len(records)} 条实际检查记录（含失败尝试）全部保存。",
                    "已完成六风险臂＋CASH契约、只读入口、完整现金日历、2×3描述性归因和配对对数净收益统计接口。",
                    "历史策略回放、真实模型拟合、真实校准拟合、最终留出访问、真实订单及历史统计重采样均为 0。",
                    "",
                    "两个信号固定为始终持有、现有10/40趋势；三类控制为G0/F3、原G1、入场后数量固定且保留硬退出/硬上限。",
                    "G0/G1控制复用现有构造函数；数量固定臂本批仅定义契约，执行适配与真实引擎等价尚未完成。",
                    "相同事前限制不保证实现波动相同；禁止以全样本实现波动反推交易权重。账户仍为五个10,000 USDT独立sleeve，无跨币资金转移。",
                    "同配置路径测试只验证提供的经济记录比较器，不冒充实际引擎会产生相同订单。",
                    "",
                    "新的四项主要比较：G1 对 CASH、F5_MATCHED、G1_PASSIVE、SIMPLE_TREND。区间和单侧p值使用同一平均对数净收益差estimand，UTC日采样、同时间块联合抽样、四项一起Holm。",
                    "新矩阵、归因、四项统计及影子成本均 NOT_COLLECTED；旧F0–F5及旧G1曲线不改名填入。旧九项比较原字节及不同CI/p estimand身份保留，不重算历史显著性。",
                    f"现金参考保留 {len(cash)} 个四小时点和付费退出边界；它是确定性参考，不证明六个风险臂已具备同一日历。",
                    "",
                    "B2仍缺真实PIT资料；真实因子、事前风险及完整执行证据也不足，全部缺口见 evidence_gaps.json。合成通过不能取得研究或交易晋级。",
                    "方案90次历史矩阵仅记录为未来规模，当前授权槽位0；本批只消费1次契约报告作业。",
                    f"保护范围内 {after['files_checked']} 个既有文件未变；两处修改的原字节、七个实施文件和本批补丁已封存。",
                    "本 generation 仅封存 B3 契约；后续工程按各自范围和证据门槛继续，历史矩阵、真实拟合及最终留出保持关闭。",
                    "",
                ]
                with (output / "report.md").open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write("\n".join(report))
    except BaseException as error:
        write_json_exclusive(
            output / "failure.json",
            {
                "error": f"{type(error).__name__}: {error}",
                "actual": {"contract_jobs": 1, "historical_bootstrap_runs": 0, **counters},
                "kind": "B3_CONTRACT_REPORT_NOT_ALPHA_TRIAL",
            },
        )
        seal_output(output)
        raise
    seal_output(output)
    return output
