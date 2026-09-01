"""Pinned NautilusTrader compatibility probe for P06."""

from aegisquant.backtest.nautilus_contract import verify_nautilus_contract


def test_pinned_nautilus_replay_is_deterministic_and_read_only() -> None:
    evidence = verify_nautilus_contract("1.231.0")

    assert evidence.package_version == "1.231.0"
    assert evidence.deterministic is True
    assert evidence.first_digest == evidence.second_digest
    assert evidence.stable_state["input_quote_count"] == 3
    assert evidence.stable_state["iterations"] == 3
    assert evidence.stable_state["total_events"] == 0
    assert evidence.stable_state["total_orders"] == 0
    assert evidence.authentication_used is False
    assert evidence.account_access_performed is False
    assert evidence.order_capability_used is False
