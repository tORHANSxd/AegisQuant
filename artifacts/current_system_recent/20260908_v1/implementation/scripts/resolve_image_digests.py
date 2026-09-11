"""Resolve or validate immutable Docker Hub manifest-list digests for P16."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

IMAGES: Final = (
    ("prom/prometheus", "v3.14.0"),
    ("prom/alertmanager", "v0.34.0"),
    ("prom/node-exporter", "v1.12.1"),
    ("grafana/grafana", "13.2.0"),
    ("grafana/loki", "3.7.7"),
    ("grafana/alloy", "v1.19.2"),
    ("grafana/tempo", "2.10.5"),
    ("library/postgres", "18.6-bookworm"),
    ("library/nginx", "1.29.1-alpine"),
    ("library/python", "3.13.15-slim-bookworm"),
    ("library/node", "24.20.0-bookworm-slim"),
)
ACCEPT: Final = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


def _request_json(url: str) -> dict[str, object]:
    if not url.startswith("https://auth.docker.io/token?"):
        raise ValueError("only the Docker Hub HTTPS token endpoint is allowed")
    request = urllib.request.Request(  # noqa: S310 - fixed HTTPS registry endpoints
        url,
        headers={"User-Agent": "AegisQuant-P16-Digest-Lock/1.0"},
    )
    with urllib.request.urlopen(  # noqa: S310  # nosec B310
        request, timeout=20
    ) as response:
        return cast("dict[str, object]", json.loads(response.read()))


def resolve(repository: str, tag: str) -> dict[str, str]:
    if (repository, tag) not in IMAGES:
        raise ValueError("image reference is outside the pinned P16 allowlist")
    scope = urllib.parse.quote(f"repository:{repository}:pull", safe=":")
    token_payload = _request_json(
        f"https://auth.docker.io/token?service=registry.docker.io&scope={scope}"
    )
    token = token_payload.get("token")
    if not isinstance(token, str):
        raise RuntimeError(f"Docker Hub returned no pull token for {repository}")
    request = urllib.request.Request(
        f"https://registry-1.docker.io/v2/{repository}/manifests/{tag}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": ACCEPT,
            "User-Agent": "AegisQuant-P16-Digest-Lock/1.0",
        },
    )
    with urllib.request.urlopen(  # noqa: S310  # nosec B310
        request, timeout=30
    ) as response:
        body = response.read()
        digest = response.headers.get("Docker-Content-Digest")
        media_type = response.headers.get("Content-Type", "").split(";", maxsplit=1)[0]
    calculated = "sha256:" + hashlib.sha256(body).hexdigest()
    if digest != calculated:
        raise RuntimeError(f"registry digest mismatch for {repository}:{tag}")
    display = repository.removeprefix("library/")
    return {
        "image": display,
        "tag": tag,
        "digest": digest,
        "reference": f"{display}@{digest}",
        "media_type": media_type,
        "registry": "registry-1.docker.io",
    }


def validate(payload: dict[str, object]) -> bool:
    raw_images = payload.get("images")
    if not isinstance(raw_images, list):
        return False
    images = cast("list[object]", raw_images)
    if len(images) != len(IMAGES):
        return False
    expected = {(repo.removeprefix("library/"), tag) for repo, tag in IMAGES}
    found: set[tuple[str, str]] = set()
    for item in images:
        if not isinstance(item, dict):
            return False
        typed_item = cast("dict[str, object]", item)
        image = typed_item.get("image")
        tag = typed_item.get("tag")
        digest = typed_item.get("digest")
        reference = typed_item.get("reference")
        if not all(isinstance(value, str) for value in (image, tag, digest, reference)):
            return False
        typed_image = cast("str", image)
        typed_tag = cast("str", tag)
        typed_digest = cast("str", digest)
        typed_reference = cast("str", reference)
        if not typed_digest.startswith("sha256:") or len(typed_digest) != 71:
            return False
        if typed_reference != f"{typed_image}@{typed_digest}":
            return False
        found.add((typed_image, typed_tag))
    return found == expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "infra/compose/IMAGE_LOCK.json"
    if arguments.refresh:
        images = [resolve(repository, tag) for repository, tag in IMAGES]
        payload: dict[str, object] = {
            "schema_version": "aegisquant-image-lock-v1",
            "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source": "Docker Hub registry v2 manifest API",
            "images": images,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    if not output.is_file():
        raise SystemExit("image lock is missing; run with --refresh")
    payload = cast("dict[str, object]", json.loads(output.read_text(encoding="utf-8")))
    passed = validate(payload)
    print(f"P16 image lock: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
