"""Generate bounded synthetic P02 data evidence and verify the committed evidence set."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

import psutil
import pyarrow as pa
import pyarrow.parquet as pq

from aegisquant.data.duckdb_security import secure_duckdb_connection
from aegisquant.data.scanner import ReadOnlyAssetScanner

PUBLIC_SAMPLE_COMMIT: Final = "09f3cdbde45302f0f0c689c950e465e98a9df960"
PUBLIC_SAMPLE_URL: Final = (
    "https://raw.githubusercontent.com/apache/parquet-testing/"
    f"{PUBLIC_SAMPLE_COMMIT}/data/alltypes_plain.parquet"
)
PUBLIC_SAMPLE_SHA256: Final = "12a618d20a59ee0967fef45e7ec1ff6d451e724838edc1bbeac780ca15e8fcc4"
PUBLIC_SAMPLE_GIT_BLOB_SHA1: Final = "a63f5dca7c3821909748f34752966a0d7e08d47f"
PUBLIC_SAMPLE_MAX_BYTES: Final = 1024 * 1024
SYNTHETIC_MTIME: Final = datetime(2026, 8, 31, 11, tzinfo=UTC).timestamp()


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True)
class RssSampler:
    """Sample process RSS every 10 ms while a bounded benchmark runs."""

    _stop: threading.Event = field(default_factory=threading.Event)
    _samples: list[int] = field(default_factory=lambda: list[int]())
    _thread: threading.Thread | None = None

    def __enter__(self) -> RssSampler:
        process = psutil.Process(os.getpid())

        def sample() -> None:
            self._samples.append(process.memory_info().rss)
            while not self._stop.wait(0.01):
                self._samples.append(process.memory_info().rss)

        self._thread = threading.Thread(target=sample, name="p02-rss-sampler", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    @property
    def peak_bytes(self) -> int:
        if not self._samples:
            raise RuntimeError("RSS sampler did not collect a sample")
        return max(self._samples)

    @property
    def baseline_bytes(self) -> int:
        if not self._samples:
            raise RuntimeError("RSS sampler did not collect a sample")
        return self._samples[0]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def create_synthetic_asset_tree(root: Path, file_count: int) -> None:
    if file_count < 1024:
        raise ValueError("synthetic inventory requires at least 1024 files")
    root.mkdir(parents=True)
    for index in range(file_count - 2):
        directory = root / f"bucket-{index % 64:02d}"
        directory.mkdir(exist_ok=True)
        prefix = "strategy_result" if index % 257 == 0 else "note"
        path = directory / f"{prefix}-{index:06d}.txt"
        path.write_text(f"deterministic synthetic text bucket={index % 32}\n", encoding="utf-8")
        os.utime(path, (SYNTHETIC_MTIME, SYNTHETIC_MTIME))
    csv_path = root / "events.csv"
    csv_path.write_text("event_id,value\nevent-1,10\nevent-2,20\n", encoding="utf-8")
    os.utime(csv_path, (SYNTHETIC_MTIME, SYNTHETIC_MTIME))
    code_path = root / "unknown_strategy.py"
    code_path.write_text(
        "raise RuntimeError('inventory scanner must never execute this file')\n",
        encoding="utf-8",
    )
    os.utime(code_path, (SYNTHETIC_MTIME, SYNTHETIC_MTIME))


def scan_synthetic_assets(*, source: Path, report_dir: Path, file_count: int) -> dict[str, object]:
    inventory = report_dir / "LOCAL_ASSET_INVENTORY.parquet"
    proposals = report_dir / "LOCAL_ASSET_IMPORT_PROPOSALS.jsonl"
    started = time.perf_counter()
    with RssSampler() as sampler:
        scanned, proposal_count = ReadOnlyAssetScanner().scan_to_parquet(
            root=source,
            root_label="p02_deterministic_synthetic_fixture",
            output=inventory,
            proposals_output=proposals,
            batch_size=256,
        )
    duration = time.perf_counter() - started
    if scanned != file_count or proposal_count != file_count:
        raise RuntimeError("synthetic inventory did not scan every generated file")
    inventory_metadata = pq.ParquetFile(inventory).metadata
    if inventory_metadata.num_rows != file_count:
        raise RuntimeError("inventory Parquet row count differs from scanned file count")
    return {
        "real_user_assets_scanned": False,
        "synthetic_file_count": scanned,
        "proposal_count": proposal_count,
        "duration_seconds": round(duration, 6),
        "files_per_second": round(scanned / max(duration, 0.000001), 3),
        "rss_baseline_bytes": sampler.baseline_bytes,
        "rss_peak_bytes": sampler.peak_bytes,
        "rss_peak_delta_bytes": max(0, sampler.peak_bytes - sampler.baseline_bytes),
        "inventory_size_bytes": inventory.stat().st_size,
        "inventory_sha256": sha256_file(inventory),
        "proposals_sha256": sha256_file(proposals),
        "source_fixture_retained": False,
        "source_execution_performed": False,
    }


def benchmark_columnar_lake(*, work_root: Path, row_count: int) -> dict[str, object]:
    if row_count < 1_000_000:
        raise ValueError("columnar benchmark requires at least 1,000,000 rows")
    path = work_root / "synthetic-columnar-benchmark.parquet"
    batch_size = 100_000
    schema = pa.schema(
        [
            ("event_id", pa.int64()),
            ("asset", pa.string()),
            ("event_time_us", pa.int64()),
            ("available_time_us", pa.int64()),
            ("value", pa.float64()),
            ("volume", pa.int64()),
        ]
    )
    rss_before = psutil.Process(os.getpid()).memory_info().rss
    write_started = time.perf_counter()
    with (
        RssSampler() as write_sampler,
        pq.ParquetWriter(
            path,
            schema,
            compression="zstd",
            version="2.6",
            use_dictionary=True,
            write_statistics=True,
        ) as writer,
    ):
        for start in range(0, row_count, batch_size):
            stop = min(start + batch_size, row_count)
            ids = list(range(start, stop))
            table = pa.table(
                {
                    "event_id": ids,
                    "asset": ["BTC-USDT"] * len(ids),
                    "event_time_us": [1_788_154_400_000_000 + value for value in ids],
                    "available_time_us": [1_788_154_400_010_000 + value for value in ids],
                    "value": [float(value % 10_000) / 100 for value in ids],
                    "volume": [value % 1_000 for value in ids],
                },
                schema=schema,
            )
            writer.write_table(table, row_group_size=batch_size)
    write_seconds = time.perf_counter() - write_started

    query_started = time.perf_counter()
    with RssSampler() as query_sampler:
        connection = secure_duckdb_connection(allowed_root=work_root)
        try:
            raw_result = (
                connection.read_parquet([path.as_posix()])
                .aggregate("count(*) AS row_count, sum(value) AS value_sum")
                .fetchone()
            )
        finally:
            connection.close()
    query_seconds = time.perf_counter() - query_started
    result = cast(tuple[object, ...] | None, raw_result)
    if result is None or result[0] != row_count:
        raise RuntimeError("DuckDB benchmark aggregate did not return every row")
    metadata = pq.ParquetFile(path).metadata
    compressed_bytes = path.stat().st_size
    throughput_bytes = compressed_bytes / max(query_seconds, 0.000001)
    return {
        "row_count": row_count,
        "batch_rows": batch_size,
        "row_group_count": metadata.num_row_groups,
        "compressed_size_bytes": compressed_bytes,
        "write_seconds": round(write_seconds, 6),
        "write_rows_per_second": round(row_count / max(write_seconds, 0.000001), 3),
        "aggregate_query_seconds": round(query_seconds, 6),
        "aggregate_rows_per_second": round(row_count / max(query_seconds, 0.000001), 3),
        "compressed_scan_mib_per_second": round(throughput_bytes / (1024 * 1024), 3),
        "value_sum": float(cast(float, result[1])),
        "rss_before_bytes": rss_before,
        "write_rss_peak_bytes": write_sampler.peak_bytes,
        "write_rss_peak_delta_bytes": max(0, write_sampler.peak_bytes - rss_before),
        "query_rss_peak_bytes": query_sampler.peak_bytes,
        "query_rss_peak_delta_bytes": max(0, query_sampler.peak_bytes - rss_before),
        "estimated_100_gib_scan_seconds": round((100 * 1024**3) / throughput_bytes, 3),
        "estimated_200_gib_scan_seconds": round((200 * 1024**3) / throughput_bytes, 3),
        "all_files_materialized_in_ram": False,
        "query_shape": "DuckDB Parquet aggregate with one projected numeric column",
        "benchmark_file_retained": False,
    }


def fetch_public_sample() -> dict[str, object]:
    # The URL is a fixed HTTPS host/path and the response has a one-MiB hard limit.
    request = urllib.request.Request(  # noqa: S310  # nosec B310
        PUBLIC_SAMPLE_URL,
        headers={"User-Agent": "AegisQuant-P02-contract"},
    )
    with urllib.request.urlopen(  # noqa: S310  # nosec B310
        request, timeout=30
    ) as response:
        raw = response.read(PUBLIC_SAMPLE_MAX_BYTES + 1)
    if len(raw) > PUBLIC_SAMPLE_MAX_BYTES:
        raise RuntimeError("public compatibility sample exceeded the bounded size limit")
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    git_blob_sha1 = hashlib.sha1(
        f"blob {len(raw)}\0".encode() + raw,
        usedforsecurity=False,
    ).hexdigest()
    if observed_sha256 != PUBLIC_SAMPLE_SHA256 or git_blob_sha1 != PUBLIC_SAMPLE_GIT_BLOB_SHA1:
        raise RuntimeError("public compatibility sample does not match the pinned identities")
    parquet_file = pq.ParquetFile(pa.BufferReader(raw))
    return {
        "provider_id": "apache_parquet_testing",
        "url": PUBLIC_SAMPLE_URL,
        "pinned_commit": PUBLIC_SAMPLE_COMMIT,
        "size_bytes": len(raw),
        "sha256": observed_sha256,
        "git_blob_sha1": git_blob_sha1,
        "row_count": parquet_file.metadata.num_rows,
        "row_group_count": parquet_file.metadata.num_row_groups,
        "arrow_schema": parquet_file.schema_arrow.to_string(),
        "processing_mode": "in_memory_metadata_only",
        "raw_bytes_retained": False,
        "credentials_used": False,
        "verified_at_utc": utc_now(),
    }


def run_pit_contracts(root: Path) -> dict[str, object]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/property/test_data_properties.py",
        "tests/p02/test_pit_query.py",
        "-q",
    ]
    started = time.perf_counter()
    # The local interpreter receives a fixed test command and no shell is used.
    result = subprocess.run(  # noqa: S603  # nosec B603
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = "\n".join((result.stdout, result.stderr)).strip()
    match = re.search(r"(\d+) passed", output)
    passed = int(match.group(1)) if match else 0
    if result.returncode != 0:
        raise RuntimeError(f"PIT contracts failed:\n{output[-4000:]}")
    return {
        "command": command[1:],
        "exit_code": result.returncode,
        "passed": passed,
        "duration_seconds": round(time.perf_counter() - started, 6),
        "status": "passed",
        "output_tail": output[-2000:],
    }


def write_markdown_reports(report_dir: Path, evidence: dict[str, object]) -> None:
    inventory = cast(dict[str, object], evidence["inventory"])
    benchmark = cast(dict[str, object], evidence["benchmark"])
    pit = cast(dict[str, object], evidence["pit_contracts"])
    public = cast(dict[str, object], evidence["public_sample"])
    inventory_md = f"""# Local Asset Inventory

