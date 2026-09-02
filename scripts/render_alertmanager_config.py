"""Render an operator-channel Alertmanager config without printing the endpoint."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from aegisquant.observability.alerts import WebhookChannel

RENDER_MARKER = "__AEGISQUANT_OPERATOR_WEBHOOK__"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template", type=Path, default=Path("infra/alertmanager/alertmanager.template.yml")
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    endpoint = os.environ.get("AEGISQUANT_OPERATOR_WEBHOOK_URL")
    if endpoint is None:
        raise SystemExit("AEGISQUANT_OPERATOR_WEBHOOK_URL is required")
    WebhookChannel(name="operator", url=endpoint)
    template = arguments.template.read_text(encoding="utf-8")
    if template.count(RENDER_MARKER) != 2:
        raise SystemExit("Alertmanager template must contain exactly two channel tokens")
    rendered = template.replace(RENDER_MARKER, endpoint)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(rendered, encoding="utf-8", newline="\n")
    os.chmod(arguments.output, 0o600)
    print(f"rendered Alertmanager config: {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
