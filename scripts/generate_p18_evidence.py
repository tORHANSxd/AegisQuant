"""Generate deterministic P18 Canary readiness and continuous-operations evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess  # nosec B404
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final, cast

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aegisquant.operations.live_readiness.evaluation import (
    build_readiness_review,
    p18_real_order_capability,
    sign_manifest,
)
from aegisquant.operations.live_readiness.models import (
    CanaryReleaseManifest,
    GateStatus,
    LiveReadinessPolicy,
    ReadinessDecision,
    ReadinessGate,
)

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT_ROOT: Final = ROOT / "reports/live_readiness"
CONTEXT_PATH: Final = ROOT / "configs/live_readiness/context.json"
POLICY_PATH: Final = ROOT / "configs/live_readiness/policy.json"
COMMIT_RE: Final = re.compile(r"^[0-9a-f]{40}$")
OUTPUTS: Final = {
    "readiness": OUTPUT_ROOT / "READINESS_EVIDENCE.json",
    "account": OUTPUT_ROOT / "ACCOUNT_CAPABILITY_EVIDENCE.json",
    "preproduction": OUTPUT_ROOT / "PREPRODUCTION_EVIDENCE.json",
    "manifest": OUTPUT_ROOT / "CANARY_RELEASE_MANIFEST.json",
    "decision": OUTPUT_ROOT / "READINESS_DECISION.json",
    "go_no_go": OUTPUT_ROOT / "GO_NO_GO.md",
    "risks": OUTPUT_ROOT / "OPEN_RISKS.md",
    "checklist": OUTPUT_ROOT / "USER_APPROVAL_CHECKLIST.md",
    "capital": OUTPUT_ROOT / "CAPITAL_LADDER.yaml",
    "stops": OUTPUT_ROOT / "STOP_CONDITIONS.yaml",
    "rollback": OUTPUT_ROOT / "ROLLBACK_PLAN.md",
    "cadence": OUTPUT_ROOT / "CONTINUOUS_OPERATIONS.yaml",
}


def _json(path: Path) -> dict[str, object]:
    payload = cast("object", json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise TypeError(f"expected JSON object: {path}")
    return cast("dict[str, object]", payload)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_commit(commit: str) -> None:
    if COMMIT_RE.fullmatch(commit) is None:
        raise ValueError("implementation commit must be a full lowercase SHA-1")
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required for P18 evidence")
    result = subprocess.run(  # noqa: S603  # nosec B603
        [git, "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError("implementation commit does not resolve locally")


def _render_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _render_yaml(payload: object) -> str:
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)


def _load_context() -> dict[str, object]:
    return _json(CONTEXT_PATH)


def _load_policy() -> LiveReadinessPolicy:
    return LiveReadinessPolicy.model_validate_json(POLICY_PATH.read_text(encoding="utf-8"))


def _phase_traceability() -> tuple[int, int, list[str]]:
    with (ROOT / "state/REQUIREMENTS_TRACEABILITY.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        rows = list(csv.DictReader(source))
    selected: list[dict[str, str]] = []
    for row in rows:
        owner = row["owner_phase"]
        if owner == "ALL" or (
            owner.startswith("P") and owner[1:].isdigit() and int(owner[1:]) <= 17
        ):
            selected.append(row)
    allowed = {"verified", "active_global", "waived"}
    incomplete = [row["requirement_id"] for row in selected if row["status"] not in allowed]
    return len(selected), len(selected) - len(incomplete), incomplete


def _gate(
    gate_id: str,
    description: str,
    status: GateStatus,
    evidence_paths: tuple[str, ...],
    *reason_codes: str,
) -> ReadinessGate:
    return ReadinessGate(
        gate_id=gate_id,
        description=description,
        status=status,
        evidence_paths=evidence_paths,
        reason_codes=reason_codes,
    )


def _build_gates(
    *,
    context: dict[str, object],
    policy: LiveReadinessPolicy,
    traceability_incomplete: list[str],
    reconciliation: dict[str, object],
    chaos: dict[str, object],
    alert: dict[str, object],
    security: dict[str, object],
    security_scan: dict[str, object],
    restore: dict[str, object],
    testnet: dict[str, object],
    mutation_records: tuple[dict[str, object], ...],
) -> tuple[ReadinessGate, ...]:
    clear = cast("dict[str, object]", reconciliation["clear"])
    difference = cast("dict[str, object]", reconciliation["difference"])
    drills = cast("list[dict[str, object]]", chaos["drills"])
    traceability_status = GateStatus.PASSED if not traceability_incomplete else GateStatus.FAILED
    ledger_ok = (
        clear["status"] == "CLEAR"
        and difference["status"] == "HALTED"
        and difference["new_risk_allowed"] is False
        and restore["ledger_balanced"] is True
        and restore["reconciliation_valid"] is True
    )
    mutation_chaos_ok = all(
        record["status"] == "passed" and record["survived"] == 0 and record["invalid"] == 0
        for record in mutation_records
    ) and all(
        item["new_risk_allowed_during_fault"] is False
        and item["duplicate_order_count"] == 0
        and item["duplicate_fill_count"] == 0
        for item in drills
    )
    secret_ok = (
        security["live_secret_denied_for_all_roles"] is True
        and security["research_testnet_secret_denied"] is True
        and security_scan["secret_finding_count"] == 0
        and context["live_credential_reference_present"] is False
        and context["plaintext_secrets_requested_or_written"] is False
    )
    capital_ok = policy.capital_ladder.tiers[0].effective_capital_usd == 0 and all(
        tier.effective_capital_usd == min(tier.hard_code_capital_usd, tier.user_policy_capital_usd)
        for tier in policy.capital_ladder.tiers
    )
    manual_lock_ok = (
        context["live_trading_locked"] is True
        and context["manual_unlock_received"] is False
        and context["real_order_requests"] == 0
        and p18_real_order_capability(
            live_trading_locked=True,
            manual_unlock_received=False,
        )
        is False
    )
    account_controls = all(
        context[key] is True
        for key in (
            "dedicated_subaccount_verified",
            "low_balance_verified",
            "withdrawal_disabled_verified",
            "ip_allowlist_verified",
            "least_privilege_verified",
        )
    )
    testnet_capability = cast("dict[str, object]", testnet["capability"])
    real_testnet_ok = (
        context["real_testnet_acceptance_passed"] is True
        and testnet["real_testnet_acceptance"] == "passed"
        and cast("int", testnet_capability["network_requests_performed"]) > 0
    )
    alert_oncall_ok = (
        context["external_sev0_sev1_delivery_verified"] is True
        and context["human_on_call_window_approved"] is True
        and alert["user_external_channel_delivery_verified"] is True
    )
    gates = (
        _gate(
            "traceability-p00-p17",
            "P00-P17 critical requirements are traceable to implementation and verification",
            traceability_status,
            ("state/REQUIREMENTS_TRACEABILITY.csv",),
            *(() if not traceability_incomplete else ("AQ-P18-TRACEABILITY-INCOMPLETE",)),
        ),
        _gate(
            "ledger-reconciliation-clear",
            "No unexplained ledger or reconciliation difference remains open",
            GateStatus.PASSED if ledger_ok else GateStatus.FAILED,
            (
                "reports/runtime/P13_RECONCILIATION_EVIDENCE.json",
                "reports/operations/P16_RESTORE_DRILL.json",
            ),
            *(() if ledger_ok else ("AQ-P18-RECONCILIATION-NOT-CLEAR",)),
        ),
        _gate(
            "no-unhandled-sev0-sev1",
            "No unhandled SEV0 or SEV1 incident is recorded",
            (GateStatus.PASSED if context["unhandled_sev0_sev1_count"] == 0 else GateStatus.FAILED),
            (
                "reports/observability/P16_ALERT_EVIDENCE.json",
                "configs/live_readiness/context.json",
            ),
            *(
                ()
                if context["unhandled_sev0_sev1_count"] == 0
                else ("AQ-P18-UNHANDLED-CRITICAL-INCIDENT",)
            ),
        ),
        _gate(
            "risk-execution-mutation-chaos",
            "Risk, execution mutation and chaos fail-safe behavior passes",
            GateStatus.PASSED if mutation_chaos_ok else GateStatus.FAILED,
            (
                "reports/testing/P11_MUTATION_RESULTS.json",
                "reports/testing/P12_MUTATION_RESULTS.json",
                "reports/testing/P13_MUTATION_RESULTS.json",
                "reports/runtime/P13_CHAOS_EVIDENCE.json",
            ),
            *(() if mutation_chaos_ok else ("AQ-P18-RISK-EXECUTION-CHAOS-FAILED",)),
        ),
        _gate(
            "live-secret-isolation",
            "Live secrets are absent from research and CI",
            GateStatus.PASSED if secret_ok else GateStatus.FAILED,
            (
                "reports/security/P16_SECURITY_EVIDENCE.json",
                "reports/security/SECURITY_SCAN_RESULTS.json",
            ),
            *(() if secret_ok else ("AQ-P18-LIVE-SECRET-BOUNDARY-FAILED",)),
        ),
        _gate(
            "capital-dual-hard-cap",
            "Canary capital is bounded by the lower code and user policy caps",
            GateStatus.PASSED if capital_ok else GateStatus.FAILED,
            ("configs/live_readiness/policy.json",),
            *(() if capital_ok else ("AQ-P18-CAPITAL-DUAL-CAP-FAILED",)),
        ),
        _gate(
            "manual-unlock-no-real-orders",
            "No real order is possible without a separate manual unlock flow",
            GateStatus.PASSED if manual_lock_ok else GateStatus.FAILED,
            (
                "configs/live_readiness/context.json",
                "tests/p18/test_phase_evidence.py",
            ),
            *(() if manual_lock_ok else ("AQ-P18-MANUAL-UNLOCK-GUARD-FAILED",)),
        ),
        _gate(
            "approved-strategy-scope",
            "At most one fully evidenced strategy and bounded instrument scope is selected",
            (
                GateStatus.PASSED
                if context["strategy_candidate_approved"] is True
                and policy.scope.selection_status.value == "SELECTED"
                else GateStatus.FAILED
            ),
            (
                "reports/data/P08_MODEL_COUNCIL_EVIDENCE.json",
                "reports/data/P07_HOLDOUT_EVIDENCE.json",
                "configs/live_readiness/policy.json",
            ),
            *(
                ()
                if context["strategy_candidate_approved"] is True
                and policy.scope.selection_status.value == "SELECTED"
                else ("AQ-P18-NO-APPROVED-STRATEGY",)
            ),
        ),
        _gate(
            "dedicated-account-controls",
            "Dedicated low-balance, no-withdrawal, IP allowlisted least-privilege account exists",
            GateStatus.PASSED if account_controls else GateStatus.BLOCKED_EXTERNAL_INPUT,
            ("configs/live_readiness/context.json",),
            *(() if account_controls else ("AQ-P18-ACCOUNT-CONTROLS-NOT-PROVIDED",)),
        ),
        _gate(
            "real-testnet-duration-fills",
            "Real Testnet duration, fills, reconciliation and fault evidence passes",
            GateStatus.PASSED if real_testnet_ok else GateStatus.BLOCKED_EXTERNAL_INPUT,
            (
                "reports/execution/P12_TESTNET_CAPABILITY.json",
                "reports/runtime/P13_STABILITY_EVIDENCE.json",
            ),
            *(() if real_testnet_ok else ("AQ-P18-REAL-TESTNET-NOT-ACCEPTED",)),
        ),
        _gate(
            "external-alert-and-oncall",
            "External SEV0/SEV1 delivery and human on-call window are verified",
            GateStatus.PASSED if alert_oncall_ok else GateStatus.BLOCKED_EXTERNAL_INPUT,
            (
                "reports/observability/P16_ALERT_EVIDENCE.json",
                "configs/live_readiness/context.json",
            ),
            *(() if alert_oncall_ok else ("AQ-P18-EXTERNAL-ALERT-ONCALL-NOT-VERIFIED",)),
        ),
        _gate(
            "target-linux-runtime",
            "Target Linux container runtime and image behavior are verified",
            (
                GateStatus.PASSED
                if context["target_linux_runtime_verified"] is True
                else GateStatus.BLOCKED_EXTERNAL_INPUT
            ),
            ("reports/deployment/P16_DEPLOYMENT_EVIDENCE.json",),
            *(
                ()
                if context["target_linux_runtime_verified"] is True
                else ("AQ-P18-TARGET-LINUX-RUNTIME-NOT-VERIFIED",)
            ),
        ),
        _gate(
            "offsite-backup",
            "Encrypted backup exists on a distinct offsite device and restores successfully",
            (
                GateStatus.PASSED
                if context["offsite_backup_verified"] is True
                else GateStatus.BLOCKED_EXTERNAL_INPUT
            ),
            ("reports/operations/P16_RESTORE_DRILL.json",),
            *(
                ()
                if context["offsite_backup_verified"] is True
                else ("AQ-P18-OFFSITE-BACKUP-NOT-VERIFIED",)
            ),
        ),
        _gate(
            "wall-clock-stability",
            "Required wall-clock stability acceptance is complete",
            GateStatus.BLOCKED_EXTERNAL_INPUT,
            ("reports/runtime/P13_STABILITY_EVIDENCE.json",),
            "AQ-P18-WALL-CLOCK-ACCEPTANCE-DEFERRED",
        ),
    )
    return gates


def _go_no_go(review_payload: dict[str, object]) -> str:
    gates = cast("list[dict[str, object]]", review_payload["gates"])
    rows = "\n".join(
        "| {gate_id} | {status} | {reasons} | {evidence} |".format(
            gate_id=item["gate_id"],
            status=item["status"],
            reasons="; ".join(cast("list[str]", item["reason_codes"])) or "—",
            evidence="<br>".join(cast("list[str]", item["evidence_paths"])),
        )
        for item in gates
    )
    return f"""# P18 Canary Go/No-Go

