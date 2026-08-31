"""Frozen specification integrity tests."""

import hashlib
from pathlib import Path

EXPECTED_SHA256 = "1265a4feeb126bf9004685b80c0aa01d053fd983079b80d5c9063abefc382d1f"


def sha256(path: Path) -> str:
    """Hash a file without text normalization."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_specification_copy_is_byte_identical(project_root: Path) -> None:
    source = project_root / "AegisQuant_v3.1_Multimodal_Event_Intelligence_Codex_Master_Taskbook.md"
    frozen = project_root / "docs/spec/AegisQuant_Master_Taskbook_v3_1.md"

    assert sha256(source) == EXPECTED_SHA256
    assert sha256(frozen) == EXPECTED_SHA256
    assert source.read_bytes() == frozen.read_bytes()
    assert len(source.read_text(encoding="utf-8").splitlines()) == 7023


def test_spec_index_records_frozen_identity(project_root: Path) -> None:
    index = (project_root / "state/SPEC_INDEX.md").read_text(encoding="utf-8")

    assert EXPECTED_SHA256 in index
    assert "7,023" in index
    assert "P00" in index and "P18" in index
