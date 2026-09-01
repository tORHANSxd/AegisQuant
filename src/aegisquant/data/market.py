"""Venue-neutral market contracts that preserve instrument and unit differences."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import InstrumentId, ProviderId
from aegisquant.domain.time import UtcDateTime, ensure_utc


class Venue(StrEnum):
    BINANCE = "BINANCE"
    OKX = "OKX"
    BYBIT = "BYBIT"
    DERIBIT = "DERIBIT"


class InstrumentType(StrEnum):
    SPOT = "SPOT"
    PERPETUAL = "PERPETUAL"
    FUTURE = "FUTURE"
    OPTION = "OPTION"


class ContractForm(StrEnum):
    SPOT = "SPOT"
    LINEAR = "LINEAR"
    INVERSE = "INVERSE"


class OptionType(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


class ImpliedVolatilitySource(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    VENUE_MARK_TICKER = "VENUE_MARK_TICKER"
    VENUE_BID_ASK_TICKER = "VENUE_BID_ASK_TICKER"


class CanonicalAsset(DomainModel):
    asset_id: str
    symbol: str
    network: str | None = None
    contract_address: str | None = None

    @classmethod
    def create(
        cls, symbol: str, *, network: str | None = None, contract_address: str | None = None
    ) -> Self:
        normalized_symbol = symbol.strip().upper()
        normalized_network = network.strip().upper() if network else None
        normalized_address = contract_address.strip().casefold() if contract_address else None
        if not normalized_symbol:
            raise ValueError("canonical asset symbol cannot be blank")
        identity = {
            "symbol": normalized_symbol,
            "network": normalized_network,
            "contract_address": normalized_address,
        }
        return cls(
            asset_id=f"asset:{canonical_sha256(identity)}",
            symbol=normalized_symbol,
            network=normalized_network,
            contract_address=normalized_address,
        )


class CanonicalPair(DomainModel):
    pair_id: str
    base_asset_id: str
    quote_asset_id: str

    @classmethod
    def create(cls, base: CanonicalAsset, quote: CanonicalAsset) -> Self:
        if base.asset_id == quote.asset_id:
            raise ValueError("canonical pair assets must differ")
        identity = {"base_asset_id": base.asset_id, "quote_asset_id": quote.asset_id}
        return cls(
            pair_id=f"pair:{canonical_sha256(identity)}",
            base_asset_id=base.asset_id,
            quote_asset_id=quote.asset_id,
        )


class CanonicalExposure(DomainModel):
    exposure_id: str
    pair_id: str
    settlement_asset_id: str
    instrument_type: InstrumentType
    contract_form: ContractForm
    expiry: UtcDateTime | None = None
    strike: Decimal | None = Field(default=None, gt=0)
    option_type: OptionType | None = None

    @classmethod
    def create(
        cls,
        pair: CanonicalPair,
        settlement: CanonicalAsset,
        *,
        instrument_type: InstrumentType,
        contract_form: ContractForm,
        expiry: datetime | None = None,
        strike: Decimal | None = None,
        option_type: OptionType | None = None,
    ) -> Self:
        normalized_expiry = ensure_utc(expiry) if expiry is not None else None
        identity = {
            "pair_id": pair.pair_id,
            "settlement_asset_id": settlement.asset_id,
            "instrument_type": instrument_type.value,
            "contract_form": contract_form.value,
            "expiry": normalized_expiry.isoformat() if normalized_expiry else None,
            "strike": str(strike) if strike is not None else None,
            "option_type": option_type.value if option_type else None,
        }
        return cls(
            exposure_id=f"exposure:{canonical_sha256(identity)}",
            pair_id=pair.pair_id,
            settlement_asset_id=settlement.asset_id,
            instrument_type=instrument_type,
            contract_form=contract_form,
            expiry=normalized_expiry,
            strike=strike,
            option_type=option_type,
        )

    @model_validator(mode="after")
    def validate_dimensions(self) -> CanonicalExposure:
        if (
            self.instrument_type is InstrumentType.SPOT
            and self.contract_form is not ContractForm.SPOT
        ):
            raise ValueError("spot exposure requires SPOT contract form")
        if (
            self.instrument_type is not InstrumentType.SPOT
            and self.contract_form is ContractForm.SPOT
        ):
            raise ValueError("derivative exposure cannot use SPOT contract form")
        option_fields = (self.strike, self.option_type)
        if self.instrument_type is InstrumentType.OPTION:
            if self.expiry is None or any(value is None for value in option_fields):
                raise ValueError("option exposure requires expiry, strike, and option_type")
        elif any(value is not None for value in option_fields):
            raise ValueError("strike and option_type exist only on option exposure")
        if self.instrument_type is InstrumentType.FUTURE and self.expiry is None:
            raise ValueError("future exposure requires expiry")
        if self.instrument_type in {InstrumentType.SPOT, InstrumentType.PERPETUAL} and self.expiry:
            raise ValueError("spot and perpetual exposure cannot expire")
        return self


class UnifiedInstrument(DomainModel):
    instrument_id: InstrumentId
    provider_id: ProviderId
    venue: Venue
    venue_symbol: str
    exposure: CanonicalExposure
    base_asset: CanonicalAsset
    quote_asset: CanonicalAsset
    settlement_asset: CanonicalAsset
    contract_multiplier: Decimal = Field(gt=0)
    tick_size: Decimal = Field(gt=0)
    lot_size: Decimal = Field(gt=0)
    active: bool
    observed_time: UtcDateTime
    available_time: UtcDateTime
    iv_source: ImpliedVolatilitySource = ImpliedVolatilitySource.NOT_APPLICABLE

    @classmethod
    def create(
        cls,
        *,
        provider_id: ProviderId,
        venue: Venue,
        venue_symbol: str,
        exposure: CanonicalExposure,
        base_asset: CanonicalAsset,
        quote_asset: CanonicalAsset,
        settlement_asset: CanonicalAsset,
        contract_multiplier: Decimal,
        tick_size: Decimal,
        lot_size: Decimal,
        active: bool,
        observed_time: datetime,
        available_time: datetime,
        iv_source: ImpliedVolatilitySource = ImpliedVolatilitySource.NOT_APPLICABLE,
    ) -> Self:
        identity = {
            "provider_id": str(provider_id),
            "venue": venue.value,
            "venue_symbol": venue_symbol,
            "exposure_id": exposure.exposure_id,
        }
        return cls(
            instrument_id=InstrumentId(canonical_sha256(identity)),
            provider_id=provider_id,
            venue=venue,
            venue_symbol=venue_symbol,
            exposure=exposure,
            base_asset=base_asset,
            quote_asset=quote_asset,
            settlement_asset=settlement_asset,
            contract_multiplier=contract_multiplier,
            tick_size=tick_size,
            lot_size=lot_size,
            active=active,
            observed_time=ensure_utc(observed_time),
            available_time=ensure_utc(available_time),
            iv_source=iv_source,
        )

    @model_validator(mode="after")
    def validate_instrument(self) -> UnifiedInstrument:
        if self.observed_time > self.available_time:
            raise ValueError("instrument cannot be available before observation")
        if self.exposure.pair_id != CanonicalPair.create(self.base_asset, self.quote_asset).pair_id:
            raise ValueError("instrument assets disagree with canonical exposure pair")
        if self.exposure.settlement_asset_id != self.settlement_asset.asset_id:
            raise ValueError("instrument settlement asset disagrees with exposure")
        is_option = self.exposure.instrument_type is InstrumentType.OPTION
        if is_option == (self.iv_source is ImpliedVolatilitySource.NOT_APPLICABLE):
            raise ValueError("option instruments require an explicit IV source")
        return self


class ContractPnl(DomainModel):
    amount: Decimal
    settlement_asset_id: str
    unit: str


def contract_base_quantity(
    *, signed_contracts: Decimal, price: Decimal, multiplier: Decimal, form: ContractForm
) -> Decimal:
    """Convert contracts to signed base exposure under the venue contract convention."""
    if price <= 0 or multiplier <= 0:
        raise ValueError("price and multiplier must be positive")
    if form in {ContractForm.SPOT, ContractForm.LINEAR}:
        return signed_contracts * multiplier
    return signed_contracts * multiplier / price


def contract_pnl(
    *,
    signed_contracts: Decimal,
    entry_price: Decimal,
    exit_price: Decimal,
    instrument: UnifiedInstrument,
) -> ContractPnl:
    """Calculate contract-convention PnL only; accounting and position state belong to P05."""
    if entry_price <= 0 or exit_price <= 0:
        raise ValueError("entry and exit prices must be positive")
    multiplier = instrument.contract_multiplier
    form = instrument.exposure.contract_form
    if form is ContractForm.INVERSE:
        amount = (
            signed_contracts * multiplier * (Decimal(1) / entry_price - Decimal(1) / exit_price)
        )
        unit = "base_asset"
    else:
        amount = signed_contracts * multiplier * (exit_price - entry_price)
        unit = "quote_asset"
    return ContractPnl(
        amount=amount,
        settlement_asset_id=instrument.settlement_asset.asset_id,
        unit=unit,
    )


class MarketObservation(DomainModel):
    provider_id: ProviderId
    venue: Venue
    instrument_id: InstrumentId
    exposure_id: str
    quote_asset_id: str
    event_time: UtcDateTime
    available_time: UtcDateTime
    ingest_time: UtcDateTime
    bid: Decimal = Field(gt=0)
    ask: Decimal = Field(gt=0)
    mark: Decimal | None = Field(default=None, gt=0)
    index: Decimal | None = Field(default=None, gt=0)
    funding_rate: Decimal | None = None
    open_interest: Decimal | None = Field(default=None, ge=0)
    liquidity_notional: Decimal = Field(ge=0)
    quality_score: Decimal = Field(ge=0, le=1)
    event_key: str | None = None

    @model_validator(mode="after")
    def validate_observation(self) -> MarketObservation:
        if self.bid > self.ask:
            raise ValueError("market observation is crossed")
        if not self.event_time <= self.available_time <= self.ingest_time:
            raise ValueError("market observation times must be monotonic")
        return self


class ProviderBatch(DomainModel):
    provider_id: ProviderId
    observations: tuple[MarketObservation, ...] = ()
    error_code: str | None = None

    @model_validator(mode="after")
    def reject_mixed_failure(self) -> ProviderBatch:
        if self.error_code is not None and self.observations:
            raise ValueError("failed provider batch cannot expose partial observations")
        if any(item.provider_id != self.provider_id for item in self.observations):
            raise ValueError("provider batch contains foreign observations")
        return self


class ComparisonRow(DomainModel):
    provider_id: ProviderId
    venue: Venue
    instrument_id: InstrumentId
    exposure_id: str
    event_time: UtcDateTime
    midpoint: Decimal
    spread_bps: Decimal
    funding_rate: Decimal | None
    basis_bps: Decimal | None
    open_interest: Decimal | None
    liquidity_notional: Decimal
    quality_score: Decimal


class ComparisonResult(DomainModel):
    as_of_time: UtcDateTime
    rows: tuple[ComparisonRow, ...]
    rejected_provider_ids: tuple[ProviderId, ...]
    filtered_observation_count: int = Field(ge=0)


def compare_venues(
    batches: tuple[ProviderBatch, ...],
    *,
    as_of_time: datetime,
    exposure_id: str,
    quote_asset_id: str,
    maximum_age: timedelta,
    minimum_quality: Decimal,
) -> ComparisonResult:
    """Build a PIT-safe comparison while isolating failed providers and low-quality rows."""
    as_of = ensure_utc(as_of_time)
    if maximum_age <= timedelta(0):
        raise ValueError("maximum_age must be positive")
    if not Decimal(0) <= minimum_quality <= Decimal(1):
        raise ValueError("minimum_quality must be between zero and one")
    rows: list[ComparisonRow] = []
    rejected: list[ProviderId] = []
    filtered = 0
    for batch in batches:
        if batch.error_code is not None:
            rejected.append(batch.provider_id)
            continue
        for item in batch.observations:
            eligible = (
                item.exposure_id == exposure_id
                and item.quote_asset_id == quote_asset_id
                and item.available_time <= as_of
                and item.event_time <= as_of
                and as_of - item.event_time <= maximum_age
                and item.quality_score >= minimum_quality
            )
            if not eligible:
                filtered += 1
                continue
            midpoint = (item.bid + item.ask) / Decimal(2)
            spread_bps = (item.ask - item.bid) / midpoint * Decimal(10_000)
            basis_bps = None
            if item.mark is not None and item.index is not None:
                basis_bps = (item.mark / item.index - Decimal(1)) * Decimal(10_000)
            rows.append(
                ComparisonRow(
                    provider_id=item.provider_id,
                    venue=item.venue,
                    instrument_id=item.instrument_id,
                    exposure_id=item.exposure_id,
                    event_time=item.event_time,
                    midpoint=midpoint,
                    spread_bps=spread_bps,
                    funding_rate=item.funding_rate,
                    basis_bps=basis_bps,
                    open_interest=item.open_interest,
                    liquidity_notional=item.liquidity_notional,
                    quality_score=item.quality_score,
                )
            )
    rows.sort(key=lambda row: (row.event_time, row.venue.value, str(row.instrument_id)))
    return ComparisonResult(
        as_of_time=as_of,
        rows=tuple(rows),
        rejected_provider_ids=tuple(sorted(rejected, key=str)),
        filtered_observation_count=filtered,
    )


class ClockObservation(DomainModel):
    provider_id: ProviderId
    request_sent_time: UtcDateTime
    server_time: UtcDateTime
    response_received_time: UtcDateTime
    round_trip_ms: Decimal = Field(ge=0)
    offset_ms: Decimal

    @classmethod
    def create(
        cls,
        provider_id: ProviderId,
        *,
        request_sent_time: datetime,
        server_time: datetime,
        response_received_time: datetime,
    ) -> Self:
        sent = ensure_utc(request_sent_time)
        server = ensure_utc(server_time)
        received = ensure_utc(response_received_time)
        if received < sent:
            raise ValueError("clock response cannot precede request")
        round_trip_ms = Decimal(str((received - sent).total_seconds() * 1000))
        midpoint = sent + (received - sent) / 2
        offset_ms = Decimal(str((server - midpoint).total_seconds() * 1000))
        return cls(
            provider_id=provider_id,
            request_sent_time=sent,
            server_time=server,
            response_received_time=received,
            round_trip_ms=round_trip_ms,
            offset_ms=offset_ms,
        )


class LeadLagObservation(DomainModel):
    exposure_id: str
    event_key: str
    leader_provider_id: ProviderId
    follower_provider_id: ProviderId
    leader_event_time: UtcDateTime
    follower_event_time: UtcDateTime
    lag_ms: Decimal = Field(ge=0)


def lead_lag_dataset(observations: tuple[MarketObservation, ...]) -> tuple[LeadLagObservation, ...]:
    """Measure arrival-independent event-time lags for observations sharing an event key."""
    grouped: dict[tuple[str, str], list[MarketObservation]] = {}
    for item in observations:
        if item.event_key is not None:
            grouped.setdefault((item.exposure_id, item.event_key), []).append(item)
    rows: list[LeadLagObservation] = []
    for (exposure_id, event_key), group in grouped.items():
        ordered = sorted(group, key=lambda item: (item.event_time, str(item.provider_id)))
        if len(ordered) < 2:
            continue
        leader = ordered[0]
        for follower in ordered[1:]:
            rows.append(
                LeadLagObservation(
                    exposure_id=exposure_id,
                    event_key=event_key,
                    leader_provider_id=leader.provider_id,
                    follower_provider_id=follower.provider_id,
                    leader_event_time=leader.event_time,
                    follower_event_time=follower.event_time,
                    lag_ms=Decimal(
                        str((follower.event_time - leader.event_time).total_seconds() * 1000)
                    ),
                )
            )
    return tuple(rows)
