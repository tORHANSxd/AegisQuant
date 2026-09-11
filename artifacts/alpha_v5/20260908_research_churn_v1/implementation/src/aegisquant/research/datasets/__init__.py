"""Point-in-time universes and mandatory training manifests."""

from aegisquant.research.datasets.external import (
    ExternalBaselineManifest,
    ExternalBaselineRecord,
    register_external_baseline,
)
from aegisquant.research.datasets.manifests import (
    CostAssumptionManifest,
    DataQualityReport,
    DatasetManifest,
    LeakageAuditManifest,
    LeakageAuditState,
    SplitManifest,
    TrainingManifestBundle,
    UniverseManifest,
)
from aegisquant.research.datasets.universe import (
    PointInTimeUniverse,
    UniverseMembership,
    UniverseSnapshot,
    membership_id,
)

__all__ = [
    "CostAssumptionManifest",
    "DataQualityReport",
    "DatasetManifest",
    "ExternalBaselineManifest",
    "ExternalBaselineRecord",
    "LeakageAuditManifest",
    "LeakageAuditState",
    "PointInTimeUniverse",
    "SplitManifest",
    "TrainingManifestBundle",
    "UniverseManifest",
    "UniverseMembership",
    "UniverseSnapshot",
    "membership_id",
    "register_external_baseline",
]
