"""REST pagination, filtering, error, and read-only boundary contracts."""
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegisquant.api import create_app
from aegisquant.readmodels.bootstrap import build_snapshot


@pytest.fixture
def client(project_root: Path) -> TestClient:
    return TestClient(create_app(build_snapshot(project_root)))


def test_health_and_overview_disclose_nonproduction_safety(client: TestClient) -> None:
    health = client.get("/api/v1/health")
    overview = client.get("/api/v1/overview")

    assert health.status_code == 200
    assert health.headers["cache-control"] == "no-store"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.json()["live_trading_locked"] is True
    assert health.json()["real_account_connected"] is False
    assert health.json()["trading_write_capability"] is False
    assert overview.status_code == 200
    assert overview.json()["account"]["payload"]["environment"] == "RESEARCH"
    assert overview.json()["live_trading_locked"] is True


def test_cursor_filter_and_error_contract(client: TestClient) -> None:
    first = client.get("/api/v1/orders", params={"limit": 1})
    assert first.status_code == 200
    assert len(first.json()["items"]) == 1
    cursor = first.json()["page"]["next_cursor"]
    assert cursor

    second = client.get("/api/v1/orders", params={"limit": 1, "cursor": cursor})
    assert second.status_code == 200
    assert second.json()["items"][0]["entity_id"] != first.json()["items"][0]["entity_id"]

    filtered = client.get("/api/v1/orders", params={"status": "FILLED"})
    assert filtered.status_code == 200
    assert all(item["payload"]["status"] == "FILLED" for item in filtered.json()["items"])

    invalid = client.get("/api/v1/orders", params={"cursor": "not-a-cursor"})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "AQ-API-INVALID-CURSOR"
    assert invalid.json()["error"]["correlation_id"]


def test_unknown_resource_and_untrusted_host_fail_closed(client: TestClient) -> None:
    missing = client.get("/api/v1/intelligence/events/not-found")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "AQ-API-NOT-FOUND"

    denied = client.get("/api/v1/health", headers={"host": "remote.example"})
    assert denied.status_code == 400


def test_no_http_trading_write_surface(client: TestClient) -> None:
    document = client.get("/api/v1/openapi.json").json()
    operations = {
        method
        for path in document["paths"].values()
        for method in path
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert operations == {"get"}
    for path in document["paths"]:
        normalized = path.casefold()
        assert not any(term in normalized for term in ("submit", "cancel", "amend", "unlock"))
