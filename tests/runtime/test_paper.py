"""Paper virtual fill, idempotency, and recovery contracts."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.domain.execution import TimeInForce, VenueOrderStatus
from aegisquant.execution.models import SubmitDisposition
from aegisquant.runtime.models import RuntimeMode
from aegisquant.runtime.paper import PaperCheckpoint, PaperEngine
from tests.p12_helpers import command, intent
from tests.p13_helpers import market, paper_policy


def test_paper_partial_fill_and_input_replays_are_idempotent() -> None:
    engine = PaperEngine(mode=RuntimeMode.PAPER, policy=paper_policy())
    first = engine.submit(command())
    replay = engine.submit(command())
    fills = engine.process(market())
    assert first.disposition is SubmitDisposition.ACCEPTED
    assert replay.disposition is SubmitDisposition.IDEMPOTENT_REPLAY
    assert engine.economic_order_count == 1
    assert len(fills) == 1
    assert fills[0].quantity.amount == Decimal("0.5")
    assert fills[0].fill_price.amount == Decimal("49999.998")
    assert engine.orders[0].status is VenueOrderStatus.PARTIALLY_FILLED
    assert engine.process(market()) == ()
    assert len(engine.fills) == 1


def test_paper_checkpoint_restores_every_deduplication_index() -> None:
    engine = PaperEngine(mode=RuntimeMode.PAPER, policy=paper_policy())
    engine.submit(command())
    engine.process(market())
    checkpoint = engine.checkpoint()
    restored = PaperEngine.restore(checkpoint, policy=paper_policy())
    assert restored.process(market()) == ()
    replay = restored.submit(command())
    assert replay.disposition is SubmitDisposition.IDEMPOTENT_REPLAY
    assert restored.economic_order_count == 1
    assert tuple(item.fill_id for item in restored.fills) == tuple(
        item.fill_id for item in engine.fills
    )


def test_paper_rejects_tampered_checkpoint() -> None:
    engine = PaperEngine(mode=RuntimeMode.PAPER, policy=paper_policy())
    engine.submit(command())
    with pytest.raises(ValidationError, match="CHECKPOINT-HASH-MISMATCH"):
        PaperCheckpoint(payload=engine.checkpoint().payload, payload_sha256="0" * 64)


def test_fill_or_kill_cancels_when_visible_liquidity_is_insufficient() -> None:
    source = intent().model_copy(update={"time_in_force": TimeInForce.FILL_OR_KILL})
    submit = command(source_intent=source)
    engine = PaperEngine(mode=RuntimeMode.PAPER, policy=paper_policy())
    engine.submit(submit)
    assert engine.process(market(ask_quantity=Decimal("1"))) == ()
    assert engine.orders[0].status is VenueOrderStatus.CANCELED


def test_paper_engine_refuses_shadow_mode() -> None:
    with pytest.raises(ValueError, match="only supports"):
        PaperEngine(mode=RuntimeMode.SHADOW, policy=paper_policy())
