"""P00 access request and deny-by-default tests."""

from pathlib import Path

import yaml


def test_access_requests_never_request_secret_values(project_root: Path) -> None:
    payload = yaml.safe_load(
        (project_root / "reports/access/SOURCE_ACCESS_REQUESTS.yaml").read_text(encoding="utf-8")
    )

    assert all(request["secret"] is False for request in payload["requests"])
    assert all(request["required_for_p00"] is False for request in payload["requests"])
    assert "api_secret" in payload["prohibited_values"]
    assert {request["request_id"] for request in payload["requests"]} >= {
        "P00-INPUT-JOINQUANT",
        "P00-INPUT-X-DEVELOPER",
        "P00-INPUT-TELEGRAM",
        "P00-INPUT-YOUTUBE-GITHUB",
        "P00-INPUT-NEWS-SUBSCRIPTIONS",
        "P00-INPUT-TESTNET",
        "P00-INPUT-RISK-PREFERENCES",
    }


def test_data_access_state_records_no_connection(project_root: Path) -> None:
    payload = yaml.safe_load(
        (project_root / "state/DATA_ACCESS_STATUS.yaml").read_text(encoding="utf-8")
    )

    assert payload["external_network_data_collection"] == "disabled"
    assert payload["real_trading_account_connection"] == "disabled"
    assert payload["secret_loading"] == "disabled"
    assert payload["credentials_received"] == 0
    assert payload["plaintext_secrets_written"] == 0
