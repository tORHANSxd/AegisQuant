"""Minimal local-only P02 inventory and catalog CLI."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from aegisquant.data.catalog import DataCatalog
from aegisquant.data.models import LakeLayer
from aegisquant.data.query import DuckDbQueryLayer
from aegisquant.data.scanner import ReadOnlyAssetScanner
from aegisquant.domain.identifiers import ProviderId


def _inventory(args: argparse.Namespace) -> int:
    scanner = ReadOnlyAssetScanner()
    file_count, proposal_count = scanner.scan_to_parquet(
        root=args.root,
        root_label=args.root_label,
        output=args.output,
        proposals_output=args.proposals_output,
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "real_user_assets_scanned": bool(args.real_user_assets),
                "file_count": file_count,
                "proposal_count": proposal_count,
                "inventory": str(args.output.resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _catalog_list(args: argparse.Namespace) -> int:
    catalog = DataCatalog(lake_root=args.lake_root, index_path=args.catalog)
    entries = catalog.query(
        provider_id=ProviderId(args.provider) if args.provider else None,
        dataset_name=args.dataset,
        layer=LakeLayer(args.layer) if args.layer else None,
        schema_version=args.schema_version,
        manifest_hash=args.manifest_hash,
    )
    print(
        json.dumps(
            [entry.model_dump(mode="json") for entry in entries],
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _catalog_verify(args: argparse.Namespace) -> int:
    catalog = DataCatalog(lake_root=args.lake_root, index_path=args.catalog)
    manifest = catalog.verify_manifest(args.manifest)
    print(
        json.dumps(
            {
                "status": "verified",
                "dataset_id": str(manifest.dataset_id),
                "manifest_hash": manifest.manifest_hash(),
            },
            sort_keys=True,
        )
    )
    return 0


def _query_count(args: argparse.Namespace) -> int:
    layer = DuckDbQueryLayer(allowed_root=args.allowed_root)
    count = layer.count_rows(tuple(args.parquet))
    print(json.dumps({"status": "completed", "row_count": count}, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subcommands = root.add_subparsers(dest="command", required=True)

    inventory = subcommands.add_parser("inventory", help="scan one explicitly authorized root")
    inventory.add_argument("--root", type=Path, required=True)
    inventory.add_argument("--root-label", required=True)
    inventory.add_argument("--output", type=Path, required=True)
    inventory.add_argument("--proposals-output", type=Path, required=True)
    inventory.add_argument(
        "--real-user-assets",
        action="store_true",
        help="declare that the supplied root was explicitly authorized by the user",
    )
    inventory.set_defaults(handler=_inventory)

    catalog_list = subcommands.add_parser("catalog-list", help="query immutable catalog rows")
    catalog_list.add_argument("--lake-root", type=Path, required=True)
    catalog_list.add_argument("--catalog", type=Path, required=True)
    catalog_list.add_argument("--provider")
    catalog_list.add_argument("--dataset")
    catalog_list.add_argument("--layer", choices=tuple(layer.value for layer in LakeLayer))
    catalog_list.add_argument("--schema-version")
    catalog_list.add_argument("--manifest-hash")
    catalog_list.set_defaults(handler=_catalog_list)

    verify = subcommands.add_parser("catalog-verify", help="verify a manifest and its files")
    verify.add_argument("--lake-root", type=Path, required=True)
    verify.add_argument("--catalog", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.set_defaults(handler=_catalog_verify)

    count = subcommands.add_parser("query-count", help="count rows in local Parquet files")
    count.add_argument("--allowed-root", type=Path, required=True)
    count.add_argument("--parquet", type=Path, action="append", required=True)
    count.set_defaults(handler=_query_count)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    handler = args.handler
    if not callable(handler):
        raise RuntimeError("CLI handler is not callable")
    result = handler(args)
    if not isinstance(result, int):
        raise RuntimeError("CLI handler returned a non-integer status")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
