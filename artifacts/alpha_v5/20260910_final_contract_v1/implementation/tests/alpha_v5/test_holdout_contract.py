from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import IO, Any, cast

import pytest
import yaml

from aegisquant.data.hashing import canonical_sha256
from aegisquant.research.experiments.journal import (
    ExperimentEvent,
    ExperimentEventJournal,
    ExperimentEventType,
)
from aegisquant.research.validation.experiment_registry import checked_development_path
from aegisquant.research.validation.holdout import (
    FreezeAdmissionExtension,
    ResearchFreezeManifest,
    create_freeze_manifest,
)
from aegisquant.research.validation.holdout_contract import (
    ACCESS_JOURNAL_PATH,
    ACCESS_LOCK_PATH,
    ANCHOR_PATH,
    CLAIM_PATH,
    FINAL_GATE_NAMES,
    HoldoutAccessAuthorization,
    HoldoutDataSeal,
    HoldoutProjectAnchor,
    build_documents,
    independent_review_handoff,
    validate_config,
)
from aegisquant.research.validation.persistent_holdout import (
    holdout_read_firewall,
    open_persistent_holdout,
)

NOW = datetime(2026, 2, 1, tzinfo=UTC)
START = datetime(2025, 1, 1, tzinfo=UTC)
END = datetime(2026, 1, 1, tzinfo=UTC)
HASH = "a" * 64


def prepare_synthetic_holdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], HoldoutProjectAnchor, Path]:
    """No market data: metadata truth flags only simulate a future reviewed registration."""
    monkeypatch.setattr("aegisquant.research.validation.persistent_holdout.PROJECT_ROOT", tmp_path)
    payload = b"SYNTHETIC ONLY: neither market observations nor unused data evidence.\n"
    data = tmp_path / "data/final_holdout/sealed.bin"
    data.parent.mkdir(parents=True)
    data.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    extension = FreezeAdmissionExtension(
        data_lineage_sha256=HASH,
        risk_policy_sha256=HASH,
        execution_rules_sha256=HASH,
        capacity_policy_sha256=HASH,
        statistical_protocol_sha256=HASH,
        comparison_family_sha256=HASH,
        complete_trial_registry_sha256=HASH,
        model_weights_manifest_sha256=HASH,
        training_update_program_sha256=HASH,
        training_update_policy="NO_TEST_PERIOD_UPDATES",
        independent_preaccess_review_sha256=HASH,
    )
    frozen = create_freeze_manifest(
        dataset_sha256=digest,
        feature_set_sha256=HASH,
        label_set_sha256=HASH,
        universe_sha256=HASH,
        split_sha256=HASH,
        cost_policy_sha256=HASH,
        model_spec_sha256=HASH,
        parameters_sha256=HASH,
        code_sha256=HASH,
        frozen_at=NOW - timedelta(days=2),
        admission_extension=extension,
    )
    journal_path = tmp_path / ACCESS_JOURNAL_PATH
    genesis = ExperimentEventJournal(journal_path).append(
        ExperimentEvent(
            event_id="synthetic-project:GENESIS",
            run_id="synthetic-project:GENESIS",
            event_type=ExperimentEventType.STARTED,
            recorded_at_utc=NOW - timedelta(days=1),
            details={
                "kind": "PROJECT_HOLDOUT_ANCHOR_GENESIS",
                "claim_consumed": False,
                "evidence_kind": "SYNTHETIC_METADATA_ONLY",
            },
        )
    )
    anchor = HoldoutProjectAnchor(
        project_id="synthetic-project",
        dataset=HoldoutDataSeal(
            semantic_dataset_id="synthetic:one-dataset",
            dataset_sha256=digest,
            content_bytes=len(payload),
            sealed_relative_path=data.relative_to(tmp_path).as_posix(),
            registered_aliases=("data/cache-preview.bin", "data/features.bin"),
            start=START,
            end_exclusive=END,
            source_material_start=START,
            source_material_end_exclusive=END,
            previously_used_through=datetime(2024, 12, 1, tzinfo=UTC),
            source_was_previously_accessed=False,
            unused_and_coverage_evidence_sha256=HASH,
            independent_metadata_verification="VERIFIED",
            lineage_source_hashes=(digest,),
            verification_note="SYNTHETIC_NOT_REAL_INDEPENDENT_VERIFICATION",
        ),
        freeze_id=frozen.freeze_id,
        operator_authorization_sha256=HASH,
        journal_genesis_entry_sha256=genesis.entry_hash,
        independent_storage_attestation_sha256=HASH,
        created_at=NOW - timedelta(days=1),
    )
    (tmp_path / ANCHOR_PATH).write_text(anchor.model_dump_json(), encoding="utf-8")
    authority = HoldoutAccessAuthorization(
        project_id=anchor.project_id,
        anchor_sha256=anchor.anchor_sha256,
        freeze_id=frozen.freeze_id,
        operator_authorization_sha256=HASH,
        generation="synthetic-generation-1",
        authorized_at=NOW,
    )

    def decode(raw: bytes) -> str:
        return raw.decode()

    kwargs: dict[str, Any] = {
        "directory": tmp_path / "candidate-1",
        "manifest": frozen,
        "expected_dataset_sha256": digest,
        "holdout_start": START,
        "holdout_end": END,
        "previously_used_through": anchor.dataset.previously_used_through,
        "loader": decode,
        "accessed_at": NOW,
        "authorization": authority,
    }
    return kwargs, anchor, data


