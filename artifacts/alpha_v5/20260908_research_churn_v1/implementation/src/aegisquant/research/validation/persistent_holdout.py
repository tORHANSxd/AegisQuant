"""A durable one-access claim around the existing final-holdout freeze contract."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from aegisquant.research.validation.calendar_walkforward import add_months
from aegisquant.research.validation.holdout import ResearchFreezeManifest


def open_persistent_holdout[T](
    *,
    directory: Path,
    manifest: ResearchFreezeManifest | None,
    expected_dataset_sha256: str,
    holdout_start: datetime,
    holdout_end: datetime,
    previously_used_through: datetime,
    loader: Callable[[], T],
    accessed_at: datetime,
) -> T:
    if manifest is None or manifest.frozen_at > accessed_at:
        raise PermissionError("AQ-HOLDOUT-NOT-FROZEN")
    if manifest.dataset_sha256 != expected_dataset_sha256:
        raise PermissionError("AQ-HOLDOUT-DATASET-HASH-MISMATCH")
    if holdout_start <= previously_used_through or holdout_end < add_months(holdout_start, 12):
        raise PermissionError("AQ-HOLDOUT-NO-UNUSED-TWELVE-MONTHS")
    directory.mkdir(parents=True, exist_ok=True)
    claim = directory / "holdout_access_claim.json"
    payload = {
        "freeze_id": manifest.freeze_id,
        "dataset_sha256": expected_dataset_sha256,
        "accessed_at": accessed_at.isoformat(),
        "start": holdout_start.isoformat(),
        "end": holdout_end.isoformat(),
        "status": "CLAIMED_BEFORE_LOADER",
    }
    try:
        with claim.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False)
            stream.write("\n")
    except FileExistsError as error:
        raise PermissionError("AQ-HOLDOUT-ALREADY-CLAIMED") from error
    # A loader failure deliberately consumes access; a documented code-defect
    # exception requires a separately reviewed recovery, never an automatic retry.
    return loader()
