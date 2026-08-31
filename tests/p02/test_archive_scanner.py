"""Encrypted revision archive and read-only asset scanner tests."""

import hashlib
import json
from pathlib import Path

import pytest

from aegisquant.data.archive import RestrictedContentCipher, RevisionArchive
from aegisquant.data.query import DuckDbQueryLayer
from aegisquant.data.scanner import ReadOnlyAssetScanner
from aegisquant.domain.errors import DomainError
from aegisquant.domain.identifiers import ProviderNativeId, SourceDocumentId, SourcePolicyId
from tests.p02.helpers import NOW, load_registries


def test_encrypted_revisions_are_immutable_and_tombstones_block_rehydration(
    tmp_path: Path, project_root: Path
) -> None:
    providers, policies = load_registries(project_root)
    policy = policies.get(SourcePolicyId("synthetic_fixture_v1"))
    archive = RevisionArchive(tmp_path / "archive", providers)
    cipher = RestrictedContentCipher(key_id="test-key-v1", key=b"k" * 32)
    plaintext = b"synthetic restricted content"
    document_id = SourceDocumentId("synthetic-document-1")
    native_id = ProviderNativeId("native-1")

    first = archive.archive_revision(
        policy=policy,
        source_document_id=document_id,
        provider_native_id=native_id,
        revision=1,
        content=plaintext,
        available_time=NOW,
        ingest_time=NOW,
        cipher=cipher,
    )
    repeated = archive.archive_revision(
        policy=policy,
        source_document_id=document_id,
        provider_native_id=native_id,
        revision=1,
        content=plaintext,
        available_time=NOW,
        ingest_time=NOW,
        cipher=cipher,
    )
    assert repeated == first
    assert archive.rehydrate(record=first, cipher=cipher) == plaintext
    assert all(plaintext not in path.read_bytes() for path in tmp_path.rglob("*.*"))

    tombstone = archive.append_tombstone(
        policy=policy,
        source_document_id=document_id,
        deleted_at=NOW,
        reason_code="source_deleted",
        supersedes_record_id=first.record_id,
    )
    assert "SYNC_DELETION_AND_APPEND_TOMBSTONE" in tombstone.required_actions
    with pytest.raises(DomainError, match="AQ-DATA-CONTENT-DELETED"):
        archive.rehydrate(record=first, cipher=cipher)


def test_metadata_only_archive_retains_hash_not_payload(tmp_path: Path, project_root: Path) -> None:
    providers, policies = load_registries(project_root)
    policy = policies.get(SourcePolicyId("apache_parquet_testing_v1"))
    archive = RevisionArchive(tmp_path / "archive", providers)
    content = b"public compatibility sample bytes"
    record = archive.archive_revision(
        policy=policy,
        source_document_id=SourceDocumentId("apache-sample-1"),
        provider_native_id=ProviderNativeId("alltypes-plain"),
        revision=1,
        content=content,
        available_time=NOW,
        ingest_time=NOW,
    )
    assert record.content_sha256 == hashlib.sha256(content).hexdigest()
    assert record.payload_path is None
    assert (
        archive.rehydrate(
            record=record,
            cipher=RestrictedContentCipher(key_id="unused", key=b"u" * 32),
        )
        is None
    )
    assert all(content not in path.read_bytes() for path in tmp_path.rglob("*.*"))


def test_scanner_is_read_only_streaming_and_proposal_only(tmp_path: Path) -> None:
    source = tmp_path / "authorized-synthetic-source"
    output_root = tmp_path / "evidence"
    source.mkdir()
    (source / "events.csv").write_text("event_id,value\nevent-1,10\nevent-2,20\n", encoding="utf-8")
    (source / "strategy.py").write_text(
        "raise RuntimeError('this asset must never execute')\n", encoding="utf-8"
    )
    (source / "notes.jsonl").write_text('{"event_id":"event-3","value":30}\n', encoding="utf-8")
    before = {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns, path.read_bytes())
        for path in source.iterdir()
    }

    inventory = output_root / "LOCAL_ASSET_INVENTORY.parquet"
    proposals = output_root / "IMPORT_PROPOSALS.jsonl"
    count, proposal_count = ReadOnlyAssetScanner(hash_buffer_bytes=4096).scan_to_parquet(
        root=source,
        root_label="synthetic_fixture_only",
        output=inventory,
        proposals_output=proposals,
        batch_size=1,
    )

    assert (count, proposal_count) == (3, 3)
    inventory_table = DuckDbQueryLayer(allowed_root=output_root).read((inventory,))
    assert inventory_table.num_rows == 3
    assert set(inventory_table.column_names) >= {
        "dataset_id",
        "relative_path",
        "sha256",
        "schema_json",
    }
    proposal_rows = [
        json.loads(line) for line in proposals.read_text(encoding="utf-8").splitlines()
    ]
    code_proposal = next(row for row in proposal_rows if row["relative_path"] == "strategy.py")
    assert code_proposal["action"] == "REVIEW"
    assert code_proposal["requires_static_analysis"] is True
    assert code_proposal["requires_user_approval"] is True
    after = {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns, path.read_bytes())
        for path in source.iterdir()
    }
    assert before == after


def test_scanner_refuses_to_write_inside_source_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.csv").write_text("x\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="AQ-DATA-SCAN-READ-ONLY"):
        ReadOnlyAssetScanner().scan_to_parquet(
            root=source,
            root_label="synthetic",
            output=source / "inventory.parquet",
        )