def replace_anchor(
    root: Path, kwargs: dict[str, Any], anchor: HoldoutProjectAnchor, **changes: Any
) -> tuple[dict[str, Any], HoldoutProjectAnchor]:
    updated = HoldoutProjectAnchor.model_validate({**dict(anchor), **changes})
    (root / ANCHOR_PATH).write_text(updated.model_dump_json(), encoding="utf-8")
    authority = HoldoutAccessAuthorization.model_validate(
        {
            **dict(kwargs["authorization"]),
            "anchor_sha256": updated.anchor_sha256,
            "freeze_id": updated.freeze_id,
        }
    )
    return {**kwargs, "authorization": authority}, updated


@pytest.mark.parametrize(
    "problem",
    [
        "unfrozen",
        "wrong_hash",
        "short",
        "used",
        "unknown_source",
        "seen_source",
        "source_tail",
        "narrow_source",
        "wrong_anchor",
        "missing_extension",
        "future_authority",
    ],
)
def test_preaccess_rejections_do_not_open_data_or_consume_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    kwargs, anchor, data = prepare_synthetic_holdout(tmp_path, monkeypatch)
    if problem == "unfrozen":
        kwargs["manifest"] = None
    elif problem == "wrong_hash":
        kwargs["expected_dataset_sha256"] = "b" * 64
    elif problem == "short":
        kwargs["holdout_end"] = datetime(2025, 12, 1, tzinfo=UTC)
    elif problem == "used":
        kwargs["previously_used_through"] = START
    elif problem in {"unknown_source", "seen_source", "source_tail", "narrow_source"}:
        update: dict[str, Any] = {
            "source_was_previously_accessed": None if problem == "unknown_source" else True
        }
        if problem == "source_tail":
            update = {"source_material_end_exclusive": END + timedelta(days=1)}
        elif problem == "narrow_source":
            update = {"source_material_start": START + timedelta(days=1)}
        seal = HoldoutDataSeal.model_validate({**dict(anchor.dataset), **update})
        kwargs, anchor = replace_anchor(tmp_path, kwargs, anchor, dataset=seal)
    elif problem == "wrong_anchor":
        kwargs["authorization"] = kwargs["authorization"].model_copy(
            update={"anchor_sha256": "b" * 64}
        )
    elif problem == "missing_extension":
        old = kwargs["manifest"]
        frozen = create_freeze_manifest(
            dataset_sha256=old.dataset_sha256,
            feature_set_sha256=old.feature_set_sha256,
            label_set_sha256=old.label_set_sha256,
            universe_sha256=old.universe_sha256,
            split_sha256=old.split_sha256,
            cost_policy_sha256=old.cost_policy_sha256,
            model_spec_sha256=old.model_spec_sha256,
            parameters_sha256=old.parameters_sha256,
            code_sha256=old.code_sha256,
            frozen_at=old.frozen_at,
        )
        kwargs, anchor = replace_anchor(tmp_path, kwargs, anchor, freeze_id=frozen.freeze_id)
        kwargs["manifest"] = frozen
    else:
        kwargs["authorization"] = kwargs["authorization"].model_copy(
            update={"authorized_at": NOW + timedelta(days=1)}
        )
    original = Path.read_bytes
    reads: list[Path] = []

    def watched(path: Path) -> bytes:
        if path == data:
            reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", watched)
    with pytest.raises(PermissionError):
        open_persistent_holdout(**kwargs)
    assert not reads and not (tmp_path / CLAIM_PATH).exists()


