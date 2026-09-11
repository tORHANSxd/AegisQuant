"""Small research-entry guards reusing the append-only experiment event journal."""

import hashlib
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue

from aegisquant.data.hashing import ensure_sha256
from aegisquant.research.experiments.journal import (
    ExperimentEvent,
    ExperimentEventJournal,
    ExperimentEventType,
)


def checked_development_path(
    root: Path,
    path: Path,
    *,
    allowed_sources: Mapping[str, str],
    protected_roots: Sequence[Path],
    protected_source_sha256: Sequence[str] = (),
    source_lineage: Mapping[str, Sequence[str]] | None = None,
    lineage_complete: Mapping[str, bool] | None = None,
    expected_holdout_anchor_sha256: str | None = None,
) -> Path:
    """Reject protected/unknown paths before opening; then bind the approved bytes."""
    resolved = path.resolve()
    if {part.casefold() for part in resolved.parts} & {"holdout", "final_holdout"}:
        raise PermissionError("AQ-DEVELOPMENT-HOLDOUT-PATH-FORBIDDEN")
    if any(resolved.is_relative_to(p.resolve()) for p in protected_roots):
        raise PermissionError("AQ-DEVELOPMENT-HOLDOUT-PATH-FORBIDDEN")
    if not resolved.is_relative_to(root.resolve()):
        raise PermissionError("AQ-DEVELOPMENT-PATH-OUTSIDE-PROJECT")
    allowed = {(root / name).resolve(): digest for name, digest in allowed_sources.items()}
    expected = allowed.get(resolved)
    if expected is None:
        raise PermissionError("AQ-DEVELOPMENT-DATA-NOT-REGISTERED")
    ensure_sha256(expected, field_name="development source")
    protected_hashes = set(protected_source_sha256)
    anchor_path = root / "state/final_holdout_anchor.json"
    if anchor_path.exists() or expected_holdout_anchor_sha256 is not None:
        from aegisquant.research.validation.holdout_contract import HoldoutProjectAnchor

        if (
            not anchor_path.is_file()
            or anchor_path.is_symlink()
            or anchor_path.resolve() != anchor_path.absolute()
        ):
            raise PermissionError("AQ-DEVELOPMENT-HOLDOUT-ANCHOR-MISSING-OR-ALIASED")
        anchor = HoldoutProjectAnchor.model_validate_json(anchor_path.read_bytes())
        if anchor.anchor_sha256 != expected_holdout_anchor_sha256:
            raise PermissionError("AQ-DEVELOPMENT-HOLDOUT-ANCHOR-NOT-PINNED")
        protected_hashes.update(anchor.dataset.protected_hashes)
    if protected_hashes or source_lineage is not None or lineage_complete is not None:
        for digest in protected_hashes:
            ensure_sha256(digest, field_name="protected source identity")
        names = [name for name in allowed_sources if (root / name).resolve() == resolved]
        if (
            len(names) != 1
            or source_lineage is None
            or lineage_complete is None
            or lineage_complete.get(names[0]) is not True
        ):
            raise PermissionError("AQ-DEVELOPMENT-COMPLETE-SOURCE-LINEAGE-REQUIRED")
        lineage = source_lineage.get(names[0])
        if not lineage or expected not in lineage:
            raise PermissionError("AQ-DEVELOPMENT-SOURCE-LINEAGE-IDENTITY-MISSING")
        for digest in lineage:
            ensure_sha256(digest, field_name="source lineage")
        if protected_hashes.intersection(lineage):
            raise PermissionError("AQ-DEVELOPMENT-HOLDOUT-DERIVATION-FORBIDDEN")
    with resolved.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise ValueError("AQ-DEVELOPMENT-DATA-HASH-MISMATCH")
    return resolved


def require_promotion_evidence(
    *, point_in_time_universe: bool, verified_execution: bool, unused_holdout_months: int
) -> None:
    if not point_in_time_universe or not verified_execution or unused_holdout_months < 12:
        raise PermissionError("AQ-RESEARCH-PROMOTION-INSUFFICIENT-EVIDENCE")


@contextmanager
def registered_run(
    directory: Path,
    run_id: str,
    *,
    planned_run_ids: Sequence[str],
    bindings: dict[str, JsonValue],
) -> Generator[None]:
    """One serialized command owns a generation; failures consume registered slots too."""
    if run_id not in planned_run_ids:
        raise PermissionError("AQ-EXPERIMENT-UNREGISTERED-RUN")
    claims = directory / "run_claims"
    claims.mkdir(parents=True, exist_ok=True)
    claim = claims / hashlib.sha256(run_id.encode()).hexdigest()
    with claim.open("x", encoding="utf-8") as stream:
        stream.write(run_id)
    journal = ExperimentEventJournal(directory / "experiment_events.jsonl")
    journal.append(
        ExperimentEvent(
            event_id=f"{run_id}:STARTED",
            run_id=run_id,
            event_type=ExperimentEventType.STARTED,
            recorded_at_utc=datetime.now(UTC),
            details=bindings,
        )
    )
    try:
        yield
    except BaseException as error:
        journal.append(
            ExperimentEvent(
                event_id=f"{run_id}:ERROR",
                run_id=run_id,
                event_type=ExperimentEventType.ERROR,
                recorded_at_utc=datetime.now(UTC),
                details={"reason": f"{type(error).__name__}: {error}", **bindings},
            )
        )
        raise
    else:
        journal.append(
            ExperimentEvent(
                event_id=f"{run_id}:SUCCEEDED",
                run_id=run_id,
                event_type=ExperimentEventType.SUCCEEDED,
                recorded_at_utc=datetime.now(UTC),
                details=bindings,
            )
        )
