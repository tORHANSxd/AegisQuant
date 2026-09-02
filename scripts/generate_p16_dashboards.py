"""Generate deterministic Grafana dashboards for the six P16 domains."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Final

Panel = tuple[str, str, str]
DASHBOARDS: Final[dict[str, tuple[str, tuple[Panel, ...]]]] = {
    "business": (
        "业务健康",
        (
            ("权威账本延迟", "max(aegisquant_ledger_lag_seconds)", "s"),
            ("未解决对账差异", "sum(aegisquant_reconciliation_mismatches)", "short"),
            ("只读 API 请求率", "sum(rate(aegisquant_api_requests_total[5m]))", "reqps"),
            ("风险姿态", "max by (state) (aegisquant_risk_state)", "short"),
        ),
    ),
    "trading": (
        "交易与执行",
        (
            ("订单阶段速率", "sum by (stage) (rate(aegisquant_orders_total[5m]))", "ops"),
            (
                "执行未知状态",
                'sum(rate(aegisquant_events_total{event_type="execution",status="unknown"}[5m]))',
                "ops",
            ),
            ("成交事件速率", 'sum(rate(aegisquant_events_total{event_type="fill"}[5m]))', "ops"),
            ("Kill switch", "max(aegisquant_kill_switch_active)", "bool_on_off"),
        ),
    ),
    "risk": (
        "风险与对账",
        (
            ("风险状态", "max by (state) (aegisquant_risk_state)", "short"),
            (
                "风险拒绝速率",
                'sum(rate(aegisquant_events_total{event_type="risk",status="rejected"}[5m]))',
                "ops",
            ),
            ("对账差异", "sum(aegisquant_reconciliation_mismatches)", "short"),
            ("账本延迟", "max(aegisquant_ledger_lag_seconds)", "s"),
        ),
    ),
    "data": (
        "数据质量",
        (
            ("数据源延迟", "max by (provider_tier) (aegisquant_provider_lag_seconds)", "s"),
            (
                "序列缺口速率",
                "sum by (provider_tier) (rate(aegisquant_sequence_gaps_total[5m]))",
                "ops",
            ),
            ("隔离行数", "sum by (data_domain) (aegisquant_quarantine_rows)", "short"),
            (
                "市场事件错误",
                'sum(rate(aegisquant_events_total{event_type="market",status!="ok"}[5m]))',
                "ops",
            ),
        ),
    ),
    "model": (
        "模型与研究",
        (
            (
                "推断 P95",
                "histogram_quantile(0.95, sum by (le, model_family) (rate(aegisquant_model_inference_duration_seconds_bucket[5m])))",
                "s",
            ),
            (
                "推断错误率",
                'sum(rate(aegisquant_events_total{event_type="inference",status="error"}[5m]))',
                "ops",
            ),
            (
                "推断超时率",
                'sum(rate(aegisquant_events_total{event_type="inference",status="timeout"}[5m]))',
                "ops",
            ),
            ("降级事件率", 'sum(rate(aegisquant_events_total{status="degraded"}[5m]))', "ops"),
        ),
    ),
    "infrastructure": (
        "基础设施",
        (
            ("CPU 使用率", '1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))', "percentunit"),
            (
                "内存使用率",
                "1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes",
                "percentunit",
            ),
            (
                "磁盘使用率",
                'max(1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"})',
                "percentunit",
            ),
            ("时钟偏差", "max(abs(node_timex_offset_seconds))", "s"),
        ),
    ),
}


def dashboard_payload(slug: str, title: str, panels: tuple[Panel, ...]) -> dict[str, object]:
    rendered_panels: list[dict[str, object]] = []
    for index, (panel_title, expression, unit) in enumerate(panels, start=1):
        rendered_panels.append(
            {
                "id": index,
                "title": panel_title,
                "type": "timeseries",
                "datasource": {"type": "prometheus", "uid": "prometheus"},
                "gridPos": {
                    "h": 8,
                    "w": 12,
                    "x": ((index - 1) % 2) * 12,
                    "y": ((index - 1) // 2) * 8,
                },
                "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
                "options": {"legend": {"displayMode": "table", "placement": "bottom"}},
                "targets": [
                    {
                        "expr": expression,
                        "legendFormat": "{{service}} {{state}} {{stage}} {{provider_tier}}",
                        "refId": "A",
                    }
                ],
            }
        )
    return {
        "annotations": {"list": []},
        "editable": False,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "panels": rendered_panels,
        "refresh": "30s",
        "schemaVersion": 42,
        "tags": ["aegisquant", slug],
        "templating": {"list": []},
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "utc",
        "title": f"AegisQuant · {title}",
        "uid": f"aegisquant-{slug}",
        "version": 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_dir = root / "infra/grafana/dashboards"
    output_dir.mkdir(parents=True, exist_ok=True)
    mismatches: list[str] = []
    for slug, (title, panels) in DASHBOARDS.items():
        output = output_dir / f"{slug}.json"
        rendered = (
            json.dumps(
                dashboard_payload(slug, title, panels),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        if arguments.check:
            if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
                mismatches.append(slug)
        else:
            output.write_text(rendered, encoding="utf-8", newline="\n")
    if mismatches:
        print(f"P16 dashboard drift: {', '.join(mismatches)}")
        return 1
    print(f"P16 dashboards: {len(DASHBOARDS)} {'verified' if arguments.check else 'generated'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
