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


@pytest.mark.parametrize(
    "mutation",
    [
        "membership_revision",
        "late_backfill",
        "future_listing",
        "liquidity_revision",
        "rule_revision",
        "cross_asset_listing",
        "cross_asset_liquidity",
    ],
)
def test_b2_future_information_preserves_decision_snapshot_bytes(mutation: str):
    from tests.alpha_v5.test_research_guards import (
        B2_TIME,
        pit_liquidity,
        pit_member,
        pit_rule,
        pit_snapshot,
    )

    known_later = B2_TIME + timedelta(days=1)
    base = pit_snapshot()
    members = [pit_member()]
    liquidity = [pit_liquidity()]
    rules = [pit_rule()]
    if mutation in {"membership_revision", "late_backfill"}:
        members.append(
            pit_member(
                kind="DELISTED",
                known=known_later,
                effective=B2_TIME - timedelta(days=10),
                revision=2 if mutation == "membership_revision" else 1,
            )
        )
    elif mutation in {"future_listing", "cross_asset_listing"}:
        members.append(
            pit_member(
                "future-uid",
                symbol="OTHERUSDT",
                kind="RELISTED",
                known=known_later,
                effective=known_later
                if mutation == "future_listing"
                else B2_TIME - timedelta(days=20),
            )
        )
    elif mutation == "liquidity_revision":
        liquidity.append(pit_liquidity(known=known_later, revision=2, quote="9000"))
    elif mutation == "rule_revision":
        rules.append(pit_rule(known=known_later, revision=2, trading=False))
    else:
        liquidity.append(pit_liquidity("unseen-cross-asset", known=known_later, quote="900000"))
    altered = pit_snapshot(members=members, liquidity=liquidity, rules=rules)
    assert altered.model_dump_json() == base.model_dump_json()


def test_b2_future_announced_event_is_part_of_the_known_prefix():
    from tests.alpha_v5.test_research_guards import B2_TIME, pit_member, pit_snapshot

    announced = pit_member(
        kind="DELISTED", effective=B2_TIME + timedelta(days=1), known=B2_TIME - timedelta(days=1)
    )
    revised_known = pit_member(
        kind="DELISTED", effective=B2_TIME + timedelta(days=2), known=B2_TIME - timedelta(days=1)
    )
    first = pit_snapshot(members=[pit_member(), announced])
    second = pit_snapshot(members=[pit_member(), revised_known])
    assert first.eligible_instrument_ids == second.eligible_instrument_ids == ("asset-uid-1",)
    assert first.snapshot_sha256 != second.snapshot_sha256
    assert first.known_future_event_ids == (announced.membership_id,)


def test_b2_future_mutation_and_input_reordering_are_cross_asset_stable():
    import random

    from tests.alpha_v5.test_research_guards import (
        B2_TIME,
        pit_liquidity,
        pit_member,
        pit_rule,
        pit_snapshot,
    )

    members = [
        pit_member(),
        pit_member("other-uid", symbol="OTHERUSDT"),
        pit_member("exited-uid", symbol="OLDUSDT", kind="DELISTED", effective=B2_TIME),
    ]
    liquidity = [pit_liquidity(), pit_liquidity("other-uid", quote="20")]
    rules = [pit_rule(), pit_rule("other-uid")]
    expected = pit_snapshot(members=members, liquidity=liquidity, rules=rules).model_dump_json()
    for seed in range(5):
        rng = random.Random(seed)  # noqa: S311 -- deterministic synthetic ordering only.
        for rows in (members, liquidity, rules):
            rng.shuffle(rows)
        actual = pit_snapshot(members=members, liquidity=liquidity, rules=rules)
        assert actual.model_dump_json() == expected
        assert any(row.instrument_uid == "exited-uid" for row in actual.decisions)


def test_b2_legacy_research_function_bodies_remain_frozen():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    relative = "scripts/run_alpha_v5_research.py"
    frozen = root / "artifacts/alpha_v5/20260908_research_churn_v3/implementation" / relative
    trees = [ast.parse(path.read_text(encoding="utf-8")) for path in (frozen, root / relative)]
    functions = [
        {
            node.name: ast.dump(node)
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name != "main"
        }
        for tree in trees
    ]
    assert functions[0] == functions[1]
