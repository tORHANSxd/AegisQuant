"""P15 API composes one read-only snapshot across every workbench page."""
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aegisquant.api import create_app
from aegisquant.readmodels.p15_bootstrap import build_p15_snapshot


def test_workbench_and_domain_routes_share_snapshot(project_root: Path) -> None:
    client = TestClient(create_app(build_p15_snapshot(project_root)))
    response = client.get("/api/v1/workbench")
    assert response.status_code == 200
    payload = response.json()
    assert payload["live_trading_locked"] is True
    assert payload["evidence"] == {
        "evidence_tier": "FIXTURE",
        "alpha_promotion_eligible": False,
        "source_artifacts": [
            "reports/backtests/p06-golden/run_manifest.json",
            "reports/backtests/p06-golden/equity_curve.parquet",
            "reports/backtests/p06-golden/pnl_attribution.parquet",
        ],
        "reason_codes": [
            "GOLDEN_TEST_FIXTURE",
            "PLACEHOLDER_HASHES",
            "EXTREME_SHORT_WINDOW",
            "NO_ALPHA_PROMOTION",
        ],
    }
    assert payload["capabilities"] == {
        "read_only": True,
        "trading_write": False,
        "real_account_connection": False,
        "risk_limit_edit": False,
        "model_publish": False,
        "live_unlock": False,
    }
    assert payload["reconciliation"]["payload"]["state"] == "SYNCHRONIZED"
    assert payload["market"] and payload["research_runs"] and payload["incidents"]

    paths = (
        "/api/v1/signals",
        "/api/v1/fills",
        "/api/v1/execution/quality",
        "/api/v1/market/state",
        "/api/v1/research/runs",
        "/api/v1/incidents",
        "/api/v1/system/health",
        "/api/v1/reconciliation/status",
        "/api/v1/risk/limits",
        "/api/v1/models/metrics",
    )
    assert all(client.get(path).status_code == 200 for path in paths)


def test_every_visible_order_has_complete_honest_trace(project_root: Path) -> None:
    client = TestClient(create_app(build_p15_snapshot(project_root)))
    orders = client.get("/api/v1/orders").json()["items"]
    assert orders
    for order in orders:
        trace = client.get(f"/api/v1/orders/{order['entity_id']}/trace")
        assert trace.status_code == 200
        payload = trace.json()["payload"]
        assert payload["complete"] is True
        assert payload["causal_link_overclaimed"] is False
        assert len(payload["stages"]) == 7
        assert all(item["status"] != "NOT_AVAILABLE" for item in payload["stages"])


def test_downsample_and_etag_contract(project_root: Path) -> None:
    client = TestClient(create_app(build_p15_snapshot(project_root)))
    equity = client.get("/api/v1/accounts/paper-account/equity", params={"max_points": 4})
    assert equity.status_code == 200
    assert equity.json()["returned_count"] <= 4
    assert equity.headers["cache-control"] == "private, max-age=0, must-revalidate"
    etag = equity.headers["etag"]
    unchanged = client.get(
        "/api/v1/accounts/paper-account/equity",
        params={"max_points": 4},
        headers={"if-none-match": etag},
    )
    assert unchanged.status_code == 304
    assert unchanged.headers["etag"] == etag
