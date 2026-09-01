from __future__ import annotations

from pathlib import Path

from aegisquant.intelligence.static_analysis.dedupe import build_fingerprint, cluster_duplicates
from tests.intelligence.helpers import extract_fixture


def test_copy_and_rename_cluster_across_ast_ir_and_behavior(project_root: Path) -> None:
    path = project_root / "tests/fixtures/p09/joinquant_manual_export/code/strategy.py"
    raw = path.read_bytes()
    first_ir = extract_fixture(path, strategy_id="original-name").strategy_ir
    second_ir = first_ir.model_copy(update={"strategy_id": "renamed-copy"})
    behavior = (0, 1, 1, 0, -1, -1, 0, 1)
    first = build_fingerprint(
        strategy_ir=first_ir,
        raw_source=raw,
        signal_series=behavior,
        trade_holding_series=behavior,
        factor_regime_series=(1, 1, 0, 0, -1, -1, 0, 1),
        residual_alpha_series=(0, 1, 2, 1, 0, -1, -2, -1),
    )
    second = build_fingerprint(
        strategy_ir=second_ir,
        raw_source=raw,
        signal_series=behavior,
        trade_holding_series=behavior,
        factor_regime_series=(1, 1, 0, 0, -1, -1, 0, 1),
        residual_alpha_series=(0, 1, 2, 1, 0, -1, -2, -1),
    )
    clusters = cluster_duplicates((first, second))
    assert len(clusters) == 1
    assert clusters[0].strategy_ids == ("original-name", "renamed-copy")
    assert set(clusters[0].matching_layers) == {
        "content_hash",
        "normalized_ast",
        "strategy_ir",
        "signal_correlation",
        "trade_holding_overlap",
        "factor_regime_exposure",
        "residual_alpha",
    }
    assert clusters[0].independent_alpha_count == 1
