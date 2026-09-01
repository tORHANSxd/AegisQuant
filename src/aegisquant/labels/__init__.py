"""Tradable, cost-aware, point-in-time research labels."""

from aegisquant.labels.generators import (
    generate_event_impact_label,
    generate_execution_label,
    generate_return_labels,
    generate_return_path_label,
)
from aegisquant.labels.models import (
    CostAssumption,
    DirectionClass,
    EventImpactLabel,
    ExecutionLabel,
    LabelDefinition,
    LabelKind,
    LabelSetManifest,
    PricePathObservation,
    ReturnPathLabel,
)

__all__ = [
    "CostAssumption",
    "DirectionClass",
    "EventImpactLabel",
    "ExecutionLabel",
    "LabelDefinition",
    "LabelKind",
    "LabelSetManifest",
    "PricePathObservation",
    "ReturnPathLabel",
    "generate_event_impact_label",
    "generate_execution_label",
    "generate_return_labels",
    "generate_return_path_label",
]
