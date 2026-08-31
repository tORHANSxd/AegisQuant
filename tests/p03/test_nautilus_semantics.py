"""Nautilus 1.231.0 public route and instrument naming semantic contract."""

import pytest

from aegisquant.data.providers.binance.nautilus_compat import inspect_installed_nautilus


@pytest.mark.nautilus
def test_nautilus_uses_current_usdm_public_and_market_routes_without_credentials() -> None:
    semantics = inspect_installed_nautilus()
    assert semantics.installed_version == "1.231.0"
    assert semantics.routes_match_p03_contract is True
    assert semantics.usdm_public_ws_base.endswith("/public")
    assert semantics.usdm_market_ws_base.endswith("/market")
    assert semantics.spot_instrument_example == "BTCUSDT.BINANCE"
    assert semantics.usdm_instrument_example == "BTCUSDT-PERP.BINANCE"
    assert semantics.credentials_accessed is False
