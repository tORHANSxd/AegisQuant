from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from aegisquant.intelligence.static_analysis.archive import ManualExportImporter


def test_manual_export_is_immutable_and_html_is_inert(project_root: Path, tmp_path: Path) -> None:
    source = project_root / "tests/fixtures/p09/joinquant_manual_export"
    importer = ManualExportImporter(tmp_path / "archive")
    first = importer.import_path(source)
    second = importer.import_path(source)
    assert first == second
    assert first.source_code_executed is False
    assert first.notebook_kernel_started is False
    assert first.raw_files_preserved == 5
    assert first.sanitized_files_created == 1
    package = tmp_path / "archive" / first.archive_relative_path
    raw_html = (package / "raw/page.html").read_text(encoding="utf-8")
    sanitized = (package / "sanitized/page.html.txt").read_text(encoding="utf-8")
    assert "<script>" in raw_html
    assert "fixtureExecuted" not in sanitized
    assert "javascript:" not in sanitized


def test_zip_path_traversal_and_compression_bomb_are_rejected(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape.py", "print('no')")
    with pytest.raises(ValueError, match="PATH-TRAVERSAL"):
        ManualExportImporter(tmp_path / "archive-a").import_path(traversal)

    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.yaml", "x" * 100_000)
    with pytest.raises(ValueError, match="ZIP-BOMB"):
        ManualExportImporter(tmp_path / "archive-b").import_path(bomb)


def test_macro_input_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.yaml").write_text("invalid: true\n", encoding="utf-8")
    (source / "payload.xlsm").write_bytes(b"macro")
    with pytest.raises(ValueError, match="FILE-TYPE-REJECTED"):
        ManualExportImporter(tmp_path / "archive").import_path(source)


def test_directory_symlink_is_rejected_without_following_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    linked = source / "linked"
    linked.mkdir(parents=True)
    (source / "manifest.yaml").write_text("invalid: true\n", encoding="utf-8")
    original = Path.is_symlink

    def marked_symlink(path: Path) -> bool:
        return path == linked or original(path)

    def single_level_walk(
        path: Path, *, followlinks: bool
    ) -> list[tuple[str, list[str], list[str]]]:
        assert followlinks is False
        return [(str(path), ["linked"], ["manifest.yaml"])]

    monkeypatch.setattr(Path, "is_symlink", marked_symlink)
    monkeypatch.setattr(
        "aegisquant.intelligence.static_analysis.archive.os.walk", single_level_walk
    )
    with pytest.raises(ValueError, match="SYMLINK-REJECTED"):
        ManualExportImporter(tmp_path / "archive").import_path(source)


def test_windows_directory_publish_retries_a_transient_lock(
    project_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = project_root / "tests/fixtures/p09/joinquant_manual_export"
    original = os.replace
    attempts = 0

    def transient_replace(source_path: Path, destination_path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("transient scanner lock")
        original(source_path, destination_path)

    monkeypatch.setattr(
        "aegisquant.intelligence.static_analysis.archive.os.replace", transient_replace
    )
    result = ManualExportImporter(tmp_path / "archive").import_path(source)
    assert result.raw_files_preserved == 5
    assert attempts == 2