def test_claim_is_durable_before_data_read_and_decoder_cannot_reread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs, _, data = prepare_synthetic_holdout(tmp_path, monkeypatch)
    original = Path.read_bytes
    observed: list[bool] = []

    def watched(path: Path) -> bytes:
        if path == data:
            observed.append((tmp_path / CLAIM_PATH).is_file())
        return original(path)

    def decode(raw: bytes) -> bytes:
        claim = json.loads((tmp_path / CLAIM_PATH).read_text(encoding="utf-8"))
        assert claim["claim_consumed"] is True
        assert claim["claim_sha256"] == canonical_sha256(
            {key: value for key, value in claim.items() if key != "claim_sha256"}
        )
        with pytest.raises(PermissionError, match="OUTSIDE-CLAIMED"):
            data.read_bytes()
        return raw

    monkeypatch.setattr(Path, "read_bytes", watched)
    kwargs["loader"] = decode
    result = open_persistent_holdout(**kwargs)
    assert isinstance(result, bytes) and result.startswith(b"SYNTHETIC ONLY")
    assert observed == [True, True]
    entries = ExperimentEventJournal(tmp_path / ACCESS_JOURNAL_PATH).entries()
    assert entries[-1].event.details["vault_state"] == "OPENED"
    assert entries[-1].event.details["claim_consumed"] is True


