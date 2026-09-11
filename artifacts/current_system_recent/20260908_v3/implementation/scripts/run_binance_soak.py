"""Run the qualifying 24-hour Binance Spot/USD-M public depth-stream acceptance soak."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from aegisquant.data.providers.binance.contracts import (
    Product,
    RestEndpoint,
    StreamKind,
    build_ws_url,
)
from aegisquant.data.providers.binance.models import SoakEvidence, SoakStreamEvidence
from aegisquant.data.providers.binance.normalization import normalize_depth_delta
from aegisquant.data.providers.binance.orderbook import (
    ApplyDisposition,
    LocalOrderBook,
    OrderBookSnapshot,
)
from aegisquant.data.providers.binance.rest import BinancePublicRestClient, decode_json
from aegisquant.data.providers.binance.websocket import PublicStreamRunner


def utc_now() -> datetime:
    return datetime.now(UTC)


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        raise ValueError(f"{label} keys must be strings")
    return {cast(str, key): item for key, item in raw.items()}


def _levels(value: object, *, label: str) -> tuple[tuple[Decimal, Decimal], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    result: list[tuple[Decimal, Decimal]] = []
    for raw_level in cast(list[object], value):
        if not isinstance(raw_level, list):
            raise ValueError(f"{label} level must be an array")
        level = cast(list[object], raw_level)
        if len(level) != 2 or not all(isinstance(item, str) for item in level):
            raise ValueError(f"{label} level must contain decimal strings")
        result.append((Decimal(cast(str, level[0])), Decimal(cast(str, level[1]))))
    return tuple(result)


class DepthSoakCollector:
    def __init__(
        self,
        *,
        product: Product,
        symbol: str,
        maximum_connection_age_seconds: float,
        witness_interval_seconds: float,
    ) -> None:
        self.product = product
        self.symbol = symbol
        self.url = build_ws_url(product=product, kind=StreamKind.DEPTH, symbol=symbol)
        self.runner = PublicStreamRunner(
            url=self.url,
            maximum_connection_age_seconds=maximum_connection_age_seconds,
            message_timeout_seconds=120,
        )
        self.book = LocalOrderBook(product=product, symbol=symbol)
        self.message_count = 0
        self.applied_count = 0
        self.duplicate_count = 0
        self.late_count = 0
        self.sequence_gap_count = 0
        self.recovery_count = 0
        self.snapshot_count = 0
        self.first_message_at: datetime | None = None
        self.last_message_at: datetime | None = None
        self.maximum_inter_message_ms = 0
        self.hash_chain = "0" * 64
        self.witness_samples: list[dict[str, object]] = []
        self._last_witness_at: datetime | None = None
        self._witness_interval_seconds = witness_interval_seconds
        self._request_hash = hashlib.sha256(self.url.encode()).hexdigest()

    def _fetch_snapshot(self) -> tuple[OrderBookSnapshot, dict[str, object]]:
        endpoint = (
            RestEndpoint.SPOT_DEPTH if self.product is Product.SPOT else RestEndpoint.USDM_DEPTH
        )
        with BinancePublicRestClient(timeout_seconds=15, maximum_attempts=4) as client:
            response = client.get(endpoint, {"symbol": self.symbol, "limit": 1000})
        row = _mapping(decode_json(response), label="depth snapshot")
        last_update_id = row.get("lastUpdateId")
        if not isinstance(last_update_id, int) or isinstance(last_update_id, bool):
            raise ValueError("depth snapshot lastUpdateId must be an integer")
        snapshot = OrderBookSnapshot(
            product=self.product,
            symbol=self.symbol,
            last_update_id=last_update_id,
            bids=_levels(row.get("bids"), label="bids"),
            asks=_levels(row.get("asks"), label="asks"),
        )
        witness: dict[str, object] = {
            "kind": "rest_snapshot",
            "received_at_utc": response.received_at.isoformat().replace("+00:00", "Z"),
            "last_update_id": last_update_id,
            "content_bytes": len(response.content),
            "content_sha256": response.content_sha256,
        }
        return snapshot, witness

    async def on_connect(self, _connected_at: datetime) -> None:
        snapshot, witness = await asyncio.to_thread(self._fetch_snapshot)
        self.book.force_resnapshot()
        self.book.load_snapshot(snapshot)
        self.snapshot_count += 1
        if len(self.witness_samples) < 48:
            self.witness_samples.append(witness)

    async def on_message(self, payload: bytes, observed_at: datetime) -> None:
        decoded: object = json.loads(payload)
        event = normalize_depth_delta(
            decoded,
            product=self.product,
            symbol=self.symbol,
            observed_at=observed_at,
            request_hash=self._request_hash,
            source=self.url,
        )
        content_hash = hashlib.sha256(payload).digest()
        self.hash_chain = hashlib.sha256(bytes.fromhex(self.hash_chain) + content_hash).hexdigest()
        if self.first_message_at is None:
            self.first_message_at = observed_at
        if self.last_message_at is not None:
            inter_message_ms = int((observed_at - self.last_message_at).total_seconds() * 1000)
            self.maximum_inter_message_ms = max(self.maximum_inter_message_ms, inter_message_ms)
        self.last_message_at = observed_at
        self.message_count += 1
        if (
            self._last_witness_at is None
            or (observed_at - self._last_witness_at).total_seconds()
            >= self._witness_interval_seconds
        ) and len(self.witness_samples) < 48:
            self.witness_samples.append(
                {
                    "kind": "websocket_frame",
                    "received_at_utc": observed_at.isoformat().replace("+00:00", "Z"),
                    "first_update_id": event.first_update_id,
                    "final_update_id": event.final_update_id,
                    "content_bytes": len(payload),
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
            self._last_witness_at = observed_at
        result = self.book.apply(event)
        if result.disposition is ApplyDisposition.APPLIED:
            self.applied_count += 1
        elif result.disposition is ApplyDisposition.DUPLICATE:
            self.duplicate_count += 1
        elif result.disposition is ApplyDisposition.LATE:
            self.late_count += 1
        elif result.disposition is ApplyDisposition.GAP:
            self.sequence_gap_count += 1
            await self.on_connect(observed_at)
            self.recovery_count += 1
        elif result.disposition is ApplyDisposition.RECOVERY_REQUIRED:
            raise RuntimeError("order book remained in recovery-required state")

    def progress(self) -> dict[str, object]:
        health = self.runner.health(
            duplicate_count=self.duplicate_count,
            late_count=self.late_count,
            gap_count=self.sequence_gap_count,
        )
        return {
            "product": self.product,
            "stream_url": self.url,
            "message_count": self.message_count,
            "applied_count": self.applied_count,
            "duplicate_count": self.duplicate_count,
            "late_count": self.late_count,
            "sequence_gap_count": self.sequence_gap_count,
            "recovery_count": self.recovery_count,
            "snapshot_count": self.snapshot_count,
            "reconnect_count": health.reconnect_count,
            "forced_rollover_count": health.forced_rollover_count,
            "first_message_at": self.first_message_at,
            "last_message_at": self.last_message_at,
            "maximum_inter_message_ms": self.maximum_inter_message_ms,
            "hash_chain_sha256": self.hash_chain,
            "witness_samples": tuple(self.witness_samples),
        }

    def evidence(self) -> SoakStreamEvidence:
        return SoakStreamEvidence.model_validate(self.progress())


async def run_soak(
    *,
    duration_seconds: int,
    test_mode: bool,
    state_path: Path,
    evidence_path: Path,
    symbol: str,
) -> SoakEvidence:
    if duration_seconds < 1:
        raise ValueError("duration_seconds must be positive")
    if not test_mode and duration_seconds < 86_400:
        raise ValueError("qualifying soak must request at least 86400 seconds")
    maximum_age = max(1.0, duration_seconds / 2) if test_mode else 43_200.0
    witness_interval = max(0.2, duration_seconds / 4) if test_mode else 3600.0
    collectors = (
        DepthSoakCollector(
            product=Product.SPOT,
            symbol=symbol,
            maximum_connection_age_seconds=maximum_age,
            witness_interval_seconds=witness_interval,
        ),
        DepthSoakCollector(
            product=Product.USD_M,
            symbol=symbol,
            maximum_connection_age_seconds=maximum_age,
            witness_interval_seconds=witness_interval,
        ),
    )
    stop = asyncio.Event()
    started_at = utc_now()
    started_monotonic = time.monotonic()
    process_id = os.getpid()
    errors: list[str] = []
    host_pause_detected = False
    manual_outage_requested = False
    manual_outage_recovered = False
    outage_baseline: tuple[tuple[int, int], ...] = ()
    manual_outage_at = min(60.0, max(0.2, duration_seconds / 3))
    monitor_interval_seconds = 0.25 if test_mode else 5.0

    async def monitor() -> None:
        nonlocal host_pause_detected
        nonlocal manual_outage_requested
        nonlocal manual_outage_recovered
        nonlocal outage_baseline
        previous_wall = utc_now()
        while not stop.is_set():
            elapsed = time.monotonic() - started_monotonic
            now = utc_now()
            wall_step = (now - previous_wall).total_seconds()
            if wall_step > 20:
                host_pause_detected = True
            previous_wall = now
            if elapsed >= manual_outage_at and not manual_outage_requested:
                outage_baseline = tuple(
                    (collector.runner.health().reconnect_count, collector.snapshot_count)
                    for collector in collectors
                )
                for collector in collectors:
                    collector.runner.request_reconnect()
                manual_outage_requested = True
            if manual_outage_requested and outage_baseline:
                manual_outage_recovered = all(
                    collector.runner.health().reconnect_count > baseline_reconnect
                    and collector.snapshot_count > baseline_snapshots
                    for collector, (baseline_reconnect, baseline_snapshots) in zip(
                        collectors, outage_baseline, strict=True
                    )
                )
            progress = {
                "schema_version": "1.0.0",
                "phase": "P03",
                "status": "in_progress",
                "test_mode": test_mode,
                "process_id": process_id,
                "started_at_utc": started_at.isoformat().replace("+00:00", "Z"),
                "updated_at_utc": now.isoformat().replace("+00:00", "Z"),
                "requested_duration_seconds": duration_seconds,
                "elapsed_monotonic_seconds": elapsed,
                "host_pause_detected": host_pause_detected,
                "manual_outage_requested": manual_outage_requested,
                "manual_outage_recovered": manual_outage_recovered,
                "public_market_data_only": True,
                "authentication_used": False,
                "account_access_performed": False,
                "order_capability_present": False,
                "live_trading_locked": True,
                "streams": [
                    collector.evidence().model_dump(mode="json") for collector in collectors
                ],
            }
            atomic_json(state_path, progress)
            if elapsed >= duration_seconds:
                stop.set()
                return
            await asyncio.sleep(
                min(
                    monitor_interval_seconds,
                    max(0.05, duration_seconds - elapsed),
                )
            )

    stream_tasks = [
        asyncio.create_task(
            collector.runner.run(
                stop=stop,
                on_message=collector.on_message,
                on_connect=collector.on_connect,
            ),
            name=f"binance-{collector.product.value.casefold()}-depth",
        )
        for collector in collectors
    ]
    monitor_task = asyncio.create_task(monitor(), name="binance-soak-monitor")
    done, _pending = await asyncio.wait(
        {monitor_task, *stream_tasks}, return_when=asyncio.FIRST_COMPLETED
    )
    if monitor_task in done and monitor_task.cancelled():
        errors.append("monitor cancelled before duration")
        stop.set()
    elif monitor_task in done and monitor_task.exception() is not None:
        monitor_error = monitor_task.exception()
        errors.append(f"monitor: {type(monitor_error).__name__}: {monitor_error}")
        stop.set()
    elif monitor_task not in done:
        for task in done:
            if task.cancelled():
                errors.append(f"{task.get_name()} cancelled before duration")
            elif task.exception() is not None:
                error = task.exception()
                errors.append(f"{task.get_name()}: {type(error).__name__}: {error}")
            else:
                errors.append(f"{task.get_name()} ended before duration")
        stop.set()
        monitor_task.cancel()
    stream_results = await asyncio.gather(*stream_tasks, return_exceptions=True)
    for collector, result in zip(collectors, stream_results, strict=True):
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            errors.append(f"{collector.product.value}: {type(result).__name__}: {result}")
    if not monitor_task.done():
        monitor_task.cancel()
    await asyncio.gather(monitor_task, return_exceptions=True)
    finished_at = utc_now()
    monotonic_duration = time.monotonic() - started_monotonic
    wall_duration = (finished_at - started_at).total_seconds()
    stream_evidence = tuple(collector.evidence() for collector in collectors)
    unexplained_gaps = sum(
        max(0, stream.sequence_gap_count - stream.recovery_count) for stream in stream_evidence
    )
    qualifying = (
        not test_mode
        and duration_seconds >= 86_400
        and monotonic_duration >= 86_400
        and not host_pause_detected
        and manual_outage_recovered
        and unexplained_gaps == 0
        and not errors
        and all(stream.message_count > 0 for stream in stream_evidence)
        and all(stream.forced_rollover_count > 0 for stream in stream_evidence)
    )
    status = (
        "passed" if qualifying else ("test_only_passed" if test_mode and not errors else "failed")
    )
    evidence = SoakEvidence(
        status=status,
        qualifying_acceptance=qualifying,
        test_mode=test_mode,
        requested_duration_seconds=duration_seconds,
        actual_monotonic_duration_seconds=monotonic_duration,
        actual_wall_duration_seconds=wall_duration,
        started_at_utc=started_at,
        finished_at_utc=finished_at,
        process_id=process_id,
        public_market_data_only=True,
        authentication_used=False,
        account_access_performed=False,
        order_capability_present=False,
        live_trading_locked=True,
        host_pause_detected=host_pause_detected,
        manual_outage_requested=manual_outage_requested,
        manual_outage_recovered=manual_outage_recovered,
        unexplained_sequence_gap_count=unexplained_gaps,
        errors=tuple(dict.fromkeys(errors)),
        streams=stream_evidence,
    )
    serialized = evidence.model_dump(mode="json")
    atomic_json(state_path, serialized)
    atomic_json(evidence_path, serialized)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=86_400)
    parser.add_argument("--test-mode", action="store_true")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument(
        "--state",
        type=Path,
        default=Path(".runtime/p03-binance-soak/state.json"),
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("reports/data/BINANCE_24H_SOAK.json"),
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    evidence = asyncio.run(
        run_soak(
            duration_seconds=args.duration_seconds,
            test_mode=args.test_mode,
            state_path=root / args.state,
            evidence_path=root / args.evidence,
            symbol=args.symbol,
        )
    )
    print(evidence.model_dump_json())
    return 0 if evidence.status in {"passed", "test_only_passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
