"""Create the frozen repository directory layout safely and idempotently."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Final, cast

DEFAULT_MANIFEST: Final = Path("state/DIRECTORY_MANIFEST.json")


def validated_relative_path(raw_path: str) -> Path:
    """Return a safe project-relative directory path or fail closed."""
    candidate = PurePosixPath(raw_path)
    has_drive_prefix = bool(candidate.parts and ":" in candidate.parts[0])
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or has_drive_prefix
        or "\\" in raw_path
    ):
        raise ValueError(f"unsafe directory path: {raw_path!r}")
    if any(part in {"", "."} for part in candidate.parts):
        raise ValueError(f"non-canonical directory path: {raw_path!r}")
    return Path(*candidate.parts)


def create_directories(root: Path, manifest_path: Path) -> list[Path]:
    """Create all manifest directories below *root* and return resolved paths."""
    resolved_root = root.resolve()
    payload_object: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload_object, dict):
        raise TypeError("manifest root must be an object")
    payload = cast("dict[str, object]", payload_object)
    raw_directories = payload.get("directories")
    if not isinstance(raw_directories, list) or not raw_directories:
        raise ValueError("manifest must contain a non-empty directories list")

    created: list[Path] = []
    for raw_path in cast("list[object]", raw_directories):
        if not isinstance(raw_path, str):
            raise TypeError("every manifest directory must be a string")
        target = (resolved_root / validated_relative_path(raw_path)).resolve()
        if target != resolved_root and resolved_root not in target.parents:
            raise ValueError(f"directory escapes project root: {raw_path!r}")
        target.mkdir(parents=True, exist_ok=True)
        created.append(target)
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    paths = create_directories(args.root, args.manifest)
    print(f"verified {len(paths)} directories below {args.root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
