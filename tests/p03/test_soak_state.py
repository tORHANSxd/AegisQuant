"""A 24-hour acceptance claim cannot be synthesized from a short or incomplete run."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from aegisquant.data.providers.binance.contracts import Product
from aegisquant.data.providers.binance.models import SoakEvidence, SoakStreamEvidence


def stream(product: Product) -> SoakStreamEvidence:
    return SoakStreamEvidence(
        product=product,
        stream_url=(
            "wss://data-stream.binance.vision/ws/btcusdt@depth@1000ms"
            if product is Product.SPOT
            else "wss://fstream.binance.com/public/ws/btcusdt@depth@500ms"
        ),
        message_count=100,
        applied_count=100,
        duplicate_count=0,
        late_count=0,
        sequence_gap_count=1,
        recovery_count=1,
        snapshot_count=3,
        reconnect_count=2,
        forced_rollover_count=1,
        first_message_at=datetime(2026, 8, 31, tzinfo=UTC),
        last_message_at=datetime(2026, 9, 1, tzinfo=UTC),
        maximum_inter_message_ms=1000,
        hash_chain_sha256="1" * 64,
        witness_samples=(),
    )


def test_real_24_hour_evidence_can_claim_acceptance() -> None:
    started = datetime(2026, 8, 31, tzinfo=UTC)
    evidence = SoakEvidence(
        status="passed",
        qualifying_acceptance=True,
        test_mode=False,
        requested_duration_seconds=86_400,
        actual_monotonic_duration_seconds=86_401,
        actual_wall_duration_seconds=86_401,
        started_at_utc=started,
        finished_at_utc=started + timedelta(seconds=86_401),
        process_id=1,
        host_pause_detected=False,
        manual_outage_requested=True,
        manual_outage_recovered=True,
        unexplained_sequence_gap_count=0,
        errors=(),
        streams=(stream(Product.SPOT), stream(Product.USD_M)),
    )
    assert evidence.qualifying_acceptance is True


def test_short_or_test_mode_run_cannot_claim_24_hour_acceptance() -> None:
    started = datetime(2026, 8, 31, tzinfo=UTC)
    with pytest.raises(ValidationError, match="unsupported"):
        SoakEvidence(
            status="passed",
            qualifying_acceptance=True,
            test_mode=True,
            requested_duration_seconds=3,
            actual_monotonic_duration_seconds=3,
            actual_wall_duration_seconds=3,
            started_at_utc=started,
            finished_at_utc=started + timedelta(seconds=3),
            process_id=1,
            host_pause_detected=False,
            manual_outage_requested=True,
            manual_outage_recovered=True,
            unexplained_sequence_gap_count=0,
            errors=(),
            streams=(stream(Product.SPOT), stream(Product.USD_M)),
        )