- 真实用户资产扫描：`false`
- 输入：运行时创建并销毁的确定性合成目录；未使用任何用户路径
- 合成文件：{inventory["synthetic_file_count"]}
- Import proposals：{inventory["proposal_count"]}
- 扫描耗时：{inventory["duration_seconds"]} 秒
- 吞吐：{inventory["files_per_second"]} files/s
- RSS 采样峰值增量：{inventory["rss_peak_delta_bytes"]} bytes
- Inventory SHA-256：`{inventory["inventory_sha256"]}`
- 源文件执行、移动、修改、删除：`false`
- 合成源目录保留：`false`

未知脚本只产生 `REVIEW` 提案；没有执行、导入或复制。由于用户没有授权真实路径，
本报告不能也不会声称发现了任何真实策略、回测结果或历史行情资产。
"""
    (report_dir / "LOCAL_ASSET_INVENTORY.md").write_text(
        inventory_md, encoding="utf-8", newline="\n"
    )
    benchmark_md = f"""# Data Lake Benchmark

## 实测范围

- 行数：{benchmark["row_count"]}
- 分批：{benchmark["batch_rows"]} rows/batch
- Row groups：{benchmark["row_group_count"]}
- 压缩 Parquet：{benchmark["compressed_size_bytes"]} bytes
- 写入：{benchmark["write_seconds"]} 秒，{benchmark["write_rows_per_second"]} rows/s
- DuckDB 聚合：{benchmark["aggregate_query_seconds"]} 秒，{benchmark["aggregate_rows_per_second"]} rows/s
- 压缩字节吞吐：{benchmark["compressed_scan_mib_per_second"]} MiB/s
- 写入 RSS 采样峰值增量：{benchmark["write_rss_peak_delta_bytes"]} bytes
- 查询 RSS 采样峰值增量：{benchmark["query_rss_peak_delta_bytes"]} bytes
- 全文件装入 RAM：`false`

