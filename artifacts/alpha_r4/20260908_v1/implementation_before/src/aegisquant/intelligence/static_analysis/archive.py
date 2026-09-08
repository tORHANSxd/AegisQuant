"""Bounded, immutable importer for user-authorized manual knowledge exports."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import stat
import tempfile
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Final, cast

import yaml
from pydantic import Field

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256, sha256_file
from aegisquant.domain.base import DomainModel
from aegisquant.intelligence.static_analysis.models import (
    ArtifactKind,
    SourceArtifact,
    SourceManifest,
    StaticReviewState,
)

ALLOWED_SUFFIXES: Final = frozenset(
    {
        ".yaml",
        ".yml",
        ".html",
        ".htm",
        ".md",
        ".py",
        ".ipynb",
        ".json",
        ".txt",
        ".sha256",
        ".csv",
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
    }
)
FORBIDDEN_SUFFIXES: Final = frozenset(
    {
        ".bat",
        ".cmd",
        ".com",
        ".dll",
        ".exe",
        ".jar",
        ".js",
        ".lnk",
        ".msi",
        ".ps1",
        ".scr",
        ".so",
        ".docm",
        ".xlsm",
        ".pptm",
    }
)
ACTIVE_HTML_TAGS: Final = frozenset(
    {"script", "style", "iframe", "object", "embed", "form", "input", "button", "svg"}
)


class KnowledgeImportLimits(DomainModel):
    maximum_files: int = Field(default=256, ge=1, le=10_000)
    maximum_file_bytes: int = Field(default=16 * 1024 * 1024, ge=1024)
    maximum_total_bytes: int = Field(default=128 * 1024 * 1024, ge=1024)
    maximum_compression_ratio: int = Field(default=50, ge=1, le=1000)


class KnowledgeImportResult(DomainModel):
    source_manifest: SourceManifest
    package_sha256: str
    archive_relative_path: str
    artifacts: tuple[SourceArtifact, ...] = Field(min_length=1)
    raw_files_preserved: int
    sanitized_files_created: int
    source_code_executed: bool = False
    notebook_kernel_started: bool = False


class _SafeTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocked_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in ACTIVE_HTML_TAGS:
            self._blocked_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag, attrs

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in ACTIVE_HTML_TAGS and self._blocked_depth:
            self._blocked_depth -= 1
        elif self._blocked_depth == 0 and tag.casefold() in {"p", "div", "li", "br", "pre"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._blocked_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        lines = (" ".join(part.split()) for part in "".join(self._parts).splitlines())
        return "\n".join(line for line in lines if line).strip() + "\n"


def sanitize_html_to_text(raw: bytes) -> bytes:
    """Return inert UTF-8 text; no HTML attributes or active URLs survive."""
    text = raw.decode("utf-8", errors="replace")
    parser = _SafeTextExtractor()
    parser.feed(text)
    parser.close()
    return parser.text().encode("utf-8")


def _artifact_kind(relative_path: str) -> ArtifactKind:
    path = Path(relative_path)
    suffix = path.suffix.casefold()
    if path.name.casefold() == "manifest.yaml":
        return ArtifactKind.MANIFEST
    if suffix in {".html", ".htm"}:
        return ArtifactKind.HTML
    if suffix == ".md":
        return ArtifactKind.MARKDOWN
    if suffix == ".py":
        return ArtifactKind.PYTHON
    if suffix == ".ipynb":
        return ArtifactKind.NOTEBOOK
    if path.name.casefold() == "comments.json":
        return ArtifactKind.COMMENTS
    if path.parts and path.parts[0].casefold() == "screenshots":
        return ArtifactKind.SCREENSHOT
    return ArtifactKind.ATTACHMENT


def _validate_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ValueError("AQ-KNOWLEDGE-ARCHIVE-PATH-TRAVERSAL")
    if any(part in {"", "."} for part in candidate.parts):
        raise ValueError("AQ-KNOWLEDGE-ARCHIVE-INVALID-PATH")
    if ":" in candidate.parts[0]:
        raise ValueError("AQ-KNOWLEDGE-ARCHIVE-DRIVE-PATH")
    return candidate.as_posix()


def _validate_suffix(relative_path: str) -> None:
    suffix = Path(relative_path).suffix.casefold()
    if suffix in FORBIDDEN_SUFFIXES or suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"AQ-KNOWLEDGE-ARCHIVE-FILE-TYPE-REJECTED:{suffix or '<none>'}")


def _walk_directory(root: Path, limits: KnowledgeImportLimits) -> Iterator[tuple[str, Path]]:
    resolved = root.resolve(strict=True)
    if not resolved.is_dir() or resolved.is_symlink():
        raise ValueError("manual export root must be a non-symlink directory")
    total = 0
    count = 0
    for directory, directory_names, file_names in os.walk(resolved, followlinks=False):
        current = Path(directory)
        if current.is_symlink():
            raise ValueError("AQ-KNOWLEDGE-ARCHIVE-SYMLINK-REJECTED")
        if any((current / name).is_symlink() for name in directory_names):
            raise ValueError("AQ-KNOWLEDGE-ARCHIVE-SYMLINK-REJECTED")
        directory_names.sort()
        file_names.sort()
        for name in file_names:
            path = current / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("AQ-KNOWLEDGE-ARCHIVE-NONREGULAR-REJECTED")
            relative = _validate_relative_path(path.relative_to(resolved).as_posix())
            _validate_suffix(relative)
            size = path.stat(follow_symlinks=False).st_size
            if size > limits.maximum_file_bytes:
                raise ValueError("AQ-KNOWLEDGE-ARCHIVE-FILE-LIMIT")
            count += 1
            total += size
            if count > limits.maximum_files or total > limits.maximum_total_bytes:
                raise ValueError("AQ-KNOWLEDGE-ARCHIVE-PACKAGE-LIMIT")
            yield relative, path


def _validate_zip_member(info: zipfile.ZipInfo, limits: KnowledgeImportLimits) -> str:
    relative = _validate_relative_path(info.filename)
    _validate_suffix(relative)
    unix_mode = info.external_attr >> 16
    if stat.S_ISLNK(unix_mode) or stat.S_ISCHR(unix_mode) or stat.S_ISBLK(unix_mode):
        raise ValueError("AQ-KNOWLEDGE-ARCHIVE-ZIP-NONREGULAR-REJECTED")
    if info.flag_bits & 0x1:
        raise ValueError("AQ-KNOWLEDGE-ARCHIVE-ENCRYPTED-ZIP-REJECTED")
    if info.file_size > limits.maximum_file_bytes:
        raise ValueError("AQ-KNOWLEDGE-ARCHIVE-FILE-LIMIT")
    if info.file_size and info.compress_size == 0:
        raise ValueError("AQ-KNOWLEDGE-ARCHIVE-ZIP-BOMB")
    if (
        info.compress_size
        and info.file_size / info.compress_size > limits.maximum_compression_ratio
    ):
        raise ValueError("AQ-KNOWLEDGE-ARCHIVE-ZIP-BOMB")
    return relative


def _extract_zip(source: Path, destination: Path, limits: KnowledgeImportLimits) -> None:
    total = 0
    count = 0
    with zipfile.ZipFile(source) as archive:
        members = sorted(
            (item for item in archive.infolist() if not item.is_dir()), key=lambda x: x.filename
        )
        for info in members:
            relative = _validate_zip_member(info, limits)
            count += 1
            total += info.file_size
            if count > limits.maximum_files or total > limits.maximum_total_bytes:
                raise ValueError("AQ-KNOWLEDGE-ARCHIVE-PACKAGE-LIMIT")
            output = destination / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source_stream, output.open("xb") as output_stream:
                copied = shutil.copyfileobj(source_stream, output_stream, length=1024 * 1024)
                del copied


def _load_manifest(path: Path) -> SourceManifest:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("manifest.yaml must contain an object")
    raw = cast("dict[str, object]", loaded)
    if "schema_version" not in raw:
        raw["schema_version"] = "1"
    return SourceManifest.model_validate_json(json.dumps(raw, ensure_ascii=False))


def _package_hash(files: list[tuple[str, Path]]) -> str:
    return canonical_sha256(
        [
            {
                "relative_path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for relative, path in files
        ]
    )


@dataclass(frozen=True, slots=True)
class ManualExportImporter:
    archive_root: Path
    limits: KnowledgeImportLimits = field(default_factory=KnowledgeImportLimits)

    def import_path(self, source: Path) -> KnowledgeImportResult:
        """Archive a directory or ZIP without importing or executing any source code."""
        resolved_source = source.resolve(strict=True)
        resolved_archive = self.archive_root.resolve(strict=False)
        try:
            resolved_archive.relative_to(resolved_source)
        except ValueError:
            pass
        else:
            raise ValueError("archive destination cannot be inside the untrusted source")
        if resolved_source.is_file():
            if resolved_source.suffix.casefold() != ".zip":
                raise ValueError("manual export file must be a ZIP archive")
            with tempfile.TemporaryDirectory(prefix="aq-knowledge-zip-") as temporary:
                extracted = Path(temporary)
                _extract_zip(resolved_source, extracted, self.limits)
                return self._import_directory(extracted)
        return self._import_directory(resolved_source)

    def _import_directory(self, source: Path) -> KnowledgeImportResult:
        files = list(_walk_directory(source, self.limits))
        if not files or files[0][0] != "manifest.yaml":
            manifest_matches = [path for relative, path in files if relative == "manifest.yaml"]
            if not manifest_matches:
                raise ValueError("manual export requires root manifest.yaml")
        manifest_path = next(path for relative, path in files if relative == "manifest.yaml")
        manifest = _load_manifest(manifest_path)
        package_sha256 = _package_hash(files)
        final_directory = self.archive_root / manifest.source_id / package_sha256
        result_path = final_directory / "import_result.json"
        if final_directory.exists():
            if not result_path.is_file():
                raise ValueError("AQ-KNOWLEDGE-ARCHIVE-IMMUTABLE-CONFLICT")
            existing = KnowledgeImportResult.model_validate_json(result_path.read_bytes())
            if existing.package_sha256 != package_sha256:
                raise ValueError("AQ-KNOWLEDGE-ARCHIVE-IMMUTABLE-CONFLICT")
            return existing
        parent = final_directory.parent
        parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="package-", dir=parent))
        artifacts: list[SourceArtifact] = []
        sanitized_count = 0
        try:
            for relative, source_path in files:
                raw = source_path.read_bytes()
                raw_hash = hashlib.sha256(raw).hexdigest()
                raw_output = staging / "raw" / relative
                raw_output.parent.mkdir(parents=True, exist_ok=True)
                with raw_output.open("xb") as output:
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                kind = _artifact_kind(relative)
                sanitized_relative: str | None = None
                if kind is ArtifactKind.HTML:
                    sanitized_relative = f"sanitized/{relative}.txt"
                    sanitized_output = staging / sanitized_relative
                    sanitized_output.parent.mkdir(parents=True, exist_ok=True)
                    sanitized_output.write_bytes(sanitize_html_to_text(raw))
                    sanitized_count += 1
                review_state = (
                    StaticReviewState.QUARANTINED
                    if kind in {ArtifactKind.PYTHON, ArtifactKind.NOTEBOOK}
                    else StaticReviewState.REVIEW_REQUIRED
                )
                artifacts.append(
                    SourceArtifact(
                        artifact_id=canonical_sha256(
                            {
                                "source_id": manifest.source_id,
                                "relative_path": relative,
                                "sha256": raw_hash,
                            }
                        ),
                        source_id=manifest.source_id,
                        relative_path=relative,
                        kind=kind,
                        sha256=raw_hash,
                        size_bytes=len(raw),
                        media_type=mimetypes.guess_type(relative, strict=False)[0]
                        or "application/octet-stream",
                        sanitized_relative_path=sanitized_relative,
                        static_review_state=review_state,
                    )
                )
            result = KnowledgeImportResult(
                source_manifest=manifest,
                package_sha256=package_sha256,
                archive_relative_path=f"{manifest.source_id}/{package_sha256}",
                artifacts=tuple(artifacts),
                raw_files_preserved=len(files),
                sanitized_files_created=sanitized_count,
            )
            (staging / "artifacts.json").write_bytes(
                canonical_json_bytes([item.model_dump(mode="json") for item in artifacts])
            )
            (staging / "import_result.json").write_bytes(
                canonical_json_bytes(result.model_dump(mode="json"))
            )
            for attempt in range(3):
                try:
                    os.replace(staging, final_directory)
                    break
                except PermissionError:
                    if attempt == 2:
                        raise
                    time.sleep(0.05 * (attempt + 1))
            return result
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise


def load_import_result(path: Path) -> KnowledgeImportResult:
    """Read and validate a previously published import result."""
    payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    return KnowledgeImportResult.model_validate(payload)
