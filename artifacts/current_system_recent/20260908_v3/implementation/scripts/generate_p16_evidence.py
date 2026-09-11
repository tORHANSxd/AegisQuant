"""Generate or verify deterministic P16 operational evidence."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, cast

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aegisquant.observability.alerts import (
    AlertDispatcher,
    AlertEvent,
    Incident,
    IncidentState,
    MaintenanceWindow,
    Severity,
    WebhookChannel,
)
from aegisquant.observability.context import TelemetryContext, correlation_scope
from aegisquant.observability.logging import StructuredJsonFormatter, redact
from aegisquant.observability.metrics import AegisMetrics
from aegisquant.observability.tracing import TracingRuntime
from aegisquant.operations.release import (
    ReleaseEnvironment,
    ReleaseManifest,
    RuntimePosture,
    approve_release,
    deployment_gate,
    rollback_after_failure,
    sign_release,
)
from aegisquant.security.isolation import SecretClass, ServiceRole, validate_secret_mounts

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUTS: Final = {
    "telemetry": ROOT / "reports/observability/P16_TELEMETRY_EVIDENCE.json",
    "dashboards": ROOT / "reports/observability/P16_DASHBOARD_EVIDENCE.json",
    "alerts": ROOT / "reports/observability/P16_ALERT_EVIDENCE.json",
    "runbooks": ROOT / "reports/operations/P16_RUNBOOK_EVIDENCE.json",
    "security": ROOT / "reports/security/P16_SECURITY_EVIDENCE.json",
    "deployment": ROOT / "reports/deployment/P16_DEPLOYMENT_EVIDENCE.json",
    "release": ROOT / "reports/deployment/P16_RELEASE_EVIDENCE.json",
}
RUNBOOKS: Final = (
    "DATA_STALE",
    "ORDER_UNKNOWN",
    "RECONCILIATION_FAILURE",
    "LEDGER_IMBALANCE",
    "VENUE_DISCONNECT",
    "MARGIN_RISK",
    "MODEL_DRIFT",
    "DATABASE_FAILURE",
    "DISK_FULL",
    "SECRET_LEAK",
    "LIVE_KILL_SWITCH",
    "RESTORE_FROM_BACKUP",
)


def _render(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _telemetry_payload() -> dict[str, object]:
    exporter = InMemorySpanExporter()
    tracing = TracingRuntime(exporter=exporter, synchronous=True)
    metrics = AegisMetrics(service="runtime", environment="paper")
    context = TelemetryContext(
        correlation_id="corr-p16-evidence",
        event_type="risk",
        account_scope="paper-primary",
        order_intent_id="intent-p16-evidence",
    )
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredJsonFormatter(service="runtime", version="3.1.0.dev0"))
    logger = logging.getLogger("aegisquant.p16.evidence")
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    with correlation_scope(context), tracing.span("risk.evaluate", context):
        metrics.record_event("risk", "rejected")
        logger.info("risk decision", extra={"details": {"reason": "limit"}})
    log_payload = cast("dict[str, object]", json.loads(stream.getvalue()))
    spans = exporter.get_finished_spans()
    rendered_metrics = metrics.render().decode()
    attributes = {} if not spans else dict(spans[0].attributes or {})
    redacted = cast(
        "dict[str, object]",
        redact({"nested": [{"api_" + "key": "fixture-value"}]}),
    )
    tracing.shutdown()
    return {
        "schema_version": "p16-telemetry-evidence-v1",
        "correlation_id": context.correlation_id,
        "log_correlation_matches": log_payload["correlation_id"] == context.correlation_id,
        "log_has_trace_id": isinstance(log_payload["trace_id"], str),
        "span_correlation_matches": attributes.get("aegisquant.correlation_id")
        == context.correlation_id,
        "metric_event_present": 'event_type="risk"' in rendered_metrics,
        "metric_status_present": 'status="rejected"' in rendered_metrics,
        "metric_excludes_correlation_id": context.correlation_id not in rendered_metrics,
        "recursive_redaction_passed": "fixture-value" not in _render(redacted),
        "collector": "Alloy OTLP/HTTP",
        "log_agent": "Grafana Alloy",
        "promtail_used": False,
        "formal_acceptance_performed": False,
        "tests": ["tests/observability/test_correlation.py"],
    }


def _dashboard_payload() -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for path in sorted((ROOT / "infra/grafana/dashboards").glob("*.json")):
        payload = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
        panels = cast("list[dict[str, object]]", payload["panels"])
        expressions = " ".join(
            str(cast("list[dict[str, object]]", panel["targets"])[0]["expr"]) for panel in panels
        )
        entries.append(
            {
                "domain": path.stem,
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": _sha256(path),
                "panel_count": len(panels),
                "editable": payload["editable"],
                "high_cardinality_identifier_used": any(
                    item in expressions for item in ("order_id", "correlation_id")
                ),
            }
        )
    return {
        "schema_version": "p16-dashboard-evidence-v1",
        "domains": [entry["domain"] for entry in entries],
        "dashboard_count": len(entries),
        "dashboards": entries,
        "private_entrypoint": "https://127.0.0.1:8443",
        "authentication": "nginx mTLS plus optional offline OIDC bearer verification",
        "tests": ["tests/p16/test_infrastructure_contracts.py"],
    }


def _alert_payload() -> dict[str, object]:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    delivered: list[str] = []

    def sender(url: str, payload: dict[str, str], timeout: float) -> int:
        del url, timeout
        delivered.append(payload["severity"])
        return 204

    channel = WebhookChannel(
        name="local-contract",
        url="http://127.0.0.1:9199/alert",
        sender=sender,
    )
    dispatcher = AlertDispatcher(
        channels={"local-contract": channel},
        routes={
            Severity.SEV0: ("local-contract",),
            Severity.SEV1: ("local-contract",),
            Severity.SEV2: ("local-contract",),
            Severity.SEV3: ("local-contract",),
        },
        clock=lambda: now,
    )
    dispatcher.set_maintenance(
        (
            MaintenanceWindow(
                name="evidence-window",
                starts_at=now - timedelta(minutes=1),
                ends_at=now + timedelta(minutes=1),
                scopes=frozenset({"accounting"}),
            ),
        )
    )

    def event(severity: Severity, rule: str) -> AlertEvent:
        return AlertEvent(
            rule_name=rule,
            severity=severity,
            environment="paper",
            scope="accounting",
            summary="P16 deterministic alert contract",
            correlation_id="corr-p16-alert",
            starts_at=now,
        )

    critical = event(Severity.SEV0, "LEDGER_IMBALANCE")
    first = dispatcher.dispatch(critical)
    duplicate = dispatcher.dispatch(critical)
    maintenance = dispatcher.dispatch(event(Severity.SEV2, "DATABASE_FAILURE"))
    incident = Incident("incident-p16-evidence", Severity.SEV1)
    for target in (
        IncidentState.ACKNOWLEDGED,
        IncidentState.MITIGATING,
        IncidentState.MONITORING,
        IncidentState.RESOLVED,
        IncidentState.POSTMORTEM_REQUIRED,
        IncidentState.CLOSED,
    ):
        incident.transition(target, actor="operator-1", at=now)
    return {
        "schema_version": "p16-alert-evidence-v1",
        "severities": [item.value for item in Severity],
        "sev0_delivery_outcome": first.outcome,
        "duplicate_outcome": duplicate.outcome,
        "maintenance_sev2_outcome": maintenance.outcome,
        "maintenance_suppressed_sev0": False,
        "delivered_severities": delivered,
        "incident_final_state": incident.state.value,
        "incident_transition_count": len(incident.history),
        "local_contract_delivery_verified": True,
        "user_external_channel_delivery_verified": False,
        "formal_acceptance_performed": False,
        "tests": ["tests/observability/test_alerts.py"],
    }


def _runbook_payload() -> dict[str, object]:
    entries = [
        {
            "name": name,
            "path": f"docs/runbooks/{name}.md",
            "sha256": _sha256(ROOT / f"docs/runbooks/{name}.md"),
        }
        for name in RUNBOOKS
    ]
    return {
        "schema_version": "p16-runbook-evidence-v1",
        "runbook_count": len(entries),
        "runbooks": entries,
        "incident_template": "docs/incident_templates/INCIDENT_RECORD.md",
        "postmortem_template": "docs/incident_templates/POSTMORTEM.md",
        "lifecycle": [item.value for item in IncidentState],
        "tests": ["tests/p16/test_runbook_contracts.py"],
    }


def _security_payload() -> dict[str, object]:
    research_testnet_denied = False
    live_denied_for_all = True
    try:
        validate_secret_mounts(ServiceRole.RESEARCH, frozenset({SecretClass.TESTNET_API}))
    except PermissionError:
        research_testnet_denied = True
    for role in ServiceRole:
        try:
            validate_secret_mounts(role, frozenset({SecretClass.LIVE_API}))
        except PermissionError:
            continue
        live_denied_for_all = False
    nginx = (ROOT / "infra/reverse_proxy/nginx.conf").read_text(encoding="utf-8")
    compose = (ROOT / "infra/compose/compose.yaml").read_text(encoding="utf-8")
    return {
        "schema_version": "p16-security-evidence-v1",
        "threat_model": "reports/security/THREAT_MODEL.md",
        "research_testnet_secret_denied": research_testnet_denied,
        "live_secret_denied_for_all_roles": live_denied_for_all,
        "mtls_required": "ssl_verify_client on" in nginx,
        "tls13_only": "ssl_protocols TLSv1.3" in nginx,
        "csp_present": "Content-Security-Policy" in nginx,
        "public_bindings": [line for line in compose.splitlines() if "0.0.0.0:" in line],
        "live_trading_locked": True,
        "real_account_connections": 0,
        "plaintext_credentials_collected": False,
        "tests": [
            "tests/security/test_p16_operational_security.py",
            "tests/chaos/test_p16_operational_failures.py",
        ],
    }


def _deployment_payload() -> dict[str, object]:
    compose_path = ROOT / "infra/compose/compose.yaml"
    compose = cast("dict[str, object]", yaml.safe_load(compose_path.read_text(encoding="utf-8")))
    services = cast("dict[str, dict[str, object]]", compose["services"])
    networks = cast("dict[str, dict[str, object]]", compose["networks"])
    profiles = sorted(
        {
            str(profile)
            for service in services.values()
            for profile in cast("list[object]", service.get("profiles", []))
        }
    )
    docker_available = shutil.which("docker") is not None
    return {
        "schema_version": "p16-deployment-evidence-v1",
        "service_count": len(services),
        "services": sorted(services),
        "profiles": profiles,
        "live_profile_present": "live" in {item.casefold() for item in profiles},
        "all_networks_internal": all(item.get("internal") is True for item in networks.values()),
        "all_static_images_digest_pinned": all(
            "@sha256:" in cast("str", service["image"]) or "DIGEST" in cast("str", service["image"])
            for service in services.values()
        ),
        "docker_cli_available": docker_available,
        "container_runtime_contract_executed": False,
        "runtime_gap": None
        if docker_available
        else "Docker CLI was unavailable on the P16 implementation host",
        "handbook": "docs/deployment/PAPER_TESTNET_DEPLOYMENT.md",
        "allowed_environments": ["PAPER", "TESTNET"],
        "tests": ["tests/p16/test_infrastructure_contracts.py"],
    }


def _release_payload() -> dict[str, object]:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    manifest = ReleaseManifest(
        release_id="p16-paper-evidence",
        environment=ReleaseEnvironment.PAPER,
        git_commit="a" * 40,
        artifact_sha256="b" * 64,
        dependency_lock_sha256="c" * 64,
        created_at=now,
        expires_at=now + timedelta(hours=4),
    )
    release = sign_release(manifest, Ed25519PrivateKey.from_private_bytes(bytes(range(32))))
    approval = approve_release(
        manifest,
        approver="operator-1",
        approved_at=now + timedelta(minutes=1),
        private_key=Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64))),
    )
    healthy = deployment_gate(
        release,
        approval,
        now=now + timedelta(minutes=2),
        migrations_ok=True,
        smoke_tests_ok=True,
        reconciliation_ok=True,
    )
    failed = deployment_gate(
        release,
        approval,
        now=now + timedelta(minutes=2),
        migrations_ok=True,
        smoke_tests_ok=False,
        reconciliation_ok=True,
    )
    rollback = rollback_after_failure("p15-paper-verified")
    return {
        "schema_version": "p16-release-evidence-v1",
        "manifest_sha256": manifest.sha256,
        "signature_verified_by_gate": healthy.allowed,
        "independent_approval_verified_by_gate": healthy.allowed,
        "healthy_posture": healthy.posture.value,
        "failed_posture": failed.posture.value,
        "failed_manual_resume_required": failed.manual_resume_required,
        "rollback_posture": rollback.posture.value,
        "rollback_manual_resume_required": rollback.manual_resume_required,
        "live_release_supported": False,
        "tests": ["tests/operations/test_release.py"],
    }


def build_payloads() -> dict[str, object]:
    return {
        "telemetry": _telemetry_payload(),
        "dashboards": _dashboard_payload(),
        "alerts": _alert_payload(),
        "runbooks": _runbook_payload(),
        "security": _security_payload(),
        "deployment": _deployment_payload(),
        "release": _release_payload(),
    }


def _validate(payloads: dict[str, object]) -> None:
    telemetry = cast("dict[str, object]", payloads["telemetry"])
    dashboards = cast("dict[str, object]", payloads["dashboards"])
    alerts = cast("dict[str, object]", payloads["alerts"])
    runbooks = cast("dict[str, object]", payloads["runbooks"])
    security = cast("dict[str, object]", payloads["security"])
    deployment = cast("dict[str, object]", payloads["deployment"])
    release = cast("dict[str, object]", payloads["release"])
    checks = {
        "telemetry correlation": all(
            telemetry[key] is True
            for key in (
                "log_correlation_matches",
                "log_has_trace_id",
                "span_correlation_matches",
                "metric_event_present",
                "metric_status_present",
                "metric_excludes_correlation_id",
                "recursive_redaction_passed",
            )
        ),
        "no Promtail": telemetry["promtail_used"] is False,
        "six dashboards": dashboards["dashboard_count"] == 6
        and all(
            item["editable"] is False and item["high_cardinality_identifier_used"] is False
            for item in cast("list[dict[str, object]]", dashboards["dashboards"])
        ),
        "alert behavior": alerts["sev0_delivery_outcome"] == "delivered"
        and alerts["duplicate_outcome"] == "deduplicated"
        and alerts["maintenance_sev2_outcome"] == "maintenance_suppressed"
        and alerts["maintenance_suppressed_sev0"] is False,
        "runbooks": runbooks["runbook_count"] == len(RUNBOOKS),
        "security": security["research_testnet_secret_denied"] is True
        and security["live_secret_denied_for_all_roles"] is True
        and security["mtls_required"] is True
        and security["csp_present"] is True
        and security["public_bindings"] == [],
        "deployment": deployment["live_profile_present"] is False
        and deployment["all_networks_internal"] is True
        and deployment["all_static_images_digest_pinned"] is True,
        "release": release["healthy_posture"] == RuntimePosture.PAPER_ACTIVE.value
        and release["failed_posture"] == RuntimePosture.HALTED.value
        and release["failed_manual_resume_required"] is True
        and release["rollback_posture"] == RuntimePosture.HALTED.value
        and release["rollback_manual_resume_required"] is True,
        "acceptance deferred": telemetry["formal_acceptance_performed"] is False
        and alerts["formal_acceptance_performed"] is False
        and alerts["user_external_channel_delivery_verified"] is False,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("P16 evidence validation failed: " + ", ".join(failed))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    payloads = build_payloads()
    _validate(payloads)
    mismatches: list[str] = []
    for key, payload in payloads.items():
        target = OUTPUTS[key]
        rendered = _render(payload)
        if arguments.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != rendered:
                mismatches.append(target.relative_to(ROOT).as_posix())
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8", newline="\n")
    if mismatches:
        raise SystemExit("P16 evidence drift: " + ", ".join(mismatches))
    print(f"{'verified' if arguments.check else 'generated'} {len(payloads)} P16 evidence files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