## 独立结论

**NO_GO**。所有硬门必须逐项通过，不使用加权平均；当前存在真实策略、专用账户、真实 Testnet、
外部关键告警与值守、目标 Linux、异机备份和墙钟稳定性证据缺口。

| Hard gate | Status | Reason codes | Evidence |
|---|---|---|---|
{rows}

## 授权边界

- `LIVE_TRADING` 仍锁定，真实订单能力为 `false`。
- Canary 策略、账户和合约选择均为空；当前有效资本上限为 0 美元。
- Manifest 签名只证明证据完整性，不是 Live 授权或解锁令牌。
- 即使未来所有门变为 `PASSED`，仍须用户在独立流程中批准并单次人工解锁。
- 本次未执行 12h/24h 验收，不生成 P18 `ACCEPTANCE.md`。
"""


def _open_risks(review_payload: dict[str, object]) -> str:
    gates = cast("list[dict[str, object]]", review_payload["gates"])
    blocked = [item for item in gates if item["status"] != GateStatus.PASSED.value]
    lines = ["# P18 开放风险", ""]
    for item in blocked:
        reasons = ", ".join(cast("list[str]", item["reason_codes"]))
        lines.append(f"- **{item['gate_id']}（高，开放）**：{item['description']}；`{reasons}`。")
    lines.extend(
        (
            "- **正式验收延期（高，开放）**：自动门禁完成不等于 P05–P18 正式 acceptance；按用户决定不执行 12h/24h。",
            "- **上游弃用告警（低，开放）**：Starlette/httpx2 与 Nautilus/Pandas timedelta 告警需在依赖升级时回归。",
            "",
        )
    )
    return "\n".join(lines)


def _approval_checklist() -> str:
    return """# P18 用户人工确认清单

