"""Installed Nautilus Binance execution compatibility contract."""

from __future__ import annotations

import pytest

from aegisquant.execution.nautilus_contract import inspect_nautilus_binance_contract


@pytest.mark.nautilus
def test_installed_nautilus_execution_contract_is_inspected_without_instantiation() -> None:
    contract = inspect_nautilus_binance_contract()
    assert contract.package_version == "1.231.0"
    assert contract.config_class == "BinanceExecClientConfig"
    assert {"environment", "base_url_ws", "base_url_ws_stream"} <= set(contract.config_fields)
    assert {"submit_order", "cancel_order", "generate_fill_reports"} <= set(
        contract.execution_methods
    )
    assert {"TESTNET", "DEMO"} <= set(contract.supported_environments)
    assert contract.instantiated is False
    assert contract.network_requests_performed == 0
