"""Pagination, checkpoints, public raw archive, and official ZIP checksum tests."""

import hashlib
from pathlib import Path

import httpx

from aegisquant.data.archive import RevisionArchive
from aegisquant.data.checkpoint import CheckpointStore
from aegisquant.data.providers.binance.contracts import RestEndpoint
from aegisquant.data.providers.binance.history import (
    BinanceHistoryDownloader,
    download_public_archive,
)
from aegisquant.data.providers.binance.rest import BinancePublicRestClient
from aegisquant.domain.identifiers import ProviderNativeId, SourceDocumentId
from tests.p03.helpers import OBSERVED, registries


def test_history_pages_are_archived_and_checkpointed(tmp_path: Path, project_root: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.params.get("fromId") == "2":
            return httpx.Response(200, json=[], request=request)
        return httpx.Response(
            200,
            json=[
                {
                    "a": 1,
                    "p": "100.0",
                    "q": "1.0",
                    "f": 1,
                    "l": 1,
                    "T": 1700000000000,
                    "m": False,
                }
            ],
            request=request,
        )

    providers, _, policy = registries(project_root)
    checkpoints = CheckpointStore(tmp_path / "checkpoints")
    archive = RevisionArchive(tmp_path / "archive", providers)
    with BinancePublicRestClient(
        transport=httpx.MockTransport(handler), clock=lambda: OBSERVED
    ) as rest:
        downloader = BinanceHistoryDownloader(
            rest=rest,
            checkpoint_store=checkpoints,
            revision_archive=archive,
            policy=policy,
        )
        pages = downloader.fetch_pages(
            endpoint=RestEndpoint.SPOT_AGG_TRADES,
            dataset_name="spot_agg_trades_btcusdt",
            parameters={"symbol": "BTCUSDT", "limit": 1},
        )
    assert len(pages) == 2
    assert "fromId=2" in calls[1]
    checkpoint = checkpoints.load(policy.provider_id, "spot_agg_trades_btcusdt")
    assert checkpoint is not None
    assert checkpoint.cursor is None
    assert checkpoint.last_completed_content_hash == pages[-1].content_sha256
    raw_files = tuple((tmp_path / "archive").rglob("content.raw"))
    assert len(raw_files) == 2
    assert {path.read_bytes() for path in raw_files} == {page.content for page in pages}


def test_public_append_only_revision_rehydrates_without_a_secret(
    tmp_path: Path, project_root: Path
) -> None:
    providers, _, policy = registries(project_root)
    archive = RevisionArchive(tmp_path / "archive", providers)
    content = b'{"public":true}'
    record = archive.archive_revision(
        policy=policy,
        source_document_id=SourceDocumentId("binance:public-test"),
        provider_native_id=ProviderNativeId("public-test"),
        revision=1,
        content=content,
        available_time=OBSERVED,
        ingest_time=OBSERVED,
    )
    assert record.payload_path == "content.raw"
    assert archive.rehydrate(record=record) == content
    assert record.content_sha256 == hashlib.sha256(content).hexdigest()


def test_public_archive_download_requires_matching_official_checksum(tmp_path: Path) -> None:
    content = b"PK\x03\x04synthetic-public-zip-fixture"
    digest = hashlib.sha256(content).hexdigest()
    filename = "BTCUSDT-1m-2026-08-30.zip"
    url = f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1m/{filename}"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=content, request=request)
    )
    output = tmp_path / filename
    actual, size = download_public_archive(
        url=url,
        checksum_text=f"{digest}  {filename}\n",
        output=output,
        transport=transport,
    )
    assert actual == digest
    assert size == len(content)
    assert output.read_bytes() == content


def test_public_archive_checksum_mismatch_never_publishes_file(tmp_path: Path) -> None:
    filename = "BTCUSDT-1m-2026-08-30.zip"
    url = f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1m/{filename}"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"wrong", request=request)
    )
    output = tmp_path / filename
    try:
        download_public_archive(
            url=url,
            checksum_text=f"{'0' * 64}  {filename}\n",
            output=output,
            transport=transport,
        )
    except ValueError as error:
        assert "CHECKSUM-MISMATCH" in str(error)
    else:
        raise AssertionError("checksum mismatch was accepted")
    assert not output.exists()