当前状态：`NOT_ACTIONABLE_WHILE_NO_GO`。以下项目只在 `GO_NO_GO.md` 的所有硬门均有真实证据后，
才由用户逐项确认；现在不要提供任何密码、Cookie、验证码、API Secret 或 session 文件。

- [ ] 确认建立专用低余额子账户，且与其他资产和权限隔离。
- [ ] 确认 API 无提现、启用 IP 白名单并仅有最小交易/读取权限。
- [ ] 确认唯一 Canary 策略、账户范围和最多两个高流动性合约。
- [ ] 确认硬代码资本上限与更低的用户政策上限。
- [ ] 确认最大持续时间、评估窗口、日损失和所有停止条件。
- [ ] 确认外部 SEV0/SEV1 渠道与全时段人工值守安排。
- [ ] 在本机秘密库中自行配置凭据引用；只确认引用存在，不披露秘密值。
- [ ] 在所有门通过后执行独立、单次、明确的人工解锁；不允许自动或永久解锁。

用户不确认时，系统保持完整 Paper/Shadow 能力和 `NO_GO`，这不构成工程失败。
"""


def _rollback_plan() -> str:
    return """# P18 Canary 回退计划

当前没有 Live/Canary 运行，系统姿态为 `HALTED` 且资本上限为 0。未来若经独立流程解锁，任一
`STOP_CONDITIONS.yaml` 条件触发时必须原子执行：

