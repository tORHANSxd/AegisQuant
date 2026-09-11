"""Read-only inspection of the installed Nautilus Binance execution contract."""

from __future__ import annotations

import importlib
import importlib.metadata
import inspect
from typing import Any

from pydantic import Field

from aegisquant.domain.base import DomainModel


class NautilusBinanceContract(DomainModel):
    package_version: str
    config_class: str
    factory_class: str
    config_fields: tuple[str, ...] = Field(min_length=1)
    execution_methods: tuple[str, ...] = Field(min_length=1)
    supported_environments: tuple[str, ...] = Field(min_length=1)
    instantiated: bool
    network_requests_performed: int = Field(ge=0)


def inspect_nautilus_binance_contract() -> NautilusBinanceContract:
    """Inspect symbols only; do not instantiate a client or access credentials."""
    config_module = importlib.import_module("nautilus_trader.adapters.binance.config")
    factory_module = importlib.import_module("nautilus_trader.adapters.binance.factories")
    common_module = importlib.import_module("nautilus_trader.adapters.binance.common.enums")
    config_class: Any = config_module.BinanceExecClientConfig
    factory_class: Any = factory_module.BinanceLiveExecClientFactory
    environment_class: Any = common_module.BinanceEnvironment
    fields = tuple(getattr(config_class, "__struct_fields__", ()))
    factory_methods = tuple(
        name
        for name, value in inspect.getmembers(factory_class)
        if callable(value) and not name.startswith("_")
    )
    client_module = importlib.import_module("nautilus_trader.adapters.binance.execution")
    client_class: Any = client_module.BinanceCommonExecutionClient
    client_methods = tuple(
        name
        for name, value in inspect.getmembers(client_class)
        if callable(value)
        and name
        in {
            "submit_order",
            "modify_order",
            "cancel_order",
            "generate_order_status_report",
            "generate_fill_reports",
            "connect",
            "disconnect",
        }
    )
    methods = tuple(sorted(set(factory_methods) | set(client_methods)))
    environments = tuple(item.name for item in environment_class)
    return NautilusBinanceContract(
        package_version=importlib.metadata.version("nautilus-trader"),
        config_class=config_class.__name__,
        factory_class=factory_class.__name__,
        config_fields=fields,
        execution_methods=methods,
        supported_environments=environments,
        instantiated=False,
        network_requests_performed=0,
    )
