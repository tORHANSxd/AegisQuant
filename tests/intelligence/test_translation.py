from __future__ import annotations

from pathlib import Path

from aegisquant.intelligence.static_analysis.translation import (
    MigrationCandidateKind,
    run_all_translation_candidates,
    translation_records,
)


def test_three_crypto_rewrites_have_explicit_semantic_changes() -> None:
    records = translation_records()
    assert len(records) == 3
    assert {item.target_strategy_id for item in records} == {
        item.value for item in MigrationCandidateKind
    }
    assert all(item.source_code_reused is False for item in records)
    assert all(item.external_return_used_as_evidence is False for item in records)
    assert all(item.semantic_changes and item.required_rechecks for item in records)


def test_three_candidates_use_same_event_backtest_contract_and_replay(project_root: Path) -> None:
    first = run_all_translation_candidates(project_root)
    second = run_all_translation_candidates(project_root)
    assert first == second
    assert len(first) == 3
    assert {item.candidate for item in first} == set(MigrationCandidateKind)
    assert len({item.economic_event_hash for item in first}) == 3
    assert all(item.engine == "EVENT" for item in first)
    assert all(item.orders == 2 and item.fills == 2 for item in first)
    assert all(item.ledger_records > 0 for item in first)
    assert all(item.source_code_reused is False for item in first)
    assert all(item.source_return_used_as_evidence is False for item in first)
    assert all(item.alpha_or_profit_claim is False for item in first)
    assert all(item.live_trading_locked is True for item in first)
