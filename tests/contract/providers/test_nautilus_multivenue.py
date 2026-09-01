from __future__ import annotations

from aegisquant.data.providers.public import nautilus_adapter_compatibility


def test_nautilus_adapter_discovery_keeps_real_native_fallback() -> None:
    result = nautilus_adapter_compatibility()
    assert set(result) == {"OKX", "BYBIT", "DERIBIT"}
    for item in result.values():
        assert isinstance(item["available"], bool)
        module = item["module"]
        assert isinstance(module, str) and module.startswith("nautilus_trader.adapters.")
        assert item["native_fallback"] == ("aegisquant.data.providers.public.PublicExchangeAdapter")
