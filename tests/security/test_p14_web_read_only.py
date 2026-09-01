"""P14 browser and API code must not expose trading writes, venues, or credential inputs."""

from __future__ import annotations

from pathlib import Path


def test_web_uses_only_generated_read_api(project_root: Path) -> None:
    web_root = project_root / "apps/web"
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            *web_root.joinpath("app").rglob("*.tsx"),
            *web_root.joinpath("src").rglob("*.ts"),
        )
        if "src/generated" not in path.as_posix()
    ).casefold()
    assert "aegisquant_api_url" in sources
    assert "127.0.0.1:8000" in sources
    for forbidden in (
        "postgresql://",
        "binance.com",
        "api_secret",
        "password input",
        "live_trading=true",
        "/submit",
        "/cancel",
        "/amend",
    ):
        assert forbidden not in sources


def test_api_routes_have_no_write_decorators(project_root: Path) -> None:
    routes = (project_root / "src/aegisquant/api/routes.py").read_text(encoding="utf-8")
    for method in ("post", "put", "patch", "delete"):
        assert f"@router.{method}(" not in routes
