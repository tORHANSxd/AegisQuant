"""Shadow observations are hypothetical and type-level read only."""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from aegisquant.runtime.shadow import ReadOnlyAccountObservation, ShadowRuntime
from tests.p12_helpers import NOW, command
from tests.p13_helpers import market, prediction


def test_shadow_records_one_hypothetical_trace_without_fill_or_write() -> None:
    runtime = ShadowRuntime()
    trace = runtime.evaluate(prediction=prediction(), command=command(), market=market())
    replay = runtime.evaluate(prediction=prediction(), command=command(), market=market())
    assert replay == trace
    assert len(runtime.records) == 1
    assert trace.hypothetical is True
    assert trace.write_attempted is False
    assert trace.fill_price is None
    assert trace.filled_quantity.amount == 0
    assert runtime.write_capability is False


def test_shadow_runtime_exposes_no_order_write_method() -> None:
    forbidden = {"submit", "cancel", "amend", "place_order", "send_order"}
    public_methods = {
        name
        for name, _ in inspect.getmembers(ShadowRuntime, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert public_methods.isdisjoint(forbidden)


def test_shadow_rejects_account_observation_with_write_permission() -> None:
    with pytest.raises(ValidationError, match="MUST-BE-READ-ONLY"):
        ReadOnlyAccountObservation(
            snapshot_id="unsafe-shadow-snapshot",
            venue_id=command().command.venue_id,
            observed_at=NOW,
            balances=(),
            open_order_ids=(),
            write_permissions=True,
            credential_values_accessed=False,
        )
