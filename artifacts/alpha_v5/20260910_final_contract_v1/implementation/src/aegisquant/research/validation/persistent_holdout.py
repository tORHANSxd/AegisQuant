"""A durable one-access claim around the existing final-holdout freeze contract."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256, safe_relative_path
from aegisquant.research.experiments.journal import (
    ExperimentEvent,
    ExperimentEventJournal,
    ExperimentEventType,
)
from aegisquant.research.validation.calendar_walkforward import add_months
from aegisquant.research.validation.holdout import FinalHoldoutVault, ResearchFreezeManifest
from aegisquant.research.validation.holdout_contract import (
    ACCESS_JOURNAL_PATH,
    ACCESS_LOCK_PATH,
    ANCHOR_PATH,
    CLAIM_PATH,
    HoldoutAccessAuthorization,
    HoldoutProjectAnchor,
)

# A caller's candidate/output directory never selects access storage. Tests replace
# this constant with a temporary synthetic project; production has no root override.
PROJECT_ROOT = Path(__file__).resolve().parents[4]
_claimed_reader_path: ContextVar[Path | None] = ContextVar(
    "aegis_claimed_reader_path", default=None
)


def _project_path(relative: str) -> Path:
    root = PROJECT_ROOT.absolute()
    if root.resolve() != root:
        raise PermissionError("AQ-HOLDOUT-PROJECT-ROOT-ALIAS")
    path = root / safe_relative_path(relative)
    for part in (root, *path.parents, path):
        if not part.is_relative_to(root):
            continue
        if part.is_symlink() or (
            part.exists()
            and getattr(part.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise PermissionError("AQ-HOLDOUT-REPARSE-PATH-FORBIDDEN")
    if not path.resolve().is_relative_to(root):
        raise PermissionError("AQ-HOLDOUT-PATH-OUTSIDE-PROJECT")
    return path


def _read_anchor(authority: HoldoutAccessAuthorization) -> HoldoutProjectAnchor:
    path = _project_path(ANCHOR_PATH)
    if not path.is_file():
        raise PermissionError("AQ-HOLDOUT-ANCHOR-NOT-REGISTERED")
    anchor = HoldoutProjectAnchor.model_validate_json(path.read_bytes())
    if (
        anchor.anchor_sha256 != authority.anchor_sha256
        or anchor.project_id != authority.project_id
        or anchor.freeze_id != authority.freeze_id
        or anchor.operator_authorization_sha256 != authority.operator_authorization_sha256
    ):
        raise PermissionError("AQ-HOLDOUT-ANCHOR-AUTHORITY-MISMATCH")
    return anchor


@contextmanager
def holdout_read_firewall(anchor: HoldoutProjectAnchor) -> Generator[None]:
    """Application-level reads, aliases and file identities; enable before opening handles.

    This does not replace OS permissions or independent append-only custody. Native
    extensions and already-open handles must not receive sealed paths/data in research.
    """
    root = PROJECT_ROOT.absolute()
    paths = tuple(
        root / safe_relative_path(name)
        for name in (anchor.dataset.sealed_relative_path, *anchor.dataset.registered_aliases)
    )
    resolved = {path.resolve() for path in paths}
    file_ids = {
        (row.st_dev, row.st_ino) for path in paths if path.is_file() for row in (path.stat(),)
    }
    active = True

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if not active or event != "open" or not args:
            return
        value = args[0]
        target: Path | None = None
        identity: tuple[int, int] | None = None
        if isinstance(value, (str, bytes)):
            target = Path(os.fsdecode(value)).absolute().resolve()
            if target.is_file():
                row = target.stat()
                identity = (row.st_dev, row.st_ino)
        elif isinstance(value, int):
            row = os.fstat(value)
            identity = (row.st_dev, row.st_ino)
        protected = target in resolved or identity in file_ids
        if not protected:
            return
        mode, flags = args[1] or "", args[2] or 0
        if any(value in mode for value in "wax+") or flags & (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        ):
            raise PermissionError("AQ-HOLDOUT-SEALED-DATA-WRITE-FORBIDDEN")
        if target is None or target != _claimed_reader_path.get():
            raise PermissionError("AQ-HOLDOUT-READ-OUTSIDE-CLAIMED-GATE")

    sys.addaudithook(audit)
    try:
        yield
    finally:
        active = False


def _validate_eligibility(
    anchor: HoldoutProjectAnchor,
    manifest: ResearchFreezeManifest,
    authority: HoldoutAccessAuthorization,
    *,
    holdout_start: datetime,
    holdout_end: datetime,
    previously_used_through: datetime,
    accessed_at: datetime,
) -> None:
    seal = anchor.dataset
    if manifest.admission_extension is None:
        raise PermissionError("AQ-HOLDOUT-COMPLETE-FREEZE-EXTENSION-REQUIRED")
    if manifest.freeze_id != anchor.freeze_id or manifest.dataset_sha256 != seal.dataset_sha256:
        raise PermissionError("AQ-HOLDOUT-FROZEN-CANDIDATE-DATA-MISMATCH")
    if (
        not manifest.frozen_at <= authority.authorized_at <= accessed_at
        or not anchor.created_at <= authority.authorized_at
        or holdout_end > accessed_at
    ):
        raise PermissionError("AQ-HOLDOUT-AUTHORITY-OR-DATA-NOT-YET-AVAILABLE")
    if (holdout_start, holdout_end, previously_used_through) != (
        seal.start,
        seal.end_exclusive,
        seal.previously_used_through,
    ):
        raise PermissionError("AQ-HOLDOUT-REGISTERED-PERIOD-MISMATCH")
    if (
        seal.independent_metadata_verification != "VERIFIED"
        or seal.source_was_previously_accessed is not False
    ):
        raise PermissionError("AQ-HOLDOUT-UNUSED-PROVENANCE-NOT-VERIFIED")
    if (seal.source_material_start, seal.source_material_end_exclusive) != (
        seal.start,
        seal.end_exclusive,
    ):
        raise PermissionError("AQ-HOLDOUT-SOURCE-TAIL-OR-OUTSIDE-MATERIAL-CONTAMINATION")


def _append_access_event(
    journal: ExperimentEventJournal,
    run_id: str,
    kind: ExperimentEventType,
    accessed_at: datetime,
    details: dict[str, Any],
) -> None:
    journal.append(
        ExperimentEvent(
            event_id=f"{run_id}:{kind.value}",
            run_id=run_id,
            event_type=kind,
            recorded_at_utc=accessed_at,
            details=details,
        )
    )


def open_persistent_holdout[T](
    *,
    directory: Path,
    manifest: ResearchFreezeManifest | None,
    expected_dataset_sha256: str,
    holdout_start: datetime,
    holdout_end: datetime,
    previously_used_through: datetime,
    loader: Callable[[bytes], T],
    accessed_at: datetime,
    authorization: HoldoutAccessAuthorization | None = None,
) -> T:
    """One project-wide claim, verified sealed bytes, then the caller's frozen decoder.

    No unanchored legacy access is permitted. Missing logs/anchors are never created
    here: an independently reviewed metadata registration must precede the first read.
    """
    if manifest is None or manifest.frozen_at > accessed_at:
        raise PermissionError("AQ-HOLDOUT-NOT-FROZEN")
    if manifest.dataset_sha256 != expected_dataset_sha256:
        raise PermissionError("AQ-HOLDOUT-DATASET-HASH-MISMATCH")
    if holdout_start <= previously_used_through or holdout_end < add_months(holdout_start, 12):
        raise PermissionError("AQ-HOLDOUT-NO-UNUSED-TWELVE-MONTHS")
    if authorization is None:
        raise PermissionError("AQ-HOLDOUT-ANCHORED-AUTHORIZATION-REQUIRED")
    manifest = ResearchFreezeManifest.model_validate_json(manifest.model_dump_json())
    authorization = HoldoutAccessAuthorization.model_validate_json(authorization.model_dump_json())
    anchor = _read_anchor(authorization)
    _validate_eligibility(
        anchor,
        manifest,
        authorization,
        holdout_start=holdout_start,
        holdout_end=holdout_end,
        previously_used_through=previously_used_through,
        accessed_at=accessed_at,
    )
    if not directory.absolute().is_relative_to(PROJECT_ROOT.absolute()):
        raise PermissionError("AQ-HOLDOUT-OUTPUT-DIRECTORY-OUTSIDE-PROJECT")
    if directory.absolute() != PROJECT_ROOT.absolute():
        _project_path(directory.absolute().relative_to(PROJECT_ROOT.absolute()).as_posix())
    claim = _project_path(CLAIM_PATH)
    journal_path = _project_path(ACCESS_JOURNAL_PATH)
    if not journal_path.is_file():
        raise PermissionError("AQ-HOLDOUT-REGISTERED-JOURNAL-MISSING-NO-RESET")
    lock = _project_path(ACCESS_LOCK_PATH)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise PermissionError("AQ-HOLDOUT-ACCESS-BUSY-OR-STALE-LOCK") from error
    lock_identity = os.fstat(descriptor)
    release_lock = False
    try:
        os.write(
            descriptor,
            canonical_json_bytes({"anchor_sha256": anchor.anchor_sha256, "pid": os.getpid()}),
        )
        os.fsync(descriptor)
        journal = ExperimentEventJournal(journal_path)
        entries = journal.entries()
        if (
            not entries
            or entries[0].entry_hash != anchor.journal_genesis_entry_sha256
            or entries[0].event.details.get("kind") != "PROJECT_HOLDOUT_ANCHOR_GENESIS"
        ):
            raise PermissionError("AQ-HOLDOUT-JOURNAL-GENESIS-MISMATCH-NO-RESET")
        if _read_anchor(authorization) != anchor:
            raise PermissionError("AQ-HOLDOUT-ANCHOR-CHANGED")
        run_id = f"FINAL-ACCESS:{uuid4()}"
        details: dict[str, Any] = {
            "anchor_sha256": anchor.anchor_sha256,
            "semantic_dataset_id": anchor.dataset.semantic_dataset_id,
            "freeze_id": manifest.freeze_id,
            "generation": authorization.generation,
            "candidate_output_directory": directory.absolute()
            .relative_to(PROJECT_ROOT.absolute())
            .as_posix(),
            "claim_consumed": False,
            "orders_authorized": False,
        }
        _append_access_event(journal, run_id, ExperimentEventType.STARTED, accessed_at, details)
        consumed = False
        terminal_event_attempted = False
        try:
            if claim.exists() or any(
                entry.event.details.get("claim_consumed") is True for entry in entries
            ):
                raise PermissionError("AQ-HOLDOUT-ALREADY-CLAIMED")
            payload = {
                **details,
                "dataset_sha256": expected_dataset_sha256,
                "accessed_at": accessed_at.isoformat(),
                "start": holdout_start.isoformat(),
                "end": holdout_end.isoformat(),
                "status": "CLAIMED_BEFORE_ANY_DATA_READ",
                "claim_consumed": True,
            }
            with claim.open("xb") as stream:
                consumed = True
                stream.write(
                    canonical_json_bytes({**payload, "claim_sha256": canonical_sha256(payload)})
                )
                stream.flush()
                os.fsync(stream.fileno())

            def read_verified() -> T:
                path = _project_path(anchor.dataset.sealed_relative_path)
                token = _claimed_reader_path.set(path.resolve())
                try:
                    data = path.read_bytes()
                finally:
                    _claimed_reader_path.reset(token)
                if (
                    len(data) != anchor.dataset.content_bytes
                    or hashlib.sha256(data).hexdigest() != expected_dataset_sha256
                ):
                    raise PermissionError("AQ-HOLDOUT-LOADED-BYTES-HASH-OR-SIZE-MISMATCH")
                return loader(data)

            with holdout_read_firewall(anchor):
                vault = FinalHoldoutVault(
                    holdout_id=anchor.dataset.semantic_dataset_id,
                    expected_dataset_sha256=expected_dataset_sha256,
                    loader=read_verified,
                )
                vault.freeze(manifest, occurred_at=accessed_at)
                result = vault.open_once(freeze_id=manifest.freeze_id, occurred_at=accessed_at)
            terminal_event_attempted = True
            _append_access_event(
                journal,
                run_id,
                ExperimentEventType.SUCCEEDED,
                accessed_at,
                {
                    **details,
                    "claim_consumed": True,
                    "loaded_bytes_sha256": expected_dataset_sha256,
                    "vault_state": vault.state.value,
                    "vault_audit_sha256": canonical_sha256(
                        [entry.model_dump(mode="json") for entry in vault.audit_log()]
                    ),
                },
            )
            release_lock = True
            return result
        except BaseException as error:
            # A failed terminal fsync may already have appended a terminal row.
            # Do not append a second terminal or hide the original storage error.
            if not terminal_event_attempted:
                try:
                    _append_access_event(
                        journal,
                        run_id,
                        ExperimentEventType.ERROR,
                        accessed_at,
                        {
                            **details,
                            "claim_consumed": consumed,
                            "reason": f"{type(error).__name__}: {error}",
                        },
                    )
                except BaseException as journal_error:
                    error.add_note(f"Terminal audit could not persist: {journal_error}")
                    raise error from journal_error
                release_lock = True
            raise
    finally:
        os.close(descriptor)
        # If a durable terminal journal entry could not be written, retain the
        # lock and require an independent storage review; never silently retry.
        if release_lock:
            current_lock = lock.lstat()
            if (current_lock.st_dev, current_lock.st_ino) != (
                lock_identity.st_dev,
                lock_identity.st_ino,
            ):
                raise PermissionError("AQ-HOLDOUT-LOCK-IDENTITY-CHANGED")
            lock.unlink()
