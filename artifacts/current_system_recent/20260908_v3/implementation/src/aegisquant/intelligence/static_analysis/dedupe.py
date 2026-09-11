"""Seven-layer strategy fingerprinting and semantic duplicate clustering."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping, Sequence

from aegisquant.data.hashing import canonical_sha256
from aegisquant.intelligence.static_analysis.models import (
    DedupeFingerprint,
    DuplicateCluster,
    StrategyIR,
)
from aegisquant.intelligence.static_analysis.scanner import normalized_ast_sha256


def _rule_payload(items: Iterable[object]) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for item in items:
        expression = getattr(item, "expression", None)
        formula = getattr(item, "formula", None)
        status = getattr(item, "status", None)
        payload.append(
            {
                "expression": expression,
                "formula": formula,
                "status": getattr(status, "value", status),
                "lookback": getattr(item, "lookback", None),
                "availability_lag": getattr(item, "availability_lag", None),
            }
        )
    return payload


def strategy_ir_semantic_sha256(strategy_ir: StrategyIR) -> str:
    """Hash rules while excluding source names, evidence IDs, and catalog identity."""
    return canonical_sha256(
        {
            "universe_selection_time": strategy_ir.universe_selection_time,
            "universe": _rule_payload(strategy_ir.universe_eligibility_rules),
            "data_requirements": list(strategy_ir.data_requirements),
            "features": _rule_payload(strategy_ir.features),
            "signals": _rule_payload(strategy_ir.signals),
            "entries": _rule_payload(strategy_ir.entries),
            "exits": _rule_payload(strategy_ir.exits),
            "position_sizing": _rule_payload(strategy_ir.position_sizing),
            "rebalance": _rule_payload(strategy_ir.rebalance),
            "execution": _rule_payload(strategy_ir.execution_assumptions),
            "risk": _rule_payload(strategy_ir.risk_controls),
            "parameters": [
                {
                    "name": item.name,
                    "value": item.value,
                    "provenance": item.provenance.value,
                }
                for item in strategy_ir.parameters
            ],
            "known_unknowns": list(strategy_ir.known_unknowns),
        }
    )


def _series(values: Sequence[float | int | str]) -> tuple[str, ...]:
    output: list[str] = []
    for value in values:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("dedupe fingerprint series must be finite")
        output.append(format(number, ".12g"))
    return tuple(output)


def build_fingerprint(
    *,
    strategy_ir: StrategyIR,
    raw_source: bytes,
    notebook: bool = False,
    signal_series: Sequence[float | int | str],
    trade_holding_series: Sequence[float | int | str],
    factor_regime_series: Sequence[float | int | str],
    residual_alpha_series: Sequence[float | int | str],
) -> DedupeFingerprint:
    if (
        min(
            len(signal_series),
            len(trade_holding_series),
            len(factor_regime_series),
            len(residual_alpha_series),
        )
        < 3
    ):
        raise ValueError("dedupe behavioral fingerprints require at least three observations")
    return DedupeFingerprint(
        strategy_id=strategy_ir.strategy_id,
        content_sha256=hashlib.sha256(raw_source).hexdigest(),
        normalized_ast_sha256=normalized_ast_sha256(raw_source, notebook=notebook),
        strategy_ir_sha256=strategy_ir_semantic_sha256(strategy_ir),
        signal_fingerprint=_series(signal_series),
        trade_holding_fingerprint=_series(trade_holding_series),
        factor_regime_fingerprint=_series(factor_regime_series),
        residual_alpha_fingerprint=_series(residual_alpha_series),
    )


def _correlation(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    if len(left) != len(right) or len(left) < 3:
        return 0.0
    x = [float(value) for value in left]
    y = [float(value) for value in right]
    x_mean = sum(x) / len(x)
    y_mean = sum(y) / len(y)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y, strict=True))
    x_scale = math.sqrt(sum((value - x_mean) ** 2 for value in x))
    y_scale = math.sqrt(sum((value - y_mean) ** 2 for value in y))
    if x_scale == 0 or y_scale == 0:
        return 1.0 if x == y else 0.0
    return numerator / (x_scale * y_scale)


def _matching_layers(
    left: DedupeFingerprint, right: DedupeFingerprint, *, correlation_threshold: float
) -> tuple[str, ...]:
    layers: list[str] = []
    if left.content_sha256 == right.content_sha256:
        layers.append("content_hash")
    if left.normalized_ast_sha256 == right.normalized_ast_sha256:
        layers.append("normalized_ast")
    if left.strategy_ir_sha256 == right.strategy_ir_sha256:
        layers.append("strategy_ir")
    for name, first, second in (
        ("signal_correlation", left.signal_fingerprint, right.signal_fingerprint),
        ("trade_holding_overlap", left.trade_holding_fingerprint, right.trade_holding_fingerprint),
        ("factor_regime_exposure", left.factor_regime_fingerprint, right.factor_regime_fingerprint),
        ("residual_alpha", left.residual_alpha_fingerprint, right.residual_alpha_fingerprint),
    ):
        if abs(_correlation(first, second)) >= correlation_threshold:
            layers.append(name)
    return tuple(layers)


def cluster_duplicates(
    fingerprints: Iterable[DedupeFingerprint],
    *,
    correlation_threshold: float = 0.995,
) -> tuple[DuplicateCluster, ...]:
    values = tuple(sorted(fingerprints, key=lambda item: item.strategy_id))
    if not 0.9 <= correlation_threshold <= 1:
        raise ValueError("dedupe correlation threshold must be in [0.9, 1]")
    if len({item.strategy_id for item in values}) != len(values):
        raise ValueError("dedupe strategy IDs must be unique")
    parent = list(range(len(values)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    pair_layers: dict[tuple[int, int], tuple[str, ...]] = {}
    for left in range(len(values)):
        for right in range(left + 1, len(values)):
            layers = _matching_layers(
                values[left], values[right], correlation_threshold=correlation_threshold
            )
            pair_layers[(left, right)] = layers
            if layers:
                union(left, right)

    groups: dict[int, list[int]] = {}
    for index in range(len(values)):
        groups.setdefault(find(index), []).append(index)
    clusters: list[DuplicateCluster] = []
    for indices in groups.values():
        if len(indices) < 2:
            continue
        layers = {
            layer
            for left in indices
            for right in indices
            if left < right
            for layer in pair_layers[(left, right)]
        }
        strategy_ids = tuple(values[index].strategy_id for index in indices)
        clusters.append(
            DuplicateCluster(
                cluster_id=canonical_sha256({"strategy_ids": strategy_ids}),
                strategy_ids=strategy_ids,
                matching_layers=tuple(sorted(layers)),
            )
        )
    return tuple(sorted(clusters, key=lambda item: item.cluster_id))


def duplicate_membership(clusters: Iterable[DuplicateCluster]) -> Mapping[str, str]:
    return {
        strategy_id: cluster.cluster_id
        for cluster in clusters
        for strategy_id in cluster.strategy_ids
    }
