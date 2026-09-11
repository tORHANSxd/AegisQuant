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
) -> Path:
    """Reject protected/unknown paths before opening; then bind the approved bytes."""
    resolved = path.resolve()
    if any(resolved.is_relative_to(p.resolve()) for p in protected_roots):
        raise PermissionError("AQ-DEVELOPMENT-HOLDOUT-PATH-FORBIDDEN")
    if not resolved.is_relative_to(root.resolve()):
        raise PermissionError("AQ-DEVELOPMENT-PATH-OUTSIDE-PROJECT")
    allowed = {(root / name).resolve(): digest for name, digest in allowed_sources.items()}
    expected = allowed.get(resolved)
    if expected is None:
        raise PermissionError("AQ-DEVELOPMENT-DATA-NOT-REGISTERED")
    ensure_sha256(expected, field_name="development source")
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
