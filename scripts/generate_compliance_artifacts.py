"""Generate phase-bound CycloneDX inventories and dependency license evidence."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess  # nosec B404
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import quote


def python_inventory() -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Inventory the active Python environment using installed package metadata."""
    components: list[dict[str, object]] = []
    licenses: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name", "unknown")
        version = distribution.version
        identity = (name.casefold(), version)
        if identity in seen:
            continue
        seen.add(identity)
        license_expression = distribution.metadata.get("License-Expression")
        license_text = license_expression or distribution.metadata.get("License") or "UNKNOWN"
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{quote(name.casefold())}@{quote(version)}",
            }
        )
        licenses.append({"name": name, "version": version, "license": license_text})
    components.sort(key=lambda item: (str(item["name"]).casefold(), str(item["version"])))
    licenses.sort(key=lambda item: (item["name"].casefold(), item["version"]))
    return components, licenses


def collect_javascript_components(payload: object) -> list[dict[str, object]]:
    """Flatten pnpm's dependency graph into unique CycloneDX components."""
    found: dict[tuple[str, str], dict[str, object]] = {}

    def visit(name: str, node: object) -> None:
        if not isinstance(node, dict):
            return
        typed_node = cast("dict[object, object]", node)
        version = typed_node.get("version")
        if isinstance(version, str):
            found[(name, version)] = {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:npm/{quote(name, safe='@')}@{quote(version)}",
            }
        for dependency_key in ("dependencies", "devDependencies", "optionalDependencies"):
            dependencies = typed_node.get(dependency_key)
            if isinstance(dependencies, dict):
                typed_dependencies = cast("dict[object, object]", dependencies)
                for child_name, child in typed_dependencies.items():
                    visit(str(child_name), child)

    roots: list[object] = cast("list[object]", payload) if isinstance(payload, list) else [payload]
    for root in roots:
        if isinstance(root, dict):
            typed_root = cast("dict[object, object]", root)
            root_name = str(typed_root.get("name", "aegisquant"))
            visit(root_name, cast("dict[object, object]", root))
    return [found[key] for key in sorted(found, key=lambda item: (item[0].casefold(), item[1]))]


def cyclonedx(component: dict[str, str], components: list[dict[str, object]]) -> dict[str, object]:
    """Build a standards-shaped CycloneDX 1.6 document."""
    return {
        "$schema": "https://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "component": component,
        },
        "components": components,
    }


def pnpm_json(pnpm: str, root: Path, *arguments: str) -> object:
    """Run pnpm inventory command and parse its JSON response."""
    # pnpm is resolved before use and receives fixed arguments.
    result = subprocess.run(  # noqa: S603  # nosec B603
        [pnpm, *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-4000:] or result.stdout[-4000:])
    return cast("object", json.loads(result.stdout))


def python_license_inventory(root: Path) -> list[dict[str, object]]:
    """Use pip-licenses to normalize legacy and SPDX license metadata."""
    # The current interpreter receives fixed module arguments.
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "piplicenses", "--format=json", "--with-urls"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-4000:] or result.stdout[-4000:])
    payload: object = json.loads(result.stdout)
    if not isinstance(payload, list):
        raise TypeError("pip-licenses did not return a list")
    items = cast("list[object]", payload)
    return [cast("dict[str, object]", item) for item in items if isinstance(item, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=(
            "P03",
            "P04",
            "P05",
            "P06",
            "P07",
            "P08",
            "P09",
            "P10",
            "P11",
            "P12",
            "P13",
            "P14",
            "P15",
            "P16",
        ),
        default="P16",
    )
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    node = root / ".tools/node-v24.20.0-win-x64/node.exe"
    pnpm_entry = root / ".tools/pnpm/node_modules/pnpm/bin/pnpm.cjs"
    if not node.is_file() or not pnpm_entry.is_file():
        raise SystemExit("repository-pinned Node/pnpm toolchain is required")
    pnpm = str(node)
    pnpm_prefix = (str(pnpm_entry),)
    sbom_dir = root / "reports/sbom"
    license_dir = root / "reports/licenses"
    sbom_dir.mkdir(parents=True, exist_ok=True)
    license_dir.mkdir(parents=True, exist_ok=True)

    python_components, _ = python_inventory()
    python_licenses = python_license_inventory(root)
    javascript_tree = pnpm_json(pnpm, root, *pnpm_prefix, "list", "--json", "--depth", "Infinity")
    javascript_components = collect_javascript_components(javascript_tree)
    javascript_licenses = pnpm_json(
        pnpm, root, *pnpm_prefix, "licenses", "list", "--json", "--long"
    )

    python_bom = cyclonedx(
        {"type": "application", "name": "aegisquant-python", "version": "3.1.0.dev0"},
        python_components,
    )
    javascript_bom = cyclonedx(
        {"type": "application", "name": "aegisquant-web", "version": "3.1.0-dev.0"},
        javascript_components,
    )
    (sbom_dir / "python.cdx.json").write_text(
        json.dumps(python_bom, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (sbom_dir / "javascript.cdx.json").write_text(
        json.dumps(javascript_bom, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (license_dir / "python.json").write_text(
        json.dumps(python_licenses, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (license_dir / "javascript.json").write_text(
        json.dumps(javascript_licenses, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    summary = {
        "schema_version": "1.0.0",
        "phase": arguments.phase,
        "status": "passed",
        "python_component_count": len(python_components),
        "javascript_component_count": len(javascript_components),
        "python_unknown_license_count": sum(
            item.get("License") == "UNKNOWN" for item in python_licenses
        ),
        "artifacts": [
            "reports/sbom/python.cdx.json",
            "reports/sbom/javascript.cdx.json",
            "reports/licenses/python.json",
            "reports/licenses/javascript.json",
        ],
    }
    (license_dir / "COMPLIANCE_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
