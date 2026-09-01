from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aegisquant.data.hashing import canonical_sha256
from aegisquant.intelligence.static_analysis.models import (
    ArtifactKind,
    SourceArtifact,
    StaticReviewState,
)
from aegisquant.intelligence.static_analysis.scanner import scan_source_bytes


def artifact(path: Path, kind: ArtifactKind = ArtifactKind.PYTHON) -> SourceArtifact:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    return SourceArtifact(
        artifact_id=canonical_sha256({"path": path.name, "sha256": digest}),
        source_id="p09-static-fixture",
        relative_path=path.name,
        kind=kind,
        sha256=digest,
        size_bytes=len(raw),
        media_type="text/x-python",
        static_review_state=StaticReviewState.QUARANTINED,
    )


def test_dangerous_source_is_detected_without_execution(project_root: Path, tmp_path: Path) -> None:
    path = project_root / "tests/fixtures/p09/unsafe_strategy.py"
    marker = tmp_path / "would-have-executed.txt"
    report = scan_source_bytes(
        source_id="p09-static-fixture",
        artifact=artifact(path),
        raw=path.read_bytes(),
    )
    categories = {item.category for item in report.findings}
    assert {
        "network_import",
        "subprocess_import",
        "embedded_credential",
        "file_write",
        "network_call",
        "subprocess",
        "unsafe_deserialization",
        "dynamic_execution",
        "destructive_file_operation",
    } <= categories
    assert report.review_state is StaticReviewState.QUARANTINED
    assert report.executable_allowed is False
    assert not marker.exists()


def test_notebook_code_cells_are_parsed_but_kernel_is_never_started(tmp_path: Path) -> None:
    path = tmp_path / "strategy.ipynb"
    path.write_text(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {},
                "cells": [
                    {"cell_type": "markdown", "metadata": {}, "source": ["ignore"]},
                    {
                        "cell_type": "code",
                        "metadata": {},
                        "execution_count": None,
                        "outputs": [],
                        "source": ["run_daily(rebalance)\n", "order_target('BTC', 1)\n"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    report = scan_source_bytes(
        source_id="p09-static-fixture",
        artifact=artifact(path, ArtifactKind.NOTEBOOK),
        raw=path.read_bytes(),
    )
    assert report.language == "python-notebook"
    assert report.scheduled_callbacks == ("run_daily",)
    assert report.trade_calls == ("order_target",)
    assert report.executable_allowed is False


def test_future_shift_and_last_row_access_are_flagged(tmp_path: Path) -> None:
    path = tmp_path / "lookahead.py"
    path.write_text("future = frame.shift(-1)\nlatest = frame.iloc[-1]\n", encoding="utf-8")
    report = scan_source_bytes(
        source_id="p09-static-fixture",
        artifact=artifact(path),
        raw=path.read_bytes(),
    )
    categories = {item.category for item in report.findings}
    assert {"lookahead", "time_index_semantics"} <= categories
    assert report.executable_allowed is False
