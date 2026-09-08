"""Run the bounded P06 vector/event throughput, memory and stability benchmark."""

from __future__ import annotations

import argparse
import gc
import platform
import time
import tracemalloc
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import psutil

from aegisquant.backtest.models import EngineKind
from aegisquant.backtest.vector import VectorBacktestEngine
from aegisquant.data.hashing import canonical_json_bytes
from aegisquant.domain.execution import OrderSide
from tests.p06.helpers import (
    NOW,
    bars,
    engine,
    order,
    policy,
    run_spec,
    spot_instrument,
    zero_cost_policy,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "reports/performance/P06_BACKTEST_BENCHMARK.json"
MIB = 1024 * 1024


def _timed_with_python_peak[T](function: Callable[[], T]) -> tuple[T, float, float]:
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    result = function()
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, elapsed, peak / MIB


def run_benchmark() -> dict[str, object]:
    selected = policy()
    benchmark = selected.benchmark
    event_count = benchmark.event_count
    vector_count = benchmark.vector_bars
    instrument = spot_instrument()
    event_engine = engine(zero_cost_policy())

    event_bars = bars(event_count)
    event_spec = run_spec(
        EngineKind.EVENT,
        run_id="p06-benchmark-event",
        end_time=NOW + timedelta(seconds=event_count + 1),
    )
    event_first, event_seconds, event_peak_mib = _timed_with_python_peak(
        lambda: event_engine.run(
            spec=event_spec,
            instrument=instrument,
            market_events=event_bars,
            orders=(),
        )
    )
    event_hashes = [event_first.economic_event_hash]
    for _ in range(benchmark.stability_replays - 1):
        event_hashes.append(
            event_engine.run(
                spec=event_spec,
                instrument=instrument,
                market_events=event_bars,
                orders=(),
            ).economic_event_hash
        )

    vector_bars = bars(vector_count)
    vector_spec = run_spec(
        EngineKind.VECTOR,
        run_id="p06-benchmark-vector",
        end_time=NOW + timedelta(seconds=vector_count + 1),
    )
    vector_order = order(sequence=1, side=OrderSide.BUY, quantity="1")
    vector_engine = VectorBacktestEngine(event_engine)
    vector_first, vector_seconds, vector_peak_mib = _timed_with_python_peak(
        lambda: vector_engine.run(
            spec=vector_spec,
            instrument=instrument,
            bars=vector_bars,
            orders=(vector_order,),
        )
    )
    vector_hashes = [vector_first.economic_event_hash]
    for _ in range(benchmark.stability_replays - 1):
        vector_hashes.append(
            vector_engine.run(
                spec=vector_spec,
                instrument=instrument,
                bars=vector_bars,
                orders=(vector_order,),
            ).economic_event_hash
        )

    maximum_peak = float(benchmark.maximum_peak_memory_mib)
    event_passed = (
        event_first.events_processed == event_count
        and event_seconds <= float(benchmark.maximum_event_seconds)
        and event_peak_mib <= maximum_peak
        and len(set(event_hashes)) == 1
    )
    vector_passed = (
        vector_seconds <= float(benchmark.maximum_vector_seconds)
        and vector_peak_mib <= maximum_peak
        and len(set(vector_hashes)) == 1
    )
    return {
        "schema_version": "p06-backtest-benchmark-v1",
        "seed": event_spec.seed,
        "event": {
            "input_event_count": event_count,
            "processed_event_count": event_first.events_processed,
            "seconds": event_seconds,
            "events_per_second": event_count / event_seconds,
            "python_peak_memory_mib": event_peak_mib,
            "maximum_seconds": str(benchmark.maximum_event_seconds),
            "passed": event_passed,
        },
        "vector": {
            "input_bar_count": vector_count,
            "seconds": vector_seconds,
            "bars_per_second": vector_count / vector_seconds,
            "python_peak_memory_mib": vector_peak_mib,
            "maximum_seconds": str(benchmark.maximum_vector_seconds),
            "passed": vector_passed,
        },
        "stability": {
            "replays": benchmark.stability_replays,
            "event_unique_hashes": len(set(event_hashes)),
            "vector_unique_hashes": len(set(vector_hashes)),
            "event_hash": event_hashes[0],
            "vector_hash": vector_hashes[0],
        },
        "memory_gate_mib": str(benchmark.maximum_peak_memory_mib),
        "process_rss_mib_after": psutil.Process().memory_info().rss / MIB,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "live_trading_locked": True,
        "real_account_connected": False,
        "passed": event_passed and vector_passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    evidence = run_benchmark()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_bytes(canonical_json_bytes(evidence))
    return 0 if evidence["passed"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
