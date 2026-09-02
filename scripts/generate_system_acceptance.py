"""Generate or verify the consolidated P00-P18 formal-acceptance audit."""

from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

import yaml

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT_DIR: Final = Path("reports/acceptance")
NEGATIVE_AUDIT_FLAG: Final = bool(0)
DEFERRED_PHASES: Final = tuple(f"P{number:02d}" for number in range(5, 19))
EXPECTED_ACCEPTANCE_COUNTS: Final = {
    "P05": 6,
    "P06": 6,
    "P07": 6,
    "P08": 7,
    "P09": 6,
    "P10": 10,
    "P11": 7,
    "P12": 7,
    "P13": 6,
    "P14": 6,
    "P15": 7,
    "P16": 7,
    "P17": 5,
    "P18": 7,
}
BLOCKED_REQUIREMENTS: Final = {
    "P12-A01": (
        "AQ-SYSTEM-ACC-REAL-TESTNET-MISSING",
        "任务书要求未提供 Testnet 凭据时将真实 Testnet 验收标记 blocked；当前仅有离线契约。",
    ),
    "P16-A03": (
        "AQ-SYSTEM-ACC-EXTERNAL-ALERT-MISSING",
        "本地 SEV0 投递契约通过，但没有用户配置外部渠道的实际送达证据。",
    ),
}
OWNER_WAIVERS: Final = {
    "P13-A01": (
        "P13-WAIVER-001",
        "项目业主明确决定不执行 12h/24h 墙钟验收；加速逻辑周期不得冒充长稳证据。",
    )
}
PRIOR_ACCEPTANCE: Final = (
    ("P00", "ACCEPTED", None),
    ("P01", "ACCEPTED", None),
    ("P02", "ACCEPTED", None),
    ("P03", "ACCEPTED_WITH_WAIVER", "P03-A01"),
    ("P04", "ACCEPTED", None),
)