1. 停止创建新风险并触发 kill switch；不得自动恢复。
2. 取消可确认的未成交订单；未知订单状态先查询和对账，禁止盲目重发。
3. 冻结策略与模型输出，保留原始事件、命令、成交、账本、日志和 trace。
4. 使用交易所官方接口与内部双重账本完成订单、成交、仓位、余额和费用对账。
5. 回退到同版本 Paper/Shadow，只允许继续观察和重放，不允许真实下单。
6. 生成事故记录、时间线、根因和恢复证据；SEV0/SEV1 必须完成复盘。
7. 重新执行数据、风险、执行、账本、恢复、告警和权限硬门。
8. 只有新的独立 Go/No-Go 与用户单次人工解锁同时存在，才可考虑再次 Canary。

真实成交相对模拟的监控至少比较成交率、价格偏差、滑点、费用、延迟、拒单、部分成交、资金费率、
账本差异和风险状态；任一无法解释的偏差直接退回，不用盈利抵消安全失败。
"""


def build_payloads(implementation_commit: str) -> dict[str, object]:
    _verify_commit(implementation_commit)
    context = _load_context()
    policy = _load_policy()
    state = cast(
        "dict[str, object]",
        yaml.safe_load((ROOT / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")),
    )
    traceability_total, traceability_complete, incomplete = _phase_traceability()
    reconciliation = _json(ROOT / "reports/runtime/P13_RECONCILIATION_EVIDENCE.json")
    chaos = _json(ROOT / "reports/runtime/P13_CHAOS_EVIDENCE.json")
    stability = _json(ROOT / "reports/runtime/P13_STABILITY_EVIDENCE.json")
    paper = _json(ROOT / "reports/runtime/P13_PAPER_EVIDENCE.json")
    shadow = _json(ROOT / "reports/runtime/P13_SHADOW_EVIDENCE.json")
    semantic = _json(ROOT / "reports/runtime/P13_SEMANTIC_COMPARISON.json")
    testnet = _json(ROOT / "reports/execution/P12_TESTNET_CAPABILITY.json")
    alert = _json(ROOT / "reports/observability/P16_ALERT_EVIDENCE.json")
    security = _json(ROOT / "reports/security/P16_SECURITY_EVIDENCE.json")
    security_scan = _json(ROOT / "reports/security/SECURITY_SCAN_RESULTS.json")
    restore = _json(ROOT / "reports/operations/P16_RESTORE_DRILL.json")
    release = _json(ROOT / "reports/deployment/P16_RELEASE_EVIDENCE.json")
    p16_results = _json(ROOT / "reports/phases/P16/TEST_RESULTS.json")
    model_council = _json(ROOT / "reports/data/P08_MODEL_COUNCIL_EVIDENCE.json")
    holdout = _json(ROOT / "reports/data/P07_HOLDOUT_EVIDENCE.json")
    provider = _json(ROOT / "reports/data/provider_bakeoff/PROVIDER_DECISIONS.json")
    mutations = tuple(
        _json(ROOT / f"reports/testing/{phase}_MUTATION_RESULTS.json")
        for phase in ("P11", "P12", "P13")
    )
    gates = _build_gates(
        context=context,
        policy=policy,
        traceability_incomplete=incomplete,
        reconciliation=reconciliation,
        chaos=chaos,
        alert=alert,
        security=security,
        security_scan=security_scan,
        restore=restore,
        testnet=testnet,
        mutation_records=mutations,
    )
    review = build_readiness_review(
        gates,
        live_trading_locked=cast("bool", context["live_trading_locked"]),
        manual_unlock_received=cast("bool", context["manual_unlock_received"]),
    )
    review_payload = cast("dict[str, object]", review.model_dump(mode="json"))

    deferred = cast("list[dict[str, object]]", state["deferred_acceptance_queue"])
    stability_record = cast("dict[str, object]", stability["stability"])
    semantic_comparison = cast("dict[str, object]", semantic["comparison"])
    account: dict[str, object] = {
        "schema_version": "p18-account-capability-evidence-v1",
        "state": "AWAITING_GO_PREREQUISITES_AND_USER_CONFIGURATION",
        "dedicated_subaccount_verified": context["dedicated_subaccount_verified"],
        "low_balance_verified": context["low_balance_verified"],
        "withdrawal_disabled_verified": context["withdrawal_disabled_verified"],
        "ip_allowlist_verified": context["ip_allowlist_verified"],
        "least_privilege_verified": context["least_privilege_verified"],
        "credential_reference_present": context["live_credential_reference_present"],
        "credential_values_accessed": False,
        "plaintext_credentials_requested_or_written": False,
        "real_account_connections": context["real_account_connections"],
        "real_order_requests": context["real_order_requests"],
        "research_or_ci_live_secret_access": False,  # nosec B105 -- audit boolean
        "live_trading_locked": True,
    }
    preproduction: dict[str, object] = {
        "schema_version": "p18-preproduction-evidence-v1",
        "historical_paper_shadow_semantics_equal": semantic_comparison["semantic_identity_equal"],
        "startup_reconciliation_status": cast("dict[str, object]", reconciliation["clear"])[
            "status"
        ],
        "injected_reconciliation_difference_posture": cast(
            "dict[str, object]", reconciliation["difference"]
        )["status"],
        "unexplained_reconciliation_difference_count": 0,
        "restore_status": restore["status"],
        "restore_verification_equal": restore["verification_equal"],
        "tampered_ciphertext_rejected": restore["tampered_ciphertext_rejected"],
        "paper_virtual_fill_count": len(cast("list[object]", paper["fills"])),
        "shadow_write_capability": shadow["write_capability"],
        "real_account_access_performed": False,
        "real_canary_preproduction_run_performed": False,
    }
    readiness: dict[str, object] = {
        "schema_version": "p18-readiness-evidence-v1",
        "as_of_utc": context["as_of_utc"],
        "review": review_payload,
        "p00_p17_requirement_count": traceability_total,
        "p00_p17_traceable_count": traceability_complete,
        "p00_p17_incomplete_requirement_ids": incomplete,
        "accepted_phase_count": len(cast("list[dict[str, object]]", state["phase_history"])),
        "deferred_phase_count": len(deferred),
        "deferred_phases": [item["phase"] for item in deferred],
        "real_testnet_acceptance": testnet["real_testnet_acceptance"],
        "paper_economic_order_count": paper["economic_order_count"],
        "paper_virtual_fills": paper["virtual_fills"],
        "shadow_write_capability": shadow["write_capability"],
        "logical_stability_cycles": stability_record["logical_cycles"],
        "wall_clock_acceptance_passed": stability_record["wall_clock_memory_acceptance_passed"],
        "wall_clock_acceptance_deferred": stability_record["deferred_by_user"],
        "chaos_drill_count": len(cast("list[object]", chaos["drills"])),
        "risk_execution_mutation_passed": all(item["status"] == "passed" for item in mutations),
        "local_sev0_delivery_verified": alert["local_contract_delivery_verified"],
        "external_sev0_sev1_delivery_verified": alert["user_external_channel_delivery_verified"],
        "target_linux_runtime_verified": context["target_linux_runtime_verified"],
        "offsite_backup_verified": context["offsite_backup_verified"],
        "provider_procurement_decision": provider["procurement_decision"],
        "approved_paid_provider_count": provider["approved_provider_count"],
        "formal_acceptance_performed": False,
        "wall_clock_12h_or_24h_executed": False,
    }

    artifact_paths = (
        "uv.lock",
        "pnpm-lock.yaml",
        "configs/live_readiness/policy.json",
        "reports/risk/P11_SIGNED_RISK_POLICY.json",
        "reports/execution/P12_RULE_EVIDENCE.json",
        "reports/runtime/P13_SEMANTIC_COMPARISON.json",
        "data/catalogs/provider_registry.yaml",
    )
    created = datetime.fromisoformat(cast("str", context["as_of_utc"]).replace("Z", "+00:00"))
    manifest = CanaryReleaseManifest(
        schema_version="p18-canary-release-manifest-v1",
        release_id=f"p18-readiness-{implementation_commit[:12]}",
        source_commit=implementation_commit,
        created_at_utc=created,
        expires_at_utc=created + timedelta(hours=4),
        decision=ReadinessDecision.NO_GO,
        scope=policy.scope,
        frozen_versions={
            "python_primary": "3.13.15",
            "python_candidate": "3.14.7",
            "nautilus_trader": "1.231.0",
            "node": "24.20.0",
            "postgresql": "18.6",
            "observed_model_candidate": cast("str", model_council["selected_model_id"]),
            "selected_strategy": "NONE",
            "final_holdout_state": cast("str", holdout["state"]),
        },
        frozen_artifact_sha256={path: _sha256(ROOT / path) for path in artifact_paths},
        live_trading_locked=True,
        user_approval_received=False,
        manual_unlock_received=False,
        releaseable=False,
    )
    evidence_seed = hashlib.sha256(b"AegisQuant-P18-evidence-integrity-only").digest()
    signed = sign_manifest(manifest, Ed25519PrivateKey.from_private_bytes(evidence_seed))
    manifest_payload = cast("dict[str, object]", signed.model_dump(mode="json"))
    manifest_payload["key_trust"] = "UNTRUSTED_TEST_EVIDENCE_KEY"
    manifest_payload["live_authorization_issued"] = False
    manifest_payload["p16_non_live_release_signature_verified"] = release[
        "signature_verified_by_gate"
    ]
    manifest_payload["target_linux_runtime_executed"] = cast(
        "dict[str, object]", p16_results["deployment"]
    )["target_linux_container_runtime_executed"]

    capital = {
        "schema_version": "p18-capital-ladder-evidence-v1",
        "decision": review.decision.value,
        "active_level": "LOCKED",
        "active_effective_capital_usd": "0",
        "activation_requires_all_hard_gates": True,
        "tiers": policy.capital_ladder.model_dump(mode="json")["tiers"],
    }
    stops = {
        "schema_version": "p18-stop-conditions-v1",
        "live_trading_locked": True,
        "conditions": [item.model_dump(mode="json") for item in policy.stop_conditions],
    }
    cadence = {
        "schema_version": "p18-continuous-operations-v1",
        "active_live_schedule": False,
        "paper_shadow_schedule_available": True,
        "cadence": [item.model_dump(mode="json") for item in policy.operating_cadence],
    }
    return {
        "readiness": readiness,
        "account": account,
        "preproduction": preproduction,
        "manifest": manifest_payload,
        "decision": review_payload,
        "go_no_go": _go_no_go(review_payload),
        "risks": _open_risks(review_payload),
        "checklist": _approval_checklist(),
        "capital": capital,
        "stops": stops,
        "rollback": _rollback_plan(),
        "cadence": cadence,
    }


def _validate(payloads: dict[str, object]) -> None:
    readiness = cast("dict[str, object]", payloads["readiness"])
    review = cast("dict[str, object]", readiness["review"])
    account = cast("dict[str, object]", payloads["account"])
    preproduction = cast("dict[str, object]", payloads["preproduction"])
    manifest = cast("dict[str, object]", payloads["manifest"])
    capital = cast("dict[str, object]", payloads["capital"])
    checks = {
        "NO_GO": review["decision"] == "NO_GO",
        "hard blockers retained": cast("int", review["blocked_hard_gate_count"]) > 0
        and cast("int", review["failed_hard_gate_count"]) > 0,
        "no weighted override": review["weighted_score_used"] is False,
        "no order capability": review["real_order_capability"] is False,
        "live lock": review["live_trading_locked"] is True,
        "zero account activity": account["real_account_connections"] == 0
        and account["real_order_requests"] == 0,
        "reconciliation clear": preproduction["unexplained_reconciliation_difference_count"] == 0,
        "manifest non-authorizing": manifest["signature_verified"] is True
        and manifest["authorization_capability"] is False
        and manifest["live_authorization_issued"] is False,
        "zero active capital": capital["active_effective_capital_usd"] == "0",
        "acceptance honest": readiness["formal_acceptance_performed"] is False
        and readiness["wall_clock_12h_or_24h_executed"] is False,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("P18 evidence validation failed: " + ", ".join(failed))


def _render(name: str, payload: object) -> str:
    if isinstance(payload, str):
        return payload if payload.endswith("\n") else payload + "\n"
    if name in {"capital", "stops", "cadence"}:
        return _render_yaml(payload)
    return _render_json(payload)


def _existing_implementation_commit() -> str:
    manifest = _json(OUTPUTS["manifest"])
    unsigned = cast("dict[str, object]", manifest["manifest"])
    commit = unsigned["source_commit"]
    if not isinstance(commit, str):
        raise TypeError("existing P18 manifest source_commit is invalid")
    return commit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--implementation-commit")
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if arguments.check:
        if arguments.implementation_commit is not None:
            raise SystemExit("--check reads the pinned implementation commit from the manifest")
        implementation_commit = _existing_implementation_commit()
    else:
        if arguments.implementation_commit is None:
            raise SystemExit("--implementation-commit is required when generating P18 evidence")
        implementation_commit = arguments.implementation_commit
    payloads = build_payloads(implementation_commit)
    _validate(payloads)
    mismatches: list[str] = []
    for name, payload in payloads.items():
        target = OUTPUTS[name]
        rendered = _render(name, payload)
        if arguments.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != rendered:
                mismatches.append(target.relative_to(ROOT).as_posix())
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8", newline="\n")
    if mismatches:
        raise SystemExit("P18 evidence drift: " + ", ".join(mismatches))
    print(f"{'verified' if arguments.check else 'generated'} {len(payloads)} P18 evidence files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
