"""Static architecture blockers for the pure P01 domain package."""

import ast
from pathlib import Path

PROHIBITED_IMPORT_PREFIXES = (
    "alembic",
    "fastapi",
    "nautilus_trader",
    "psycopg",
    "sqlalchemy",
)


def domain_files() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    return sorted((root / "src/aegisquant/domain").glob("*.py"))


def test_domain_has_no_framework_database_or_exchange_sdk_imports() -> None:
    violations: list[str] = []
    for path in domain_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
                line_number = node.lineno
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names = [node.module]
                line_number = node.lineno
            else:
                line_number = 0
            for name in names:
                if name.startswith(PROHIBITED_IMPORT_PREFIXES):
                    violations.append(f"{path.name}:{line_number}:{name}")
    assert violations == []


def test_domain_has_no_naive_datetime_or_builtin_round_calls() -> None:
    violations: list[str] = []
    for path in domain_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in {"datetime", "round"}:
                violations.append(f"{path.name}:{node.lineno}:{node.func.id}")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "utcnow":
                violations.append(f"{path.name}:{node.lineno}:utcnow")
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "now"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "datetime"
                and not node.args
            ):
                violations.append(f"{path.name}:{node.lineno}:datetime.now-without-timezone")
    assert violations == []


def test_domain_models_are_real_contracts_not_empty_placeholders() -> None:
    required_classes = {
        "Account",
        "AlphaSignal",
        "Asset",
        "ClaimRecord",
        "EventCluster",
        "EventImpactForecast",
        "Fill",
        "ForecastBundle",
        "Instrument",
        "JournalEntry",
        "MarketEvent",
        "NarrativeState",
        "OrderCommand",
        "OrderIntent",
        "PortfolioProposal",
        "PositionLot",
        "RawContentEnvelope",
        "RiskDecision",
        "SourceIdentity",
        "SourceProcessingPolicy",
        "Venue",
        "VenueOrder",
    }
    observed: set[str] = set()
    for path in domain_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        observed.update(node.name for node in tree.body if isinstance(node, ast.ClassDef))
    assert required_classes <= observed
