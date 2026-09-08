"""NautilusTrader Binance semantics checked without creating any live client."""

from __future__ import annotations

from pydantic import model_validator

from aegisquant.domain.base import DomainModel


class NautilusBinanceSemantics(DomainModel):
    installed_version: str
    spot_market_ws_base: str
    usdm_market_ws_base: str
    usdm_public_ws_base: str
    spot_instrument_example: str
    usdm_instrument_example: str
    routes_match_p03_contract: bool
    credentials_accessed: bool = False

    @model_validator(mode="after")
    def reject_credentials(self) -> NautilusBinanceSemantics:
        if self.credentials_accessed:
            raise ValueError("compatibility inspection must never access credentials")
        return self


def inspect_installed_nautilus() -> NautilusBinanceSemantics:
    """Import enums and pure URL helpers only; factories and live clients are deliberately excluded."""
    import nautilus_trader
    from nautilus_trader.adapters.binance.common.enums import (
        BinanceAccountType,
        BinanceEnvironment,
    )
    from nautilus_trader.adapters.binance.common.urls import (
        get_ws_base_url,
        get_ws_public_base_url,
    )

    spot = get_ws_base_url(BinanceAccountType.SPOT, BinanceEnvironment.LIVE, False)
    usdm_market = get_ws_base_url(BinanceAccountType.USDT_FUTURES, BinanceEnvironment.LIVE, False)
    usdm_public = get_ws_public_base_url(
        BinanceAccountType.USDT_FUTURES, BinanceEnvironment.LIVE, False
    )
    return NautilusBinanceSemantics(
        installed_version=nautilus_trader.__version__,
        spot_market_ws_base=spot,
        usdm_market_ws_base=usdm_market,
        usdm_public_ws_base=usdm_public,
        spot_instrument_example="BTCUSDT.BINANCE",
        usdm_instrument_example="BTCUSDT-PERP.BINANCE",
        routes_match_p03_contract=(
            spot == "wss://stream.binance.com:9443"
            and usdm_market == "wss://fstream.binance.com/market"
            and usdm_public == "wss://fstream.binance.com/public"
        ),
        credentials_accessed=False,
    )
