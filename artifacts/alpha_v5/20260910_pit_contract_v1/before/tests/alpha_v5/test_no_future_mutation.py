"""Future OHLCV/gaps cannot change earlier features, risk targets or actual orders."""

from datetime import timedelta
from decimal import Decimal

import numpy as np
import pytest

from aegisquant.domain.identifiers import BacktestEventId
from aegisquant.research.strategies.buffered_target import BufferPolicy, RiskResizePolicy
from aegisquant.research.strategies.cost_aware_trend import build_trend_features
from aegisquant.research.validation.cat_contract import CatAuditPolicy
from aegisquant.research.validation.cat_replay import replay_cat
from scripts.summarize_alpha_r4 import shadow_cost
from tests.integration.cat_helpers import ROOT, fixture


@pytest.mark.parametrize("mutation", ["price", "volume", "gap"])
def test_future_mutation_preserves_past_feature_targets_orders_and_fills(mutation: str):
    spec, original, _ = fixture()
    prototype = original[0]
    bars = tuple(
        prototype.model_copy(
            update={
                "event_id": BacktestEventId(f"r5-causal-{i}"),
                "event_time": prototype.event_time + timedelta(hours=4 * (i - 280)),
                "available_time": prototype.available_time + timedelta(hours=4 * (i - 280)),
                "open": Decimal(str(100 + 5 * np.sin(i / 10))),
                "close": Decimal(str(100 + 5 * np.sin(i / 10))),
                "high": Decimal(str(101 + 5 * np.sin(i / 10))),
                "low": Decimal(str(99 + 5 * np.sin(i / 10))),
            }
        )
        for i in range(340)
    )
    cutoff = bars[320].available_time
    mutated = tuple(
        b
        if b.available_time <= cutoff
        else b.model_copy(
            update={k: getattr(b, k) * 10 for k in ("open", "high", "low", "close")}
            if mutation == "price"
            else {"volume": b.volume * 100}
            if mutation == "volume"
            else {}
        )
        for i, b in enumerate(bars)
        if not (mutation == "gap" and i == 325)
    )
    features = [build_trend_features(source) for source in (bars, mutated)]
    np.testing.assert_array_equal(features[0].values[:321], features[1].values[:321])
    results = [
        replay_cat(
            root=ROOT,
            spec=spec,
            bars=tuple(b for b in source if b.event_time >= spec.start_time),
            features=f,
            feature_indices={t: i for i, t in enumerate(f.available_times)},
            trend_by_time=dict.fromkeys(f.available_times, True),
            forecasts={},
            level="A1",
            audit_policy=CatAuditPolicy(version="cat-audit-r2"),
            buffer_policy=BufferPolicy(),
            resize_policy=RiskResizePolicy(),
        )
        for source, f in zip((bars, mutated), features, strict=True)
    ]
    base, altered = (r[0] for r in results)
    assert len(base.orders) >= 2
    assert [o for o in base.orders if o.order.decision_time < cutoff] == [
        o for o in altered.orders if o.order.decision_time < cutoff
    ]
    assert [f for f in base.fills if f.event_time <= cutoff] == [
        f for f in altered.fills if f.event_time <= cutoff
    ]
    for rows in zip(results[0][1], results[1][1], strict=False):
        if rows[0]["time"] >= cutoff:
            break
        for key in ("target_quantity", "smoothed_risk_weight", "last_regular_review", "reason"):
            assert rows[0].get(key) == rows[1].get(key)
    one = sum((shadow_cost(f, Decimal("1")) for f in base.fills), Decimal("0"))
    two = sum((shadow_cost(f, Decimal("2")) for f in base.fills), Decimal("0"))
    assert two > one
    assert base.equity_curve[-1].equity - (two - one) < base.equity_curve[-1].equity
    if mutation == "gap":
        after_gap = next(row for row in results[1][1] if row["time"] == bars[326].available_time)
        assert after_gap["smoothed_risk_weight"] == after_gap["unsmoothed_risk_weight"]
