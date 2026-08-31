"""Host capability evidence tests."""

import json
from pathlib import Path


def test_host_probe_is_explicit_and_non_secret(project_root: Path) -> None:
    payload = json.loads(
        (project_root / "state/HOST_CAPABILITIES.json").read_text(encoding="utf-8")
    )

    assert payload["network_access_performed"] is False
    assert payload["secrets_read"] is False
    assert payload["operating_system"]["system"] == "Windows"
    assert payload["memory"]["total_bytes"] > 0
    assert payload["workspace_disk"]["free_bytes"] > 0
    assert payload["runtimes"]["python"]["version"]
    assert "available" in payload["platform_tools"]["wsl"]
