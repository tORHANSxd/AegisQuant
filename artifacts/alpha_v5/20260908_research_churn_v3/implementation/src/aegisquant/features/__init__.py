"""Versioned point-in-time market and event features."""

from aegisquant.features.events import build_event_feature_vector, event_feature_definitions
from aegisquant.features.market import (
    MarketFeatureCalculator,
    MarketFeatureConfig,
    MarketObservation,
    assert_batch_incremental_parity,
    cross_sectional_rank,
    market_feature_definitions,
)
from aegisquant.features.models import (
    FeatureDefinition,
    FeatureDType,
    FeatureEntity,
    FeatureParameter,
    FeatureSetManifest,
    FeatureSnapshot,
    FeatureValueRecord,
    FeatureVector,
)
from aegisquant.features.registry import FeatureRegistry, values_by_key

__all__ = [
    "FeatureDType",
    "FeatureDefinition",
    "FeatureEntity",
    "FeatureParameter",
    "FeatureRegistry",
    "FeatureSetManifest",
    "FeatureSnapshot",
    "FeatureValueRecord",
    "FeatureVector",
    "MarketFeatureCalculator",
    "MarketFeatureConfig",
    "MarketObservation",
    "assert_batch_incremental_parity",
    "build_event_feature_vector",
    "cross_sectional_rank",
    "event_feature_definitions",
    "market_feature_definitions",
    "values_by_key",
]
