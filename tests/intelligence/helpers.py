from __future__ import annotations

import hashlib
from pathlib import Path

from aegisquant.data.hashing import canonical_sha256
from aegisquant.intelligence.static_analysis.extraction import (
    StrategyExtractionResult,
    extract_strategy_ir,
)
from aegisquant.intelligence.static_analysis.models import (
    ArtifactKind,
    SourceArtifact,
    StaticReviewState,
)
from aegisquant.intelligence.static_analysis.scanner import scan_source_bytes


def artifact_for(path: Path, *, source_id: str = "p09-safe-source") -> SourceArtifact:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    return SourceArtifact(
        artifact_id=canonical_sha256({"source_id": source_id, "path": path.name, "sha256": digest}),
        source_id=source_id,
        relative_path=path.name,
        kind=ArtifactKind.PYTHON,
        sha256=digest,
        size_bytes=len(raw),
        media_type="text/x-python",
        static_review_state=StaticReviewState.QUARANTINED,
    )


def extract_fixture(
    path: Path, *, strategy_id: str = "p09-source-strategy"
) -> StrategyExtractionResult:
    source_id = "p09-safe-source"
    artifact = artifact_for(path, source_id=source_id)
    raw = path.read_bytes()
    scan = scan_source_bytes(source_id=source_id, artifact=artifact, raw=raw)
    return extract_strategy_ir(
        strategy_id=strategy_id,
        source_id=source_id,
        artifact=artifact,
        raw=raw,
        scan=scan,
    )
