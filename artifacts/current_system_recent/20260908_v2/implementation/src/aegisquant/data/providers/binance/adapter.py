"""Policy-gated facade for the Binance public market-data implementation."""

from __future__ import annotations

from collections.abc import Iterable

from aegisquant.data.archive import RevisionArchive, RevisionRecord
from aegisquant.data.provider_registry import ProviderRegistry
from aegisquant.data.providers.binance.contracts import (
    Product,
    RestEndpoint,
    StreamKind,
    build_ws_url,
)
from aegisquant.data.providers.binance.models import ConnectionHealth, RawResponseEnvelope
from aegisquant.data.providers.binance.rest import BinancePublicRestClient
from aegisquant.data.providers.binance.websocket import PublicStreamRunner
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import ProviderId, ProviderNativeId, SourceDocumentId
from aegisquant.domain.policy import SourceProcessingPolicy


class DatasetDescriptor(DomainModel):
    dataset_name: str
    product: Product
    transports: tuple[str, ...]
    time_semantics: str
    schema_version: str = "1.0.0"


class ProviderQuota(DomainModel):
    observed_used_weight: dict[str, int]
    ws_connection_attempt_limit_per_five_minutes: int = 300
    credential_quota_used: bool = False


class ProviderHealth(DomainModel):
    provider_id: ProviderId
    status: str
    streams: tuple[ConnectionHealth, ...]
    live_trading_locked: bool = True
    order_submission_enabled: bool = False
    private_api_enabled: bool = False


class BinancePublicAdapter:
    provider_id = ProviderId("binance_public")

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        policy: SourceProcessingPolicy,
        rest: BinancePublicRestClient,
        archive: RevisionArchive,
    ) -> None:
        registry.require_collection(self.provider_id, policy)
        registry.require_archive(self.provider_id, policy)
        if policy.provider_id != self.provider_id:
            raise ValueError("Binance adapter policy/provider mismatch")
        self._registry = registry
        self._policy = policy
        self._rest = rest
        self._archive = archive

    def discover_catalog(self) -> tuple[DatasetDescriptor, ...]:
        common = (
            "instruments",
            "klines",
            "trades",
            "book_ticker",
            "depth",
        )
        rows = [
            DatasetDescriptor(
                dataset_name=f"spot_{name}",
                product=Product.SPOT,
                transports=("REST", "WEBSOCKET") if name != "instruments" else ("REST",),
                time_semantics="exchange_event+local_available+local_ingest+processed+revision",
            )
            for name in common
        ]
        rows.extend(
            DatasetDescriptor(
                dataset_name=f"usdm_{name}",
                product=Product.USD_M,
                transports=("REST", "WEBSOCKET") if name != "instruments" else ("REST",),
                time_semantics="exchange_event+local_available+local_ingest+processed+revision",
            )
            for name in (*common, "mark_index", "funding", "open_interest")
        )
        return tuple(rows)

    def fetch(
        self, endpoint: RestEndpoint, parameters: dict[str, str | int] | None = None
    ) -> RawResponseEnvelope:
        self._registry.require_collection(self.provider_id, self._policy)
        return self._rest.get(endpoint, parameters)

    def archive_response(self, response: RawResponseEnvelope) -> RevisionRecord:
        self._registry.require_archive(self.provider_id, self._policy)
        return self._archive.archive_revision(
            policy=self._policy,
            source_document_id=SourceDocumentId(
                f"binance:{response.endpoint}:{response.request_hash}"
            ),
            provider_native_id=ProviderNativeId(f"{response.endpoint}:{response.request_hash}"),
            revision=1,
            content=response.content,
            available_time=response.received_at,
            ingest_time=response.received_at,
        )

    def stream_runner(
        self,
        *,
        product: Product,
        kind: StreamKind,
        symbol: str,
        interval: str | None = None,
        maximum_connection_age_seconds: float = 85_800.0,
    ) -> PublicStreamRunner:
        self._registry.require_collection(self.provider_id, self._policy)
        return PublicStreamRunner(
            url=build_ws_url(
                product=product,
                kind=kind,
                symbol=symbol,
                interval=interval,
            ),
            maximum_connection_age_seconds=maximum_connection_age_seconds,
        )

    @staticmethod
    def quota(response: RawResponseEnvelope) -> ProviderQuota:
        used: dict[str, int] = {}
        for key, raw_value in response.rate_limit_headers.items():
            if key.startswith("x-mbx-used-weight"):
                try:
                    used[key] = int(raw_value)
                except ValueError:
                    continue
        return ProviderQuota(observed_used_weight=used, credential_quota_used=False)

    def health(self, runners: Iterable[PublicStreamRunner] = ()) -> ProviderHealth:
        streams = tuple(runner.health() for runner in runners)
        status = (
            "HEALTHY" if all(stream.status not in {"FAILED"} for stream in streams) else "DEGRADED"
        )
        return ProviderHealth(
            provider_id=self.provider_id,
            status=status,
            streams=streams,
            live_trading_locked=True,
            order_submission_enabled=False,
            private_api_enabled=False,
        )
