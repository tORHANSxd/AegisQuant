"""P15 workbench cannot gain trading, credential, or remote-account capabilities."""
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aegisquant.api import create_app
from aegisquant.readmodels.p15_bootstrap import build_p15_snapshot


def test_p15_api_exposes_only_safe_read_methods(project_root: Path) -> None:
    app = create_app(build_p15_snapshot(project_root))
    operations = {
        method.upper()
        for path, path_item in app.openapi()["paths"].items()
        if path.startswith("/api/v1")
        for method in path_item
        if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    assert operations == {"GET"}

    payload = TestClient(app).get("/api/v1/workbench").json()
    assert payload["live_trading_locked"] is True
    assert payload["capabilities"] == {
        "read_only": True,
        "trading_write": False,
        "real_account_connection": False,
        "risk_limit_edit": False,
        "model_publish": False,
        "live_unlock": False,
    }


def test_p15_web_has_no_secret_or_trading_input_surface(project_root: Path) -> None:
    files = [
        path
        for path in (project_root / "apps/web").rglob("*.ts*")
        if "generated" not in path.parts
        and "node_modules" not in path.parts
        and ".next" not in path.parts
        and "tests" not in path.parts
        and "e2e" not in path.parts
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)
    forbidden_controls = (
        'type="password"',
        'method: "POST"',
        "解锁实盘</button>",
        "提交订单</button>",
        'name="risk_limit"',
    )
    assert not [item for item in forbidden_controls if item in source]
    assert "LIVE TRADING LOCKED" in source
    assert "VIEWER · READ ONLY" in source
    assert "must remain on loopback" in source

    proxy = (project_root / "apps/web/proxy.ts").read_text(encoding="utf-8")
    assert 'request.nextUrl.protocol === "https:"' in proxy
    assert "upgrade-insecure-requests" in proxy
    assert not (project_root / "src/aegisquant/live").exists()