## 100/200 GiB 外推

- 100 GiB 单列顺序扫描估算：{benchmark["estimated_100_gib_scan_seconds"]} 秒
- 200 GiB 单列顺序扫描估算：{benchmark["estimated_200_gib_scan_seconds"]} 秒

外推按实测压缩字节吞吐线性计算，只是容量规划下界，不等于真实多列、并发或冷盘性能。
生产查询必须依赖日期/provider/dataset 分区裁剪、列裁剪和增量处理，禁止把 100/200 GiB
全部物化到 Python 内存。实测文件只存在于临时目录，完成后销毁。

## 生命周期与恢复建议

- 200 GiB 逻辑数据集预留至少 500 GiB 工作空间，覆盖不可变版本、compaction staging 与 20% 余量。
- Catalog、manifest、schema registry 和 tombstone 每次提交后做独立校验备份；数据文件按内容哈希去重备份。
- RAW/BRONZE 只追加；修订写新版本。删除先追加 tombstone，再按来源政策传播到派生数据和备份索引。
- 恢复顺序：schema registry → manifest/catalog → 内容哈希核验 → 派生层重建；不从 Gold 反推 Raw。
"""
    (report_dir / "DATA_LAKE_BENCHMARK.md").write_text(benchmark_md, encoding="utf-8", newline="\n")
    pit_md = f"""# PIT Leakage Tests

