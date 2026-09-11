"""Verify only known development-data anomalies against official public daily archives."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from scripts.run_alpha_v4_audit import END, OUTPUT, ROOT, SOURCE, SYMBOLS, read_json
from scripts.run_alpha_v4_walkforward import write_json


def archive_millis(value: int, date: str) -> int:
    """Spot archives changed to microseconds in 2025; REST milliseconds are untouched."""
    if value <= 0:
        raise ValueError("invalid timestamp")
    return value // 1000 if date >= "2025-01-01" else value


def fetch_archive(job: tuple[str, str, Path]) -> dict[str, Any]:
    symbol, date, folder = job
    if symbol not in SYMBOLS or datetime.fromisoformat(date).replace(tzinfo=UTC) >= END:
        raise ValueError("archive verification outside registered development data")
    name = f"{symbol}-1h-{date}.zip"
    url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/1h/{name}"
    stamp = datetime.now(UTC).isoformat()
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read(2_000_001)
        with urllib.request.urlopen(url + ".CHECKSUM", timeout=30) as response:  # noqa: S310
            checksum = response.read(4096).decode("ascii")
        if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != checksum.split()[0]:
            raise ValueError("archive size or official checksum mismatch")
        (folder / name).write_bytes(raw)
        (folder / (name + ".CHECKSUM")).write_text(checksum, encoding="ascii")
        records: list[dict[str, Any]] = []
        with zipfile.ZipFile(io.BytesIO(raw)) as zipped:
            files = zipped.namelist()
            if len(files) != 1 or zipped.getinfo(files[0]).file_size > 2_000_000:
                raise ValueError("unexpected archive contents")
            # Parse the sole member in memory; never extract untrusted paths.
            for row in csv.reader(io.TextIOWrapper(zipped.open(files[0]), encoding="utf-8")):
                if row and row[0].isdigit():
                    records.append(
                        {
                            "open_time_ms": archive_millis(int(row[0]), date),
                            "close_time_ms": archive_millis(int(row[6]), date),
                            "volume": row[5],
                        }
                    )
        return {
            "symbol": symbol,
            "date": date,
            "url": url,
            "downloaded_at": stamp,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "checksum_verified": True,
            "unit": "microseconds" if date >= "2025-01-01" else "milliseconds",
            "records": records,
        }
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return {
            "symbol": symbol,
            "date": date,
            "url": url,
            "downloaded_at": stamp,
            "status": "UNAVAILABLE_NOT_FILLED",
            "error": str(exc),
        }


def main() -> None:
    output = OUTPUT / "data_quality"
    if output.exists():
        raise FileExistsError("public data audit already recorded")
    output.mkdir()
    archive = output / "official_archives"
    archive.mkdir()
    rows: list[dict[str, Any]] = []
    jobs: list[tuple[str, str, Path]] = []
    for source in read_json(SOURCE / "source_manifest.json")["datasets"]:
        with (ROOT / source["path"]).open(encoding="utf-8", newline="") as stream:
            data = [
                r
                for r in csv.DictReader(stream)
                if int(r["open_time_ms"]) < int(END.timestamp() * 1000)
            ]
        times = [int(r["open_time_ms"]) for r in data]
        observed = set(times)
        missing = sorted(set(range(times[0], times[-1] + 1, 3600000)) - observed)
        early = [
            int(r["open_time_ms"])
            for r in data
            if int(r["close_time_ms"]) != int(r["open_time_ms"]) + 3599999
        ]
        zeros = [int(r["open_time_ms"]) for r in data if float(r["base_volume"]) == 0]
        dates = sorted(
            {
                datetime.fromtimestamp(value / 1000, UTC).date().isoformat()
                for value in [*missing, *early, *zeros]
            }
        )
        jobs.extend((source["symbol"], date, archive) for date in dates)
        rows.append(
            {
                "symbol": source["symbol"],
                "rows": len(data),
                "duplicate_opens": len(times) - len(observed),
                "unordered_pairs": sum(b <= a for a, b in pairwise(times)),
                "missing_hours": len(missing),
                "missing_open_times_ms": missing,
                "early_close_open_times_ms": early,
                "zero_volume_times_ms": zeros,
                "input_sha256": source["sha256"],
                "rest_time_unit": "milliseconds",
                "cause": "UNVERIFIED_EXCHANGE_OUTAGE_OR_SOURCE_GAP; no invented suspension/delisting claim",
            }
        )
    with ThreadPoolExecutor(max_workers=4) as pool:
        downloaded = list(pool.map(fetch_archive, jobs))
    lookup = {(r["symbol"], r["date"]): r for r in downloaded}
    for row in rows:
        absent = present = unavailable = 0
        for time in row["missing_open_times_ms"]:
            date = datetime.fromtimestamp(time / 1000, UTC).date().isoformat()
            reference = lookup[row["symbol"], date]
            if "records" not in reference:
                unavailable += 1
            elif time in {r["open_time_ms"] for r in reference["records"]}:
                present += 1
            else:
                absent += 1
        row.update(
            {
                "missing_in_both_rest_and_archive": absent,
                "missing_rest_present_archive": present,
                "unverified_due_to_archive_unavailable": unavailable,
            }
        )
    write_json(
        output / "data_quality.json",
        {
            "version": "public-gap-audit-v1",
            "symbols": rows,
            "archive_responses": downloaded,
            "original_files_modified": False,
            "gaps_filled": False,
            "final_holdout_access_count": 0,
            "universe": {
                "status": "CONDITIONAL_FIXED_SURVIVORS",
                "listing_delisting_evidence": "INCOMPLETE",
                "future_eligibility_rule": "require dated listing, 240 complete 4h history bars and positive trailing 30d liquidity known before entry; missing listing/delisting provenance excludes asset from broad-universe claims",
            },
        },
    )
    print(
        json.dumps(
            {
                "symbols": len(rows),
                "archive_requests": len(jobs),
                "verified": sum(r.get("checksum_verified", False) for r in downloaded),
            }
        )
    )


if __name__ == "__main__":
    main()