@pytest.mark.parametrize("failure", ["decoder", "read_missing", "wrong_bytes", "claim_fsync"])
def test_failures_consume_claim_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    kwargs, _, data = prepare_synthetic_holdout(tmp_path, monkeypatch)
    if failure == "decoder":

        def decode(_: bytes) -> None:
            raise RuntimeError("synthetic decoder failure")

        kwargs["loader"] = decode
    elif failure == "read_missing":
        assert data.resolve().is_relative_to(tmp_path.resolve())
        data.unlink()
    elif failure == "wrong_bytes":
        data.write_bytes(b"tampered synthetic content")
    else:
        fsync = os.fsync
        calls = 0

        def broken_once(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("synthetic fsync failure after claim creation")
            fsync(descriptor)

        monkeypatch.setattr(os, "fsync", broken_once)
    with pytest.raises((OSError, RuntimeError, PermissionError)):
        open_persistent_holdout(**kwargs)
    assert (tmp_path / CLAIM_PATH).is_file()
    assert (
        ExperimentEventJournal(tmp_path / ACCESS_JOURNAL_PATH)
        .entries()[-1]
        .event.details["claim_consumed"]
        is True
    )
    kwargs["directory"] = tmp_path / "candidate-2"
    kwargs["authorization"] = kwargs["authorization"].model_copy(
        update={"generation": "new-generation"}
    )
    with pytest.raises(PermissionError, match="ALREADY-CLAIMED"):
        open_persistent_holdout(**kwargs)


def test_rename_alias_new_generation_and_new_candidate_share_claim_and_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs, anchor, data = prepare_synthetic_holdout(tmp_path, monkeypatch)
    open_persistent_holdout(**kwargs)
    renamed = data.with_name("renamed.bin")
    assert data.resolve().is_relative_to(tmp_path.resolve()) and renamed.resolve().is_relative_to(
        tmp_path.resolve()
    )
    data.rename(renamed)
    old: ResearchFreezeManifest = kwargs["manifest"]
    candidate = create_freeze_manifest(
        dataset_sha256=old.dataset_sha256,
        feature_set_sha256=old.feature_set_sha256,
        label_set_sha256=old.label_set_sha256,
        universe_sha256=old.universe_sha256,
        split_sha256=old.split_sha256,
        cost_policy_sha256=old.cost_policy_sha256,
        model_spec_sha256=old.model_spec_sha256,
        parameters_sha256="b" * 64,
        code_sha256=old.code_sha256,
        frozen_at=old.frozen_at,
        admission_extension=old.admission_extension,
    )
    seal = HoldoutDataSeal.model_validate(
        {
            **dict(anchor.dataset),
            "semantic_dataset_id": "renamed-semantic-id",
            "sealed_relative_path": renamed.relative_to(tmp_path).as_posix(),
        }
    )
    kwargs, _ = replace_anchor(
        tmp_path, kwargs, anchor, dataset=seal, freeze_id=candidate.freeze_id
    )
    kwargs.update(manifest=candidate, directory=tmp_path / "another-candidate")
    kwargs["authorization"] = kwargs["authorization"].model_copy(
        update={"generation": "new-generation"}
    )
    with pytest.raises(PermissionError, match="ALREADY-CLAIMED"):
        open_persistent_holdout(**kwargs)
    events = [
        entry.event for entry in ExperimentEventJournal(tmp_path / ACCESS_JOURNAL_PATH).entries()
    ]
    assert sum(event.event_type is ExperimentEventType.SUCCEEDED for event in events) == 1
    assert events[-1].details["freeze_id"] == candidate.freeze_id
    assert events[-1].details["generation"] == "new-generation"


@pytest.mark.parametrize("failure", ["lock_write", "lock_fsync", "start_fsync", "terminal_fsync"])
def test_durability_failures_keep_lock_until_independent_storage_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    kwargs, _, data = prepare_synthetic_holdout(tmp_path, monkeypatch)
    original_read = Path.read_bytes
    reads: list[Path] = []

    def watched(path: Path) -> bytes:
        if path == data:
            reads.append(path)
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", watched)
    if failure == "lock_write":

        def broken_write(_: int, __: bytes) -> int:
            raise OSError("synthetic lock write failure")

        monkeypatch.setattr(os, "write", broken_write)
    else:
        fsync = os.fsync
        calls = 0
        first_failure = {"lock_fsync": 1, "start_fsync": 2, "terminal_fsync": 4}[failure]

        def broken_fsync(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls >= first_failure:
                raise OSError("synthetic durability failure")
            fsync(descriptor)

        monkeypatch.setattr(os, "fsync", broken_fsync)
    with pytest.raises(OSError):
        open_persistent_holdout(**kwargs)
    assert (tmp_path / ACCESS_LOCK_PATH).is_file()
    assert (tmp_path / CLAIM_PATH).exists() is (failure == "terminal_fsync")
    assert len(reads) == (1 if failure == "terminal_fsync" else 0)
    with pytest.raises(PermissionError, match="STALE-LOCK"):
        open_persistent_holdout(**kwargs)


def test_deleting_only_claim_does_not_reset_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs, _, _ = prepare_synthetic_holdout(tmp_path, monkeypatch)
    open_persistent_holdout(**kwargs)
    claim = tmp_path / CLAIM_PATH
    assert claim.resolve().is_relative_to(tmp_path.resolve())
    claim.unlink()
    with pytest.raises(PermissionError, match="ALREADY-CLAIMED"):
        open_persistent_holdout(**kwargs)


@pytest.mark.parametrize("problem", ["missing", "corrupt", "wrong_genesis", "stale_lock"])
def test_missing_or_corrupt_storage_is_not_reinitialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    kwargs, anchor, _ = prepare_synthetic_holdout(tmp_path, monkeypatch)
    journal = tmp_path / ACCESS_JOURNAL_PATH
    if problem == "missing":
        assert journal.resolve().is_relative_to(tmp_path.resolve())
        journal.unlink()
    elif problem == "corrupt":
        journal.write_text("corrupt\n", encoding="utf-8")
    elif problem == "wrong_genesis":
        kwargs, _ = replace_anchor(tmp_path, kwargs, anchor, journal_genesis_entry_sha256="b" * 64)
    else:
        (tmp_path / ACCESS_LOCK_PATH).write_text("owned by another access", encoding="utf-8")
    with pytest.raises((PermissionError, ValueError)):
        open_persistent_holdout(**kwargs)
    assert not (tmp_path / CLAIM_PATH).exists()
    if problem == "stale_lock":
        assert (tmp_path / ACCESS_LOCK_PATH).read_text() == "owned by another access"


def test_concurrent_calls_allow_only_one_decoder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs, _, _ = prepare_synthetic_holdout(tmp_path, monkeypatch)
    entered, release = Event(), Event()
    calls: list[bytes] = []

    def decode(raw: bytes) -> int:
        calls.append(raw)
        entered.set()
        assert release.wait(3)
        return len(raw)

    kwargs["loader"] = decode
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(open_persistent_holdout, **kwargs)
        assert entered.wait(3)
        second = pool.submit(open_persistent_holdout, **kwargs)
        try:
            with pytest.raises(PermissionError, match="BUSY"):
                second.result(timeout=3)
        finally:
            release.set()
        assert first.result(timeout=3) == len(calls[0])
    assert len(calls) == 1


def test_read_firewall_blocks_raw_cache_feature_and_hardlink_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, anchor, data = prepare_synthetic_holdout(tmp_path, monkeypatch)
    paths = [data]
    for name in anchor.dataset.registered_aliases:
        path = tmp_path / name
        path.write_bytes(b"synthetic derivative")
        paths.append(path)
    hardlink = tmp_path / "outside-data-hardlink.bin"
    os.link(data, hardlink)
    paths.append(hardlink)
    with holdout_read_firewall(anchor):
        for path in paths:
            with pytest.raises(PermissionError, match="OUTSIDE-CLAIMED"):
                path.read_bytes()
        with pytest.raises(PermissionError, match="WRITE-FORBIDDEN"):
            data.write_bytes(b"no")


def test_symlink_alias_and_reparse_registration_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    kwargs, anchor, data = prepare_synthetic_holdout(tmp_path, monkeypatch)
    link = tmp_path / "alias.bin"
    try:
        link.symlink_to(data)
    except OSError as error:
        record_property(
            "native_symlink",
            f"UNAVAILABLE:{error.winerror if hasattr(error, 'winerror') else error.errno};reparse_guard_synthetic_check",
        )
        original = Path.is_symlink

        def simulated_reparse(path: Path) -> bool:
            return path == tmp_path / ANCHOR_PATH or original(path)

        monkeypatch.setattr(Path, "is_symlink", simulated_reparse)
        with pytest.raises(PermissionError, match="REPARSE"):
            open_persistent_holdout(**kwargs)
    else:
        record_property("native_symlink", "VERIFIED_ON_TEMP_SYNTHETIC_FILE")
        with holdout_read_firewall(anchor), pytest.raises(PermissionError, match="OUTSIDE-CLAIMED"):
            link.read_bytes()
        second = data.with_name("linked.bin")
        second.symlink_to(data)
        kwargs, _ = replace_anchor(
            tmp_path,
            kwargs,
            anchor,
            dataset=HoldoutDataSeal.model_validate(
                {
                    **dict(anchor.dataset),
                    "sealed_relative_path": second.relative_to(tmp_path).as_posix(),
                }
            ),
        )
        with pytest.raises(PermissionError, match="REPARSE"):
            open_persistent_holdout(**kwargs)


@pytest.mark.parametrize("kind", ["copy", "preview", "feature", "unknown"])
def test_development_cannot_read_holdout_copies_or_derived_features(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    _, anchor, _ = prepare_synthetic_holdout(tmp_path, monkeypatch)
    name = f"data/{kind}.bin"
    content = b"derived synthetic feature"
    digest = (
        anchor.dataset.dataset_sha256 if kind == "copy" else hashlib.sha256(content).hexdigest()
    )
    # The protected content hash is already registered. No bytes need be opened
    # to reject an alias; derived hashes include the complete source ancestry.
    path = tmp_path / name
    path.write_bytes(content)
    kwargs: dict[str, Any] = {
        "allowed_sources": {name: digest},
        "protected_roots": [tmp_path / "data/final_holdout"],
        "expected_holdout_anchor_sha256": anchor.anchor_sha256,
        "source_lineage": {name: (digest, anchor.dataset.dataset_sha256)},
        "lineage_complete": {name: kind != "unknown"},
    }
    original = Path.open

    def no_data_open(selected: Path, *args: Any, **options: Any) -> IO[Any]:
        if selected == path:
            raise AssertionError("protected source opened before lineage rejection")
        return cast("IO[Any]", original(selected, *args, **options))

    monkeypatch.setattr(Path, "open", no_data_open)
    with pytest.raises(PermissionError, match=r"LINEAGE|DERIVATION"):
        checked_development_path(tmp_path, path, **kwargs)


def test_independent_development_source_remains_usable_with_complete_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, anchor, _ = prepare_synthetic_holdout(tmp_path, monkeypatch)
    name = "data/development.bin"
    path = tmp_path / name
    path.write_bytes(b"independent synthetic development")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert (
        checked_development_path(
            tmp_path,
            path,
            allowed_sources={name: digest},
            protected_roots=[tmp_path / "data/final_holdout"],
            expected_holdout_anchor_sha256=anchor.anchor_sha256,
            source_lineage={name: (digest,)},
            lineage_complete={name: True},
        )
        == path
    )
    with pytest.raises(PermissionError, match="NOT-PINNED"):
        checked_development_path(tmp_path, path, allowed_sources={name: digest}, protected_roots=[])


def test_legacy_freeze_hash_is_stable_and_extended_hash_binds_every_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs, _, _ = prepare_synthetic_holdout(tmp_path, monkeypatch)
    extended: ResearchFreezeManifest = kwargs["manifest"]
    payload = extended.model_dump(mode="json", exclude={"freeze_id", "admission_extension"})
    payload["frozen_at"] = extended.frozen_at.isoformat()
    legacy = ResearchFreezeManifest.model_validate_json(
        json.dumps({**payload, "freeze_id": canonical_sha256(payload)})
    )
    assert "admission_extension" not in legacy.model_dump(mode="json")
    assert legacy.freeze_id != extended.freeze_id
    with pytest.raises(ValueError, match="freeze_id"):
        ResearchFreezeManifest.model_validate_json(
            extended.model_copy(update={"admission_extension": None}).model_dump_json()
        )


def test_all_gates_even_when_passing_only_request_independent_review() -> None:
    missing = independent_review_handoff(
        dict.fromkeys(FINAL_GATE_NAMES, None), immutable_report_sha256=None
    )
    assert missing["status"] == "NO_PROVEN_ALPHA"
    passed = independent_review_handoff(
        dict.fromkeys(FINAL_GATE_NAMES, True), immutable_report_sha256=HASH
    )
    assert passed["status"] == "INDEPENDENT_REVIEW_REQUIRED"
    assert passed["promotion_decision"] == "HOLD"
    assert all(
        passed[key] is False
        for key in (
            "production_ml_enabled",
            "paper_trading_admitted",
            "live_trading",
            "order_submission_enabled",
        )
    )
    with pytest.raises(ValueError, match="every frozen gate"):
        independent_review_handoff({}, immutable_report_sha256=HASH)


def test_real_inputs_and_access_are_absent_in_current_report() -> None:
    config = yaml.safe_load(
        Path("configs/research/alpha_v5_final_holdout_contract.yaml").read_text(encoding="utf-8")
    )
    validate_config(config)
    config["actual_access_authorization"] = {"allow_data_read": True}
    with pytest.raises(ValueError, match="NOT-AUTHORIZED"):
        validate_config(config)
    docs = build_documents({"b2_safety": {"strict_data_quality": "INSUFFICIENT"}})
    assert docs["holdout_eligibility.json"]["actual_content_accesses"] == 0
    assert docs["holdout_eligibility.json"]["dataset"] is None
    assert docs["independent_review.json"]["independent_review_completed"] is False
    assert docs["all_batches_status.json"]["real_research_acceptance"].startswith("NOT_COMPLETED")
