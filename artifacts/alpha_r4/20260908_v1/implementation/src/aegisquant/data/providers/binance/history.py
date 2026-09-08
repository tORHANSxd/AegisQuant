"""Checkpointed Binance REST history pages and verified public archive downloads."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import httpx

from aegisquant.data.archive import RevisionArchive
from aegisquant.data.checkpoint import CheckpointStore, IngestCheckpoint
from aegisquant.data.hashing import canonical_sha256
from aegisquant.data.providers.binance.contracts import (
    RestEndpoint,
    assert_public_archive_url,
    build_rest_request,
)
from aegisquant.data.providers.binance.models import RawResponseEnvelope
from aegisquant.data.providers.binance.rest import BinancePublicRestClient, decode_json
from aegisquant.domain.identifiers import ProviderNativeId, SourceDocumentId
from aegisquant.domain.policy import SourceProcessingPolicy

_KLINE_ENDPOINTS = frozenset(
    {RestEndpoint.SPOT_KLINES, RestEndpoint.USDM_KLINES, RestEndpoint.USDM_MARK_KLINES}
)


class BinanceHistoryDownloader:
    """Endpoint-aware public paginator whose every completed page is archived and checkpointed."""

    def __init__(
        self,
        *,
        rest: BinancePublicRestClient,
        checkpoint_store: CheckpointStore,
        revision_archive: RevisionArchive,
        policy: SourceProcessingPolicy,
    ) -> None:
        self._rest = rest
        self._checkpoints = checkpoint_store
        self._archive = revision_archive
        self._policy = policy

    def fetch_pages(
        self,
        *,
        endpoint: RestEndpoint,
        dataset_name: str,
        parameters: dict[str, str | int],
        maximum_pages: int = 10_000,
    ) -> tuple[RawResponseEnvelope, ...]:
        if maximum_pages < 1:
            raise ValueError("maximum_pages must be positive")
        _, _, initial_hash = build_rest_request(endpoint, parameters)
        checkpoint = self._checkpoints.load(self._policy.provider_id, dataset_name)
        request_parameters = dict(parameters)
        if checkpoint is not None:
            if checkpoint.source_request_hash != initial_hash:
                raise ValueError("AQ-DATA-CHECKPOINT-REQUEST-MISMATCH")
            if checkpoint.cursor is not None:
                self._apply_cursor(endpoint, request_parameters, int(checkpoint.cursor))
        pages: list[RawResponseEnvelope] = []
        for _page_index in range(maximum_pages):
            response = self._rest.get(endpoint, request_parameters)
            payload = decode_json(response)
            self._archive_response(endpoint, response)
            pages.append(response)
            cursor = self._next_cursor(endpoint, payload)
            self._checkpoints.save(
                IngestCheckpoint(
                    provider_id=self._policy.provider_id,
                    dataset_name=dataset_name,
                    cursor=str(cursor) if cursor is not None else None,
                    byte_offset=0,
                    source_request_hash=initial_hash,
                    last_completed_content_hash=response.content_sha256,
                    updated_at=response.received_at,
                )
            )
            if cursor is None or self._past_end(request_parameters, cursor):
                return tuple(pages)
            self._apply_cursor(endpoint, request_parameters, cursor)
        raise RuntimeError("AQ-DATA-BINANCE-HISTORY-MAXIMUM-PAGES")

    def _archive_response(self, endpoint: RestEndpoint, response: RawResponseEnvelope) -> None:
        self._archive.archive_revision(
            policy=self._policy,
            source_document_id=SourceDocumentId(
                f"binance:{endpoint.value}:{response.request_hash}"
            ),
            provider_native_id=ProviderNativeId(f"{endpoint.value}:{response.request_hash}"),
            revision=1,
            content=response.content,
            available_time=response.received_at,
            ingest_time=response.received_at,
        )

    @staticmethod
    def _next_cursor(endpoint: RestEndpoint, payload: object) -> int | None:
        if not isinstance(payload, list) or not payload:
            return None
        rows = cast(list[object], payload)
        last = rows[-1]
        if endpoint in _KLINE_ENDPOINTS:
            if not isinstance(last, list):
                raise ValueError("Kline page has no integer close time")
            kline = cast(list[object], last)
            if len(kline) < 7 or not isinstance(kline[6], int):
                raise ValueError("Kline page has no integer close time")
            return kline[6] + 1
        if endpoint in {RestEndpoint.SPOT_AGG_TRADES, RestEndpoint.USDM_AGG_TRADES}:
            row = BinanceHistoryDownloader._row(last)
            trade_id = row.get("a")
            if not isinstance(trade_id, int) or isinstance(trade_id, bool):
                raise ValueError("aggregate trade page has no integer aggregate ID")
            return trade_id + 1
        if endpoint is RestEndpoint.USDM_FUNDING:
            row = BinanceHistoryDownloader._row(last)
            funding_time = row.get("fundingTime")
            if not isinstance(funding_time, int) or isinstance(funding_time, bool):
                raise ValueError("funding page has no integer funding time")
            return funding_time + 1
        if endpoint is RestEndpoint.USDM_OPEN_INTEREST_HISTORY:
            row = BinanceHistoryDownloader._row(last)
            timestamp = row.get("timestamp")
            if not isinstance(timestamp, int) or isinstance(timestamp, bool):
                raise ValueError("open-interest page has no integer timestamp")
            return timestamp + 1
        return None

    @staticmethod
    def _row(value: object) -> Mapping[str, object]:
        if not isinstance(value, dict):
            raise ValueError("history row must be a string-keyed object")
        raw = cast(dict[object, object], value)
        if not all(isinstance(key, str) for key in raw):
            raise ValueError("history row must be a string-keyed object")
        return {cast(str, key): item for key, item in raw.items()}

    @staticmethod
    def _apply_cursor(
        endpoint: RestEndpoint, parameters: dict[str, str | int], cursor: int
    ) -> None:
        if endpoint in _KLINE_ENDPOINTS | {
            RestEndpoint.USDM_FUNDING,
            RestEndpoint.USDM_OPEN_INTEREST_HISTORY,
        }:
            parameters["startTime"] = cursor
        elif endpoint in {RestEndpoint.SPOT_AGG_TRADES, RestEndpoint.USDM_AGG_TRADES}:
            parameters["fromId"] = cursor

    @staticmethod
    def _past_end(parameters: Mapping[str, str | int], cursor: int) -> bool:
        end = parameters.get("endTime")
        return isinstance(end, int) and not isinstance(end, bool) and cursor > end


def parse_checksum(checksum_text: str, *, expected_filename: str) -> str:
    fields = checksum_text.strip().split()
    if len(fields) != 2 or fields[1].lstrip("*") != expected_filename:
        raise ValueError("AQ-DATA-BINANCE-CHECKSUM-FORMAT")
    digest = fields[0].casefold()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("AQ-DATA-BINANCE-CHECKSUM-FORMAT")
    return digest


def download_public_archive(
    *,
    url: str,
    checksum_text: str,
    output: Path,
    transport: httpx.BaseTransport | None = None,
    timeout_seconds: float = 60.0,
) -> tuple[str, int]:
    """Stream one official ZIP to an atomic local file after SHA-256 verification."""
    assert_public_archive_url(url)
    if output.name != Path(urlsplit(url).path).name:
        raise ValueError("output filename must match the official archive filename")
    expected = parse_checksum(checksum_text, expected_filename=output.name)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.partial")
    if temporary.exists():
        temporary.unlink()
    digest = hashlib.sha256()
    size = 0
    try:
        with (
            httpx.Client(
                transport=transport,
                timeout=httpx.Timeout(timeout_seconds),
                follow_redirects=False,
                trust_env=False,
            ) as client,
            client.stream("GET", url) as response,
        ):
            if 300 <= response.status_code < 400:
                raise ValueError("AQ-PROVIDER-BINANCE-REDIRECT-DENIED")
            response.raise_for_status()
            with temporary.open("xb") as destination:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    digest.update(chunk)
                    destination.write(chunk)
                    size += len(chunk)
                destination.flush()
                os.fsync(destination.fileno())
        actual = digest.hexdigest()
        if actual != expected:
            raise ValueError("AQ-DATA-BINANCE-CHECKSUM-MISMATCH")
        os.replace(temporary, output)
        return actual, size
    finally:
        if temporary.exists():
            temporary.unlink()


def history_request_hash(endpoint: RestEndpoint, parameters: Mapping[str, str | int]) -> str:
    """Expose the stable base-request identity used to bind checkpoints."""
    return canonical_sha256(
        {"endpoint": endpoint.value, "parameters": dict(parameters), "authentication": False}
    )
