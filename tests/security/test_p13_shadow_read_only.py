"""P13 Shadow and mode limitations cannot reach trading or credential surfaces."""

from __future__ import annotations

import ast
from pathlib import Path

from aegisquant.runtime.models import MarketModeLimitations
from aegisquant.runtime.shadow import ShadowRuntime


def test_shadow_source_has_no_adapter_environment_or_write_surface(project_root: Path) -> None:
    path = project_root / "src/aegisquant/runtime/shadow.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    methods = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "ExecutionAdapter" not in source
    assert "os.environ" not in source
    assert "getenv(" not in source
    assert not any(name.endswith("adapter") for name in imported)
    assert methods.isdisjoint({"submit", "cancel", "amend", "place_order", "send_order"})
    assert not any(hasattr(ShadowRuntime(), name) for name in ("submit", "cancel", "amend"))


def test_runtime_tree_has_no_production_endpoint_or_secret_read(project_root: Path) -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((project_root / "src/aegisquant/runtime").glob("*.py"))
    ).lower()
    assert "api.binance.com" not in source
    assert "fapi.binance.com" not in source
    assert "api_secret" not in source
    assert "cookie" not in source
    assert "password" not in source
    limitations = MarketModeLimitations(reason_codes=("AQ-RUNTIME-P13-SAFE",))
    assert limitations.shadow_has_write_capability is False
    assert limitations.real_account_access_performed is False
    assert limitations.venue_network_requests_performed == 0
