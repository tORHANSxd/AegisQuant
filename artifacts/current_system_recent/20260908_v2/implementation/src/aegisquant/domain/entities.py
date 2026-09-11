"""Core reference entities and point-in-time instrument rules."""

from __future__ import annotations

from enum import StrEnum

from pydantic import model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import (
    AccountId,
    ArtifactId,
    AssetId,
    EnvironmentId,
    InstrumentId,
    VenueId,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import Money, Price, Quantity


class AssetClass(StrEnum):
    CRYPTO = "CRYPTO"


class InstrumentType(StrEnum):
    SPOT = "SPOT"
    PERPETUAL = "PERPETUAL"
    FUTURE = "FUTURE"
    OPTION = "OPTION"


class ContractDirection(StrEnum):
    LINEAR = "LINEAR"
    INVERSE = "INVERSE"
    NOT_APPLICABLE = "NA"


class InstrumentStatus(StrEnum):
    TRADING = "TRADING"
    HALTED = "HALTED"
    DELISTED = "DELISTED"
    EXPIRED = "EXPIRED"


class OptionType(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


class DeploymentStage(StrEnum):
    RESEARCH = "RESEARCH"
    PAPER = "PAPER"
    TESTNET = "TESTNET"
    CANARY = "CANARY"
    LIVE = "LIVE"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    READ_ONLY = "READ_ONLY"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class Asset(DomainModel):
    asset_id: AssetId
    symbol: str
    display_name: str
    decimals: int


class Venue(DomainModel):
    venue_id: VenueId
    display_name: str
    timezone: str = "UTC"


class Environment(DomainModel):
    environment_id: EnvironmentId
    stage: DeploymentStage
    live_trading_locked: bool = True

    @model_validator(mode="after")
    def enforce_live_lock(self) -> Environment:
        if self.stage is DeploymentStage.LIVE or not self.live_trading_locked:
            raise ValueError("AQ-SECURITY-LIVE-LOCKED: Live environment is disabled")
        return self


class Account(DomainModel):
    account_id: AccountId
    venue_id: VenueId
    environment_id: EnvironmentId
    reporting_asset_id: AssetId
    status: AccountStatus
    opened_at: UtcDateTime


class Instrument(DomainModel):
    instrument_id: InstrumentId
    venue_id: VenueId
    venue_symbol: str
    asset_class: AssetClass
    instrument_type: InstrumentType
    base_asset_id: AssetId
    quote_asset_id: AssetId
    settlement_asset_id: AssetId
    contract_size: Quantity
    linear_inverse: ContractDirection
    price_tick: Price
    quantity_step: Quantity
    min_quantity: Quantity
    min_notional: Money
    max_quantity: Quantity | None = None
    expiry_time: UtcDateTime | None = None
    strike: Price | None = None
    option_type: OptionType | None = None
    status: InstrumentStatus
    valid_from: UtcDateTime
    valid_to: UtcDateTime | None = None
    source_snapshot_id: ArtifactId

    @model_validator(mode="after")
    def validate_contract(self) -> Instrument:
        if self.base_asset_id == self.quote_asset_id:
            raise ValueError("instrument base and quote assets must differ")
        quantities = (self.contract_size, self.quantity_step, self.min_quantity)
        if any(value.asset_id != self.base_asset_id for value in quantities):
            raise ValueError("instrument quantity units must use the base asset")
        if self.max_quantity is not None and self.max_quantity.asset_id != self.base_asset_id:
            raise ValueError("max quantity must use the base asset")
        if self.min_notional.asset_id != self.quote_asset_id:
            raise ValueError("minimum notional must use the quote asset")
        if self.price_tick.base_asset_id != self.base_asset_id:
            raise ValueError("price tick base asset mismatch")
        if self.price_tick.quote_asset_id != self.quote_asset_id:
            raise ValueError("price tick quote asset mismatch")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("instrument validity interval must be increasing")
        is_option = self.instrument_type is InstrumentType.OPTION
        if is_option != (self.strike is not None and self.option_type is not None):
            raise ValueError("option strike and type must appear only on options")
        return self