def _json(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def _yaml(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", yaml.safe_load(path.read_text(encoding="utf-8")))


def _required_text(row: dict[str, str | None], key: str) -> str:
    value = row.get(key)
    if not value:
        raise ValueError(f"traceability row is missing {key}: {row!r}")
    return value


def _references(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(";") if item.strip())


def _result_passed(payload: dict[str, object]) -> bool:
    result = payload.get("result")
    status = payload.get("status")
    return result in {"pass", "implementation_verified_acceptance_deferred"} or status in {
        "passed",
        "passed_implementation_acceptance_deferred",
    }


def _verify_prior_acceptance(root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for phase, status, waiver in PRIOR_ACCEPTANCE:
        acceptance = root / f"reports/phases/{phase}/ACCEPTANCE.md"
        manifest = _json(root / f"reports/phases/{phase}/ARTIFACT_MANIFEST.json")
        if not acceptance.is_file() or acceptance.stat().st_size == 0:
            raise ValueError(f"{phase} prior acceptance report is missing")
        implementation_commit = manifest.get("implementation_commit")
        if not isinstance(implementation_commit, str) or len(implementation_commit) != 40:
            raise ValueError(f"{phase} prior acceptance commit is invalid")
        records.append(
            {
                "phase": phase,
                "formal_status": status,
                "implementation_commit": implementation_commit,
                "waived_requirement_id": waiver,
                "acceptance_report": acceptance.relative_to(root).as_posix(),
            }
        )
    return records


def _verify_phase_evidence(
    root: Path,
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    audit_rows: list[dict[str, str]] = []
    phase_records: list[dict[str, object]] = []
    first_blocking_number = 12

    for phase in DEFERRED_PHASES:
        matrix_path = root / f"reports/phases/{phase}/REQUIREMENTS_TRACEABILITY.csv"
        with matrix_path.open(encoding="utf-8", newline="") as source:
            raw_rows = list(csv.DictReader(source))
        task_rows = [row for row in raw_rows if row.get("category") == "task"]
        acceptance_rows = [row for row in raw_rows if row.get("category") == "acceptance"]
        expected_count = EXPECTED_ACCEPTANCE_COUNTS[phase]
        if len(acceptance_rows) != expected_count:
            raise ValueError(
                f"{phase} acceptance row count is {len(acceptance_rows)}, expected {expected_count}"
            )
        task_statuses = {row.get("status") for row in task_rows}
        if not task_rows or not task_statuses <= {
            "verified",
            "in_progress",
            "planned_acceptance_deferred",
        }:
            raise ValueError(f"{phase} task traceability has an invalid historical status")

        ci = _json(root / f"reports/phases/{phase}/CI_RESULTS.json")
        results = _json(root / f"reports/phases/{phase}/TEST_RESULTS.json")
        if ci.get("status") != "passed" or ci.get("failed_count") != 0:
            raise ValueError(f"{phase} CI evidence did not pass")
        if not _result_passed(results):
            raise ValueError(f"{phase} implementation test evidence did not pass")

        intrinsic_results: list[str] = []
        for raw in acceptance_rows:
            requirement_id = _required_text(raw, "requirement_id")
            for field in ("implementation", "test", "evidence"):
                for relative in _references(_required_text(raw, field)):
                    if not (root / relative).exists():
                        raise ValueError(f"{requirement_id} missing {field} reference: {relative}")

            if requirement_id in BLOCKED_REQUIREMENTS:
                intrinsic_result = "BLOCKED_EXTERNAL_INPUT"
                reason_code, note = BLOCKED_REQUIREMENTS[requirement_id]
            elif requirement_id in OWNER_WAIVERS:
                intrinsic_result = "WAIVED_BY_OWNER"
                waiver_id, note = OWNER_WAIVERS[requirement_id]
                reason_code = waiver_id
            else:
                intrinsic_result = "PASS"
                reason_code = ""
                note = "实现、测试、运行证据与阶段 CI 均可解析且通过。"
            intrinsic_results.append(intrinsic_result)

            phase_number = int(phase[1:])
            if phase_number < first_blocking_number:
                formal_result = "READY_NOT_ISSUED_ATOMIC_AUDIT"
            elif phase_number == first_blocking_number:
                formal_result = (
                    "BLOCKED_EXTERNAL_INPUT"
                    if intrinsic_result == "BLOCKED_EXTERNAL_INPUT"
                    else "EVALUATED_PASS_PHASE_BLOCKED"
                )
            else:
                formal_result = "NOT_REACHED_DEPENDENCY_BLOCKED"

            audit_rows.append(
                {
                    "requirement_id": requirement_id,
                    "phase": phase,
                    "requirement": _required_text(raw, "requirement"),
                    "implementation": _required_text(raw, "implementation"),
                    "test": _required_text(raw, "test"),
                    "evidence": _required_text(raw, "evidence"),
                    "historical_status": _required_text(raw, "status"),
                    "intrinsic_result": intrinsic_result,
                    "formal_result": formal_result,
                    "reason_code": reason_code,
                    "notes": note,
                }
            )

        if "BLOCKED_EXTERNAL_INPUT" in intrinsic_results:
            intrinsic_status = "BLOCKED_EXTERNAL_INPUT"
        elif "WAIVED_BY_OWNER" in intrinsic_results:
            intrinsic_status = "PASS_WITH_OWNER_WAIVER"
        else:
            intrinsic_status = "PASS"
        phase_number = int(phase[1:])
        if phase_number < first_blocking_number:
            formal_status = "READY_NOT_ISSUED_ATOMIC_AUDIT"
        elif phase_number == first_blocking_number:
            formal_status = "BLOCKED_EXTERNAL_INPUT"
        else:
            formal_status = "NOT_REACHED_DEPENDENCY_BLOCKED"
        phase_records.append(
            {
                "phase": phase,
                "implementation_status": "VERIFIED",
                "intrinsic_acceptance_status": intrinsic_status,
                "formal_acceptance_status": formal_status,
                "acceptance_requirement_count": len(acceptance_rows),
                "ci_stage_count": ci.get("stage_count"),
                "ci_failed_count": ci.get("failed_count"),
                "acceptance_report_issued": False,
            }
        )

    return audit_rows, phase_records


def _csv_text(rows: list[dict[str, str]]) -> str:
    fields: list[str] = [
        "requirement_id",
        "phase",
        "requirement",
        "implementation",
        "test",
        "evidence",
        "historical_status",
        "intrinsic_result",
        "formal_result",
        "reason_code",
        "notes",
    ]
    target = io.StringIO(newline="")
    writer = csv.DictWriter(target, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return target.getvalue()


def _phase_table(records: list[dict[str, object]]) -> str:
    lines = [
        "| Phase | 实现证据 | 内在验收判定 | 正式顺序结果 |",
        "|---|---|---|---|",
    ]
    for record in records:
        lines.append(
            f"| {record['phase']} | {record['implementation_status']} | "
            f"{record['intrinsic_acceptance_status']} | {record['formal_acceptance_status']} |"
        )
    return "\n".join(lines)


def build_outputs(root: Path, generated_at_utc: str) -> dict[Path, str]:
    """Build every deterministic audit output in memory."""
    state = _yaml(root / "state/PROJECT_PHASE_STATE.yaml")
    if state.get("live_trading_locked") is not True:
        raise ValueError("LIVE_TRADING lock is not active")
    if state.get("spec_version") != "3.1.0":
        raise ValueError("unexpected specification version")

    prior = _verify_prior_acceptance(root)
    audit_rows, phase_records = _verify_phase_evidence(root)
    if len(audit_rows) != 93:
        raise ValueError(f"consolidated acceptance row count is {len(audit_rows)}, expected 93")

    p18_results = _json(root / "reports/phases/P18/TEST_RESULTS.json")
    p18_ci = _json(root / "reports/phases/P18/CI_RESULTS.json")
    readiness = _json(root / "reports/live_readiness/READINESS_EVIDENCE.json")
    review = cast("dict[str, object]", readiness["review"])
    if p18_ci.get("status") != "passed" or review.get("decision") != "NO_GO":
        raise ValueError("P18 final evidence is not a passing implementation with NO_GO readiness")

    blocked_rows = [
        row for row in audit_rows if row["intrinsic_result"] == "BLOCKED_EXTERNAL_INPUT"
    ]
    waived_rows = [row for row in audit_rows if row["intrinsic_result"] == "WAIVED_BY_OWNER"]
    payload: dict[str, object] = {
        "schema_version": "system-acceptance-audit-v1",
        "generated_at_utc": generated_at_utc,
        "scope": "P00-P18",
        "decision": "BLOCKED_EXTERNAL_INPUT",
        "first_blocking_phase": "P12",
        "engineering_implementation_status": "COMPLETE",
        "research_platform_status": "IMPLEMENTATION_COMPLETE_WITH_P03_SOAK_WAIVER",
        "paper_shadow_formal_acceptance": "BLOCKED_EXTERNAL_INPUT",
        "canary_readiness": "NO_GO",
        "live_trading_locked": True,
        "phase_acceptance_reports_issued": False,
        "atomic_audit": True,
        "prior_formal_acceptance": prior,
        "deferred_phase_assessments": phase_records,
        "acceptance_requirement_count": len(audit_rows),
        "intrinsic_pass_count": sum(row["intrinsic_result"] == "PASS" for row in audit_rows),
        "blocked_requirement_ids": [row["requirement_id"] for row in blocked_rows],
        "waived_requirement_ids": [row["requirement_id"] for row in waived_rows],
        "blocking_evidence": {
            "P12-A01": "reports/execution/P12_TESTNET_CAPABILITY.json",
            "P16-A03": "reports/observability/P16_ALERT_EVIDENCE.json",
        },
        "source_verification": {
            "p18_ci_status": p18_ci.get("status"),
            "p18_ci_stage_count": p18_ci.get("stage_count"),
            "p18_ci_failed_count": p18_ci.get("failed_count"),
            "python_313_passed": cast("dict[str, object]", p18_results["python_313"])["passed"],
            "python_314_passed": cast("dict[str, object]", p18_results["python_314_candidate"])[
                "passed"
            ],
            "p18_readiness_decision": review.get("decision"),
        },
        "safety": {
            "wall_clock_12h_or_24h_executed": False,
            "real_account_connections": 0,
            "real_order_requests": 0,
            "plaintext_secret_requested_or_written": NEGATIVE_AUDIT_FLAG,
            "live_authorization_issued": False,
        },
    }

    phase_table = _phase_table(phase_records)
    acceptance_md = f"""# AegisQuant v3.1 系统统一验收记录

## 结论：BLOCKED_EXTERNAL_INPUT

P00–P18 工程实现及最后一次 P18 完整 CI 均有可解析证据，但正式验收不能通过。第一个硬阻断点是
`P12-A01`：当前没有本地秘密库 Testnet 凭据引用，也没有真实 Testnet 提交、部分成交、撤单、重连和
重启恢复证据。任务书明确要求此时标记 `blocked`，禁止用 fixture 或模拟结果冒充。

本次采用原子统一验收：P05–P11 的内在条件已满足，但在 P12 阻断关闭前不签发阶段
`ACCEPTANCE.md`，P13–P18 也不越过依赖顺序。P18 的工程目标已完成且独立结论保持 `NO_GO`；这不授予
Canary readiness，更不授予 Live 权限。

## 阶段判定

{phase_table}

## 明确阻断与豁免

- `P12-A01`：`BLOCKED_EXTERNAL_INPUT`，真实 Testnet 外部输入和运行证据缺失。
- `P16-A03`：内在审查为 `BLOCKED_EXTERNAL_INPUT`，外部 SEV0/SEV1 用户渠道未实际送达；因 P12 已先
  阻断，正式顺序尚未到达 P16。
- `P13-A01`：用户已明确豁免 12h/24h 墙钟验收；该豁免保留为非合格证据声明，不会把 10,080 个逻辑
  周期改名为墙钟通过。
- `P03-A01`：既有 `P03-WAIVER-001` 保持有效，仍不证明 24 小时公共流稳定性。

## 安全边界

`LIVE_TRADING` 继续锁定；Canary 范围为空、有效资本为 0、真实账户连接和真实订单请求均为 0。本次
没有请求或写入密码、Cookie、验证码或 API Secret，也没有签发任何 Live 授权。
"""
    summary_md = """# 系统统一验收摘要

P00–P18 的工程实现已经完成，P18 全仓 CI 与双 Python、安全、供应链、账本、风险、执行、Web 和
可观测性证据均通过。正式系统验收仍为 `BLOCKED_EXTERNAL_INPUT`：首个阻断是 P12 真实 Testnet，
后续还存在 P16 外部告警送达缺口。P13 的墙钟长跑按用户决定豁免，不执行 12h/24h。

因此当前可诚实表述为“非 Live 工程实现完成”，不能表述为“Paper/Shadow 生产验收通过”或
“Canary 就绪”。P18 `NO_GO`、0 美元资本和 `LIVE_TRADING` 锁全部保持不变。
"""
    risks_md = """# 系统统一验收风险

- **真实 Testnet 缺失（阻断）**：P12 只有确定性离线契约；不得伪造真实场所验收。
- **墙钟稳定性豁免（高）**：P13 加速逻辑周期不证明 12 小时内存和连续运行行为。
- **外部告警未送达（阻断，尚未到达）**：P16 只验证本地投递契约。
- **目标 Linux 与异机备份未验证（高）**：静态容器/IaC 和本机恢复不能替代目标运行与异机恢复。
- **Canary 策略与账户为空（高，受控）**：readiness 保持 `NO_GO`，有效资本为 0。
- **P03 长流豁免（高）**：既有 24 小时缺口继续限制生产采集 SLA 声明。
"""
    next_actions_md = """# 系统统一验收后续动作

1. 若要解除 P12 阻断，由用户仅在本机秘密库配置 Testnet 凭据引用；秘密值不得进入对话、仓库或日志。
2. 在 Testnet 完成提交、部分成交、撤单、断线重连、重启恢复、对账和 Chaos，并保存真实运行证据。
3. 配置一个用户可接收的外部 SEV0/SEV1 渠道并验证实际送达；不需要把渠道密钥交给 Codex。
4. 保持 P13 墙钟豁免事实，不补写、不外推；若未来改主意，再独立执行连续 12 小时验收。
5. 关闭首个阻断后重新从 P05 顺序运行统一验收。P18 即使转为 `GO`，仍须独立人工解锁；当前禁止实盘。
"""
    adr_md = """# 系统统一验收 ADR 引用

- `ADR-0024`：统一验收采用原子结果，并在 P12 外部硬门停止。
- `ADR-0010`：实现验证与正式验收分离、全部实现后统一验收。
- `ADR-0007`：P03 24 小时公共流豁免及不得虚报边界。
- `ADR-0017`：P12 Testnet-only、凭据引用和真实 Testnet 证据政策。
- `ADR-0018`：P13 逻辑周期、12 小时资格和用户长跑豁免。
- `ADR-0021`：P16 外部告警、目标环境与备份恢复边界。
- `ADR-0023`：P18 默认 NO_GO、零资本和非授权 Manifest。
- `ADR-0003`：不可由单一环境变量或网页绕过的 LIVE_TRADING 锁。
"""
    waivers_md = """# 系统统一验收豁免登记

| Waiver | Requirement | 状态 | 说明 |
|---|---|---|---|
| P03-WAIVER-001 | P03-A01 | 已应用 | 不执行真实连续 24 小时公共流；不得声称生产采集 SLA。 |
| P13-WAIVER-001 | P13-A01 | 已获业主明确决定，尚未消费 | 不执行 12h/24h；逻辑周期保持 non-qualifying。 |

P12 真实 Testnet、P16 外部告警、目标 Linux、异机备份和 Canary 硬门均没有豁免。它们必须保持
`BLOCKED_EXTERNAL_INPUT` 或 `NO_GO`，不能顺手塞进豁免表蒙混过关。
"""
    test_results: dict[str, object] = {
        "schema_version": "system-acceptance-test-results-v1",
        "generated_at_utc": generated_at_utc,
        "scope": "P00-P18",
        "result": "blocked_external_input",
        "audit": {
            "phase_matrix_count": len(DEFERRED_PHASES),
            "acceptance_requirement_count": len(audit_rows),
            "missing_reference_count": 0,
            "prior_acceptance_report_count": len(prior),
            "blocked_requirement_count": len(blocked_rows),
            "waived_requirement_count": len(waived_rows),
        },
        "inherited_complete_ci": payload["source_verification"],
        "wall_clock_12h_or_24h_executed": False,
        "formal_acceptance_passed": False,
        "live_trading_locked": True,
        "real_account_connections": 0,
        "real_order_requests": 0,
        "plaintext_secret_requested_or_written": NEGATIVE_AUDIT_FLAG,
    }

    return {
        OUTPUT_DIR / "SYSTEM_ACCEPTANCE.json": json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n",
        OUTPUT_DIR / "REQUIREMENTS_TRACEABILITY.csv": _csv_text(audit_rows),
        OUTPUT_DIR / "ACCEPTANCE.md": acceptance_md,
        OUTPUT_DIR / "SUMMARY.md": summary_md,
        OUTPUT_DIR / "TEST_RESULTS.json": json.dumps(test_results, ensure_ascii=False, indent=2)
        + "\n",
        OUTPUT_DIR / "RISKS.md": risks_md,
        OUTPUT_DIR / "NEXT_ACTIONS.md": next_actions_md,
        OUTPUT_DIR / "ADR_REFERENCES.md": adr_md,
        OUTPUT_DIR / "WAIVERS.md": waivers_md,
    }


def generate(root: Path) -> None:
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for relative, content in build_outputs(root, generated_at).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    print("generated consolidated system acceptance audit: BLOCKED_EXTERNAL_INPUT")


def check(root: Path) -> None:
    acceptance_path = root / OUTPUT_DIR / "SYSTEM_ACCEPTANCE.json"
    current = _json(acceptance_path)
    generated_at = current.get("generated_at_utc")
    if not isinstance(generated_at, str):
        raise ValueError("system acceptance generated_at_utc is invalid")
    expected = build_outputs(root, generated_at)
    stale = [
        relative.as_posix()
        for relative, content in expected.items()
        if not (root / relative).is_file()
        or (root / relative).read_text(encoding="utf-8") != content
    ]
    if stale:
        raise ValueError("system acceptance outputs are stale: " + ", ".join(stale))
    print("verified consolidated system acceptance audit: BLOCKED_EXTERNAL_INPUT")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check(ROOT)
    else:
        generate(ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