- 状态：`{pit["status"]}`
- 通过：{pit["passed"]}
- 命令：`{" ".join(cast(list[str], pit["command"]))}`
- 耗时：{pit["duration_seconds"]} 秒

覆盖 `event_time <= decision_time`、`available_time <= decision_time`、未来 revision、未来互动
快照、非法 SQL 标识符和 Hypothesis 随机可用时间。查询实现通过严格标识符 allow-list 和
DuckDB LATERAL latest-visible join 执行；任何未来可用事实只能返回空值，不能进入特征。
"""
    (report_dir / "PIT_LEAKAGE_TESTS.md").write_text(pit_md, encoding="utf-8", newline="\n")
    public_md = f"""# Public Parquet Compatibility Sample

- Provider：`{public["provider_id"]}`
- 固定 commit：`{public["pinned_commit"]}`
- SHA-256：`{public["sha256"]}`
- Git blob SHA-1：`{public["git_blob_sha1"]}`
- 大小：{public["size_bytes"]} bytes
- 行数：{public["row_count"]}
- 原始字节保留：`false`
- 凭据：`false`

样本仅在内存中打开并读取 Parquet metadata；仓库只保留来源、许可、固定版本和哈希证据。
"""
    (report_dir / "PUBLIC_PARQUET_SAMPLE.md").write_text(public_md, encoding="utf-8", newline="\n")


def generate(root: Path, *, file_count: int, row_count: int, public_sample: bool) -> None:
    report_dir = root / "reports/data"
    report_dir.mkdir(parents=True, exist_ok=True)
    public_path = report_dir / "PUBLIC_PARQUET_SAMPLE.json"
    if public_sample:
        public = fetch_public_sample()
        write_json(public_path, public)
    elif public_path.is_file():
        public = cast(dict[str, object], json.loads(public_path.read_text(encoding="utf-8")))
    else:
        raise RuntimeError("run once with --public-sample to create the pinned sample evidence")
    with tempfile.TemporaryDirectory(prefix="aegisquant-p02-") as temporary:
        temporary_root = Path(temporary)
        source = temporary_root / "synthetic-assets"
        create_synthetic_asset_tree(source, file_count)
        inventory = scan_synthetic_assets(
            source=source,
            report_dir=report_dir,
            file_count=file_count,
        )
        benchmark = benchmark_columnar_lake(work_root=temporary_root, row_count=row_count)
    pit_contracts = run_pit_contracts(root)
    disk = shutil.disk_usage(root)
    evidence: dict[str, object] = {
        "schema_version": "1.0.0",
        "phase": "P02",
        "generated_at_utc": utc_now(),
        "live_trading_locked": True,
        "real_user_assets_scanned": False,
        "real_account_access_performed": False,
        "plaintext_secrets_written": False,
        "inventory": inventory,
        "benchmark": benchmark,
        "public_sample": public,
        "pit_contracts": pit_contracts,
        "capacity_snapshot": {
            "workspace_volume_total_bytes": disk.total,
            "workspace_volume_free_bytes": disk.free,
            "recommended_200_gib_working_space_bytes": 500 * 1024**3,
        },
    }
    write_json(report_dir / "P02_DATA_EVIDENCE.json", evidence)
    write_markdown_reports(report_dir, evidence)
    print(
        f"P02 data evidence: {file_count} synthetic files, {row_count} rows, "
        f"{pit_contracts['passed']} PIT tests"
    )


def check(root: Path) -> None:
    report_dir = root / "reports/data"
    required = (
        "DATA_LAKE_BENCHMARK.md",
        "LOCAL_ASSET_INVENTORY.md",
        "LOCAL_ASSET_INVENTORY.parquet",
        "P02_DATA_EVIDENCE.json",
        "PIT_LEAKAGE_TESTS.md",
        "PUBLIC_PARQUET_SAMPLE.json",
        "PUBLIC_PARQUET_SAMPLE.md",
    )
    for name in required:
        path = report_dir / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"missing P02 data evidence: {name}")
    evidence = cast(
        dict[str, object],
        json.loads((report_dir / "P02_DATA_EVIDENCE.json").read_text(encoding="utf-8")),
    )
    inventory = cast(dict[str, object], evidence["inventory"])
    benchmark = cast(dict[str, object], evidence["benchmark"])
    public = cast(dict[str, object], evidence["public_sample"])
    pit = cast(dict[str, object], evidence["pit_contracts"])
    inventory_path = report_dir / "LOCAL_ASSET_INVENTORY.parquet"
    checks = (
        evidence.get("phase") == "P02",
        evidence.get("live_trading_locked") is True,
        evidence.get("real_user_assets_scanned") is False,
        int(cast(int, inventory["synthetic_file_count"])) >= 4096,
        inventory["inventory_sha256"] == sha256_file(inventory_path),
        pq.ParquetFile(inventory_path).metadata.num_rows == inventory["synthetic_file_count"],
        int(cast(int, benchmark["row_count"])) >= 1_000_000,
        benchmark["all_files_materialized_in_ram"] is False,
        float(cast(float, benchmark["estimated_100_gib_scan_seconds"])) > 0,
        float(cast(float, benchmark["estimated_200_gib_scan_seconds"])) > 0,
        public["pinned_commit"] == PUBLIC_SAMPLE_COMMIT,
        public["sha256"] == PUBLIC_SAMPLE_SHA256,
        public["raw_bytes_retained"] is False,
        pit["status"] == "passed",
        int(cast(int, pit["passed"])) > 0,
    )
    if not all(checks):
        raise RuntimeError("P02 data evidence failed its contract checks")
    print("P02 data evidence contract: passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--public-sample", action="store_true")
    parser.add_argument("--files", type=int, default=4096)
    parser.add_argument("--rows", type=int, default=1_000_000)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.check:
        check(root)
    else:
        generate(
            root,
            file_count=args.files,
            row_count=args.rows,
            public_sample=args.public_sample,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
