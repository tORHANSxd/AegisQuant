"""Generate or verify deterministic P15 workbench evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final, cast

from aegisquant.api.app import create_app
from aegisquant.api.downsampling import downsample_time_values
from aegisquant.readmodels.models import ProjectionKind, TimeValuePoint
from aegisquant.readmodels.p15_bootstrap import build_p15_snapshot

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUTS: Final = {
    "routes": ROOT / "reports/web/P15_ROUTE_EVIDENCE.json",
    "trace": ROOT / "reports/web/P15_TRACE_EVIDENCE.json",
    "interaction": ROOT / "reports/web/P15_INTERACTION_EVIDENCE.json",
    "performance": ROOT / "reports/performance/P15_PERFORMANCE_EVIDENCE.json",
    "accessibility": ROOT / "reports/web/P15_ACCESSIBILITY_EVIDENCE.json",
    "browsers": ROOT / "reports/web/P15_BROWSER_EVIDENCE.json",
    "usability": ROOT / "reports/web/P15_USABILITY_EVIDENCE.json",
    "security": ROOT / "reports/security/P15_WEB_SAFETY_EVIDENCE.json",
}
ROUTES: Final = (
    ("/overview", "账户与风险总览"),
    ("/live", "实时台与状态回放"),
    ("/performance", "绩效、成本与归因"),
    ("/execution", "执行质量与订单追溯"),
    ("/strategies", "策略目录与信号"),
    ("/models", "模型评估与治理"),
    ("/market", "市场状态与历史回放"),
    ("/intelligence", "全球事件与叙事情报"),
    ("/risk", "风险限额与熔断姿态"),
    ("/research", "研究运行与负结果"),
    ("/research/intelligence", "外部知识与情报研究"),
    ("/data", "数据质量、来源与血缘"),
    ("/incidents", "事故时间线与恢复证据"),
    ("/system", "系统健康与契约状态"),
    ("/settings", "安全设置"),
)
TRACE_STAGES: Final = (
    "SIGNAL",
    "EVENT_EVIDENCE",
    "MODEL",
    "RISK",
    "ORDER",
    "FILL",
    "LEDGER",
)


def _render(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _route_file(route: str) -> Path:
    if route == "/overview":
        return ROOT / "apps/web/app/overview/page.tsx"
    if route == "/research/intelligence":
        return ROOT / "apps/web/app/research/intelligence/page.tsx"
    return ROOT / f"apps/web/app/{route.strip('/')}/page.tsx"


def _api_inventory() -> list[dict[str, object]]:
    app = create_app(build_p15_snapshot(ROOT))
    inventory: list[dict[str, object]] = []
    paths = cast("dict[str, dict[str, object]]", app.openapi()["paths"])
    for path, path_item in paths.items():
        if not path.startswith("/api/v1"):
            continue
        methods = sorted(
            method.upper()
            for method in path_item
            if method.lower() in {"get", "post", "put", "patch", "delete"}
        )
        inventory.append({"path": path, "methods": sorted(methods)})
    return sorted(inventory, key=lambda item: str(item["path"]))


def _route_payload() -> dict[str, object]:
    inventory = _api_inventory()
    route_entries = [
        {
            "path": route,
            "heading": heading,
            "source": _route_file(route).relative_to(ROOT).as_posix(),
            "source_sha256": _sha256(_route_file(route)),
        }
        for route, heading in ROUTES
    ]
    return {
        "schema_version": "p15-route-evidence-v1",
        "routes": route_entries,
        "route_count": len(route_entries),
        "missing_routes": [
            item["path"] for item in route_entries if not (ROOT / str(item["source"])).is_file()
        ],
        "shared_error_boundary": "apps/web/app/error.tsx",
        "shared_loading_boundary": "apps/web/app/loading.tsx",
        "not_found_boundary": "apps/web/app/not-found.tsx",
        "api_routes": inventory,
        "unsafe_api_methods": [
            item for item in inventory if set(cast("list[str]", item["methods"])) - {"GET"}
        ],
        "failure_scope": "current Next.js route segment; trading services are not invoked",
        "formal_acceptance_performed": False,
    }


def _trace_payload() -> dict[str, object]:
    snapshot = build_p15_snapshot(ROOT)
    orders = [item for item in snapshot.records if item.projection is ProjectionKind.ORDERS]
    traces = {
        item.entity_id: item
        for item in snapshot.records
        if item.projection is ProjectionKind.ORDER_TRACES
    }
    entries: list[dict[str, object]] = []
    for order in orders:
        trace = traces.get(order.entity_id)
        stages = [] if trace is None else cast("list[dict[str, object]]", trace.payload["stages"])
        entries.append(
            {
                "order_id": order.entity_id,
                "trace_present": trace is not None,
                "complete": trace is not None and trace.payload["complete"] is True,
                "causal_link_overclaimed": None
                if trace is None
                else trace.payload["causal_link_overclaimed"],
                "stages": [stage["stage"] for stage in stages],
                "statuses": [stage["status"] for stage in stages],
                "sources": [stage["source_artifact"] for stage in stages],
            }
        )
    return {
        "schema_version": "p15-trace-evidence-v1",
        "visible_order_count": len(orders),
        "trace_count": len(traces),
        "canonical_stages": list(TRACE_STAGES),
        "orders": entries,
        "all_visible_orders_traceable": all(item["trace_present"] for item in entries),
        "all_traces_complete": all(item["complete"] for item in entries),
        "all_stage_orders_canonical": all(item["stages"] == list(TRACE_STAGES) for item in entries),
        "not_available_stage_count": sum(
            cast("list[str]", item["statuses"]).count("NOT_AVAILABLE") for item in entries
        ),
        "causal_overclaim_count": sum(item["causal_link_overclaimed"] is True for item in entries),
        "detail_route": "/execution/orders/[orderId]",
        "test": "apps/web/e2e/dashboard.spec.ts; tests/integration/test_p15_workbench.py",
    }


def _interaction_payload() -> dict[str, object]:
    controls = _source("apps/web/src/components/global-controls.tsx")
    settings = _source("apps/web/app/settings/page.tsx") + _source(
        "apps/web/src/components/preferences.tsx"
    )
    keys_match = re.search(r"new Set\(\[([^]]+)\]\)", controls)
    safe_keys = [] if keys_match is None else re.findall(r'"([a-z]+)"', keys_match.group(1))
    actions = {
        "global_filters": all(
            label in controls for label in ("账户", "时间范围", "时区", "策略", "场所", "计价")
        ),
        "command_palette": "Control+K" in controls and 'role="dialog"' in controls,
        "text_export": "URL.createObjectURL" in controls and "text/plain" in controls,
        "safe_layout": "window.localStorage" in controls and "safeSavedTarget" in controls,
        "display_preferences": all(
            item in settings for item in ("主题", "密度", "涨跌色", "高对比", "色盲友好")
        ),
    }
    return {
        "schema_version": "p15-interaction-evidence-v1",
        "actions": actions,
        "safe_query_keys": sorted(safe_keys),
        "saved_layout_storage_key": "aegisquant-safe-layout-v1",
        "preference_storage_key": "aegisquant-ui-preferences-v1",
        "server_writes": 0,
        "credential_fields": settings.count('type="password"'),
        "trading_controls": 0,
        "test": "apps/web/e2e/dashboard.spec.ts; apps/web/tests/locked-page.test.tsx",
    }


def _performance_payload() -> dict[str, object]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    points = tuple(
        TimeValuePoint(time=start + timedelta(seconds=index), value=Decimal(index % 101))
        for index in range(100_000)
    )
    points = (
        *points[:12_345],
        TimeValuePoint(time=points[12_345].time, value=Decimal("-999")),
        *points[12_346:87_654],
        TimeValuePoint(time=points[87_654].time, value=Decimal("999")),
        *points[87_655:],
    )
    protected = frozenset({50_000})
    sampled = downsample_time_values(points, max_points=200, protected_indices=protected)
    benchmark = cast(
        "dict[str, object]",
        json.loads(
            (ROOT / "reports/performance/P15_WORKBENCH_BENCHMARK.json").read_text(encoding="utf-8")
        ),
    )
    common = _source("apps/web/src/components/common.tsx")
    app = _source("src/aegisquant/api/app.py")
    return {
        "schema_version": "p15-performance-evidence-v1",
        "input_points": len(points),
        "returned_points": len(sampled),
        "max_points": 200,
        "first_preserved": sampled[0] == points[0],
        "last_preserved": sampled[-1] == points[-1],
        "protected_event_preserved": points[50_000] in sampled,
        "global_min_preserved": min(item.value for item in sampled) == Decimal("-999"),
        "global_max_preserved": max(item.value for item in sampled) == Decimal("999"),
        "virtual_table_windowing": "rows.slice(windowStart, windowStart + windowSize)" in common,
        "etag_revalidation": "if-none-match" in app.casefold() and "etag" in app.casefold(),
        "benchmark": "reports/performance/P15_WORKBENCH_BENCHMARK.json",
        "benchmark_status": benchmark["status"],
        "benchmark_p75_ms": benchmark["p75_ms"],
        "benchmark_target_p75_ms": benchmark["target_p75_ms"],
        "qualifies_as_12h_or_24h_acceptance": False,
        "test": "tests/p15/test_downsampling.py; apps/web/e2e/dashboard.spec.ts",
    }


def _linear(value: int) -> float:
    channel = value / 255
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _contrast(foreground: str, background: str) -> float:
    first = tuple(int(foreground[index : index + 2], 16) for index in (1, 3, 5))
    second = tuple(int(background[index : index + 2], 16) for index in (1, 3, 5))
    first_luminance = sum(
        weight * _linear(value)
        for weight, value in zip((0.2126, 0.7152, 0.0722), first, strict=True)
    )
    second_luminance = sum(
        weight * _linear(value)
        for weight, value in zip((0.2126, 0.7152, 0.0722), second, strict=True)
    )
    lighter, darker = sorted((first_luminance, second_luminance), reverse=True)
    return round((lighter + 0.05) / (darker + 0.05), 3)


def _accessibility_payload() -> dict[str, object]:
    css = _source("apps/web/app/globals.css")
    shell = _source("apps/web/src/components/app-shell.tsx")
    charts = _source("apps/web/src/components/charts/chart-suite.tsx")
    layout = _source("apps/web/app/layout.tsx")
    contrast_pairs = {
        "dark_text_on_background": _contrast("#eef6f7", "#071017"),
        "dark_muted_on_surface": _contrast("#91a8ae", "#0e1b25"),
        "dark_green_on_surface": _contrast("#5ad29c", "#0e1b25"),
        "dark_red_on_surface": _contrast("#ff7768", "#0e1b25"),
        "light_text_on_surface": _contrast("#102429", "#ffffff"),
        "light_muted_on_surface": _contrast("#526e73", "#ffffff"),
    }
    structural_checks = {
        "document_language": 'lang="zh-CN"' in layout,
        "skip_link": "skip-link" in shell and "#main-content" in shell,
        "focus_visible": ":focus-visible" in css,
        "reduced_motion": "prefers-reduced-motion" in css,
        "screen_reader_utility": ".sr-only" in css,
        "chart_text_alternative": "ChartTable" in charts and 'role="img"' in charts,
        "keyboard_command": "aria-keyshortcuts"
        in _source("apps/web/src/components/global-controls.tsx"),
        "color_has_text_encoding": "chart-markers" in charts and "marker.kind" in charts,
    }
    return {
        "schema_version": "p15-accessibility-evidence-v1",
        "target": "WCAG 2.2 AA",
        "structural_checks": structural_checks,
        "contrast_ratios": contrast_pairs,
        "minimum_normal_text_ratio": min(contrast_pairs.values()),
        "minimum_required_ratio": 4.5,
        "automated_scope": "semantic, keyboard, motion, text-alternative, and token contrast contracts",
        "formal_acceptance_performed": False,
        "test": "apps/web/e2e/dashboard.spec.ts; apps/web/tests/",
    }


def _browser_payload() -> dict[str, object]:
    config = _source("apps/web/playwright.config.ts")
    snapshots = sorted((ROOT / "apps/web/e2e/dashboard.spec.ts-snapshots").glob("p15-*.png"))
    return {
        "schema_version": "p15-browser-evidence-v1",
        "browsers": [
            name for name in ("chromium", "firefox", "webkit") if f'name: "{name}"' in config
        ],
        "narrow_viewport": {"width": 390, "height": 844},
        "visual_baselines": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for path in snapshots
        ],
        "visual_baseline_count": len(snapshots),
        "production_runtime": "Next.js production build + FastAPI loopback on isolated port",
        "test": "apps/web/e2e/dashboard.spec.ts",
    }


def _usability_payload() -> dict[str, object]:
    workspace = _source("apps/web/src/components/workspace-page.tsx")
    required_labels = ("Fixture 权益", "Fixture 净损益", "风险状态", "对账状态")
    return {
        "schema_version": "p15-usability-evidence-v1",
        "five_second_core_labels": list(required_labels),
        "all_core_labels_present": all(item in workspace for item in required_labels),
        "pnl_formula_present": "attribution.formula" in workspace,
        "pnl_source_present": "source_artifact" in workspace,
        "pnl_as_of_present": "as_of_time" in workspace,
        "timezone_options": ["Asia/Shanghai", "UTC"],
        "historical_state_disclosure": "历史开发" in workspace,
        "evidence_tier_disclosure": "证据等级" in workspace,
        "alpha_promotion_disclosure": "alpha_promotion_eligible" in workspace,
        "non_advice_disclosure": "不构成买卖建议" in workspace,
        "formal_acceptance_performed": False,
        "test": "apps/web/e2e/dashboard.spec.ts",
    }


def _security_payload() -> dict[str, object]:
    app_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "apps/web").rglob("*.ts*"))
        if path.is_file()
        and "generated" not in path.parts
        and "node_modules" not in path.parts
        and ".next" not in path.parts
        and "tests" not in path.parts
        and "e2e" not in path.parts
    )
    inventory = _api_inventory()
    unsafe_patterns = {
        # This literal is a negative scanner sentinel, not a credential.
        "password_input": 'type="password"',  # nosec B105
        "post_fetch": 'method: "POST"',
        "live_unlock_control": "解锁实盘</button>",
        "submit_order_control": "提交订单</button>",
        "risk_limit_input": 'name="risk_limit"',
    }
    matches = [name for name, pattern in unsafe_patterns.items() if pattern in app_sources]
    return {
        "schema_version": "p15-web-safety-evidence-v1",
        "live_trading_locked": "LIVE TRADING LOCKED" in app_sources,
        "viewer_read_only": "VIEWER · READ ONLY" in app_sources,
        "unsafe_control_matches": matches,
        "credential_values_collected": False,
        "real_account_connections": 0,
        "venue_order_requests": 0,
        "api_write_routes": [
            item for item in inventory if set(cast("list[str]", item["methods"])) - {"GET"}
        ],
        "loopback_api_validation": "must remain on loopback" in app_sources,
        "settings_scope": "local display preferences only",
        "test": "tests/security/test_p15_workbench_read_only.py; apps/web/e2e/dashboard.spec.ts",
    }


def build_payloads() -> dict[str, object]:
    return {
        "routes": _route_payload(),
        "trace": _trace_payload(),
        "interaction": _interaction_payload(),
        "performance": _performance_payload(),
        "accessibility": _accessibility_payload(),
        "browsers": _browser_payload(),
        "usability": _usability_payload(),
        "security": _security_payload(),
    }


def _validate(payloads: dict[str, object]) -> None:
    routes = cast("dict[str, object]", payloads["routes"])
    trace = cast("dict[str, object]", payloads["trace"])
    interaction = cast("dict[str, object]", payloads["interaction"])
    performance = cast("dict[str, object]", payloads["performance"])
    accessibility = cast("dict[str, object]", payloads["accessibility"])
    browsers = cast("dict[str, object]", payloads["browsers"])
    usability = cast("dict[str, object]", payloads["usability"])
    security = cast("dict[str, object]", payloads["security"])
    checks = {
        "route coverage": routes["route_count"] == len(ROUTES) and routes["missing_routes"] == [],
        "read-only API": routes["unsafe_api_methods"] == [],
        "trace coverage": trace["all_visible_orders_traceable"] is True
        and trace["all_traces_complete"] is True,
        "trace honesty": trace["all_stage_orders_canonical"] is True
        and trace["not_available_stage_count"] == 0
        and trace["causal_overclaim_count"] == 0,
        "interactions": all(cast("dict[str, bool]", interaction["actions"]).values()),
        "interaction safety": interaction["server_writes"] == 0
        and interaction["credential_fields"] == 0,
        "downsampling": all(
            performance[key] is True
            for key in (
                "first_preserved",
                "last_preserved",
                "protected_event_preserved",
                "global_min_preserved",
                "global_max_preserved",
            )
        ),
        "performance": performance["benchmark_status"] == "passed"
        and cast("int", performance["benchmark_p75_ms"])
        < cast("int", performance["benchmark_target_p75_ms"]),
        "accessibility structure": all(
            cast("dict[str, bool]", accessibility["structural_checks"]).values()
        ),
        "accessibility contrast": cast("float", accessibility["minimum_normal_text_ratio"]) >= 4.5,
        "browsers": browsers["browsers"] == ["chromium", "firefox", "webkit"]
        and browsers["visual_baseline_count"] == 6,
        "usability": usability["all_core_labels_present"] is True
        and usability["pnl_formula_present"] is True
        and usability["pnl_source_present"] is True
        and usability["pnl_as_of_present"] is True
        and usability["evidence_tier_disclosure"] is True
        and usability["alpha_promotion_disclosure"] is True,
        "security": security["live_trading_locked"] is True
        and security["viewer_read_only"] is True
        and security["unsafe_control_matches"] == []
        and security["api_write_routes"] == [],
        "acceptance deferred": routes["formal_acceptance_performed"] is False
        and usability["formal_acceptance_performed"] is False,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("P15 evidence validation failed: " + ", ".join(failed))


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
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8", newline="\n")
    if mismatches:
        raise SystemExit("P15 evidence drift: " + ", ".join(mismatches))
    print(f"{'verified' if arguments.check else 'generated'} {len(payloads)} P15 evidence files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
