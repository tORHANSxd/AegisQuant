from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import yaml


def test_compose_is_digest_pinned_private_and_least_privilege(project_root: Path) -> None:
    compose_path = project_root / "infra/compose/compose.yaml"
    text = compose_path.read_text(encoding="utf-8")
    compose = cast("dict[str, object]", yaml.safe_load(text))
    services = cast("dict[str, dict[str, object]]", compose["services"])
    networks = cast("dict[str, dict[str, object]]", compose["networks"])
    lock = json.loads((project_root / "infra/compose/IMAGE_LOCK.json").read_text(encoding="utf-8"))
    locked = {item["reference"] for item in lock["images"]}

    assert all(settings["internal"] is True for settings in networks.values())
    assert ":latest" not in text.casefold()
    assert "promtail" not in text.casefold()
    assert "docker.sock" not in text
    for name, service in services.items():
        image = cast("str", service["image"])
        if "${" not in image:
            assert image in locked, name
        else:
            assert "DIGEST" in image, name
        assert service.get("privileged") is not True
        assert service.get("network_mode") != "host"
        for published in cast("list[str]", service.get("ports", [])):
            assert str(published).startswith("127.0.0.1:"), (name, published)
    assert set(cast("list[str]", services["reverse-proxy"]["secrets"])) >= {
        "tls_certificate",
        "tls_private_key",
        "operator_client_ca",
    }


def test_dockerfiles_pin_base_digests_and_web_uses_standalone(project_root: Path) -> None:
    for name in ("Dockerfile.api", "Dockerfile.web"):
        lines = (project_root / f"infra/docker/{name}").read_text(encoding="utf-8").splitlines()
        from_lines = [line for line in lines if line.startswith("FROM ")]
        assert from_lines and all("@sha256:" in line for line in from_lines)
    next_config = (project_root / "apps/web/next.config.ts").read_text(encoding="utf-8")
    assert 'output: "standalone"' in next_config


def test_six_dashboards_are_provisioned_and_use_low_cardinality_metrics(project_root: Path) -> None:
    directory = project_root / "infra/grafana/dashboards"
    files = sorted(directory.glob("*.json"))
    assert [path.stem for path in files] == [
        "business",
        "data",
        "infrastructure",
        "model",
        "risk",
        "trading",
    ]
    for path in files:
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        assert dashboard["editable"] is False
        assert len(dashboard["panels"]) == 4
        expressions = " ".join(panel["targets"][0]["expr"] for panel in dashboard["panels"])
        assert "order_id" not in expressions
        assert "correlation_id" not in expressions


def test_observability_configs_link_metrics_logs_traces_and_alerts(project_root: Path) -> None:
    alloy = (project_root / "infra/alloy/config.alloy").read_text(encoding="utf-8")
    datasources = (
        project_root / "infra/grafana/provisioning/datasources/datasources.yml"
    ).read_text(encoding="utf-8")
    rules = yaml.safe_load(
        (project_root / "infra/prometheus/alerts.yml").read_text(encoding="utf-8")
    )
    alert_rules = rules["groups"][0]["rules"]
    severities = {rule["labels"]["severity"] for rule in alert_rules}
    assert "loki.source.file" in alloy
    assert "otelcol.receiver.otlp" in alloy
    assert "otelcol.exporter.otlphttp" in alloy
    assert "correlation_id" in alloy and "trace_id" in alloy
    assert "tracesToLogsV2" in datasources
    assert severities >= {"SEV0", "SEV1", "SEV2"}
    assert all("runbook" in rule["annotations"] for rule in alert_rules)


def test_reverse_proxy_requires_mtls_and_sets_csp(project_root: Path) -> None:
    config = (project_root / "infra/reverse_proxy/nginx.conf").read_text(encoding="utf-8")
    assert "listen 8443 ssl" in config
    assert "ssl_verify_client on" in config
    assert "ssl_protocols TLSv1.3" in config
    assert "Content-Security-Policy" in config
    assert "127.0.0.1:8443:8443" in (project_root / "infra/compose/compose.yaml").read_text(
        encoding="utf-8"
    )
