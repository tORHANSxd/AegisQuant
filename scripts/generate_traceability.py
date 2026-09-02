"""Generate deterministic normative-requirement traceability from the frozen spec."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

SPEC_SHA256: Final = "1265a4feeb126bf9004685b80c0aa01d053fd983079b80d5c9063abefc382d1f"
KEYWORDS: Final = (
    "不可妥协",
    "没有例外",
    "无例外",
    "只允许",
    "不允许",
    "必须",
    "禁止",
    "不得",
    "应当",
    "只能",
    "不能",
    "不可",
)
KEYWORD_RE: Final = re.compile("|".join(map(re.escape, KEYWORDS)))
CLAUSE_BOUNDARY_RE: Final = re.compile(r"[；。！？]")


@dataclass(frozen=True, slots=True)
class Requirement:
    line_number: int
    occurrence: int
    keyword: str
    clause: str
    section: str
    owner_phase: str


PHASE_RANGES: Final = (
    (5898, 5960, "P00"),
    (5961, 6005, "P01"),
    (6006, 6055, "P02"),
    (6056, 6089, "P03"),
    (6090, 6144, "P04"),
    (6145, 6176, "P05"),
    (6177, 6209, "P06"),
    (6210, 6242, "P07"),
    (6243, 6280, "P08"),
    (6281, 6319, "P09"),
    (6320, 6361, "P10"),
    (6362, 6398, "P11"),
    (6399, 6438, "P12"),
    (6439, 6470, "P13"),
    (6471, 6503, "P14"),
    (6504, 6545, "P15"),
    (6546, 6578, "P16"),
    (6579, 6616, "P17"),
    (6617, 6663, "P18"),
)

ARTIFACT_BY_PHASE: Final = {
    "ALL": "state/REQUIREMENTS_TRACEABILITY.csv",
    "P00": "reports/phases/P00/",
    "P01": "src/aegisquant/domain/; schemas/",
    "P02": "src/aegisquant/data/; data/manifests/",
    "P03": "src/aegisquant/data/providers/binance/",
    "P04": "src/aegisquant/data/providers/; src/aegisquant/intelligence/collectors/",
    "P05": "src/aegisquant/accounting/",
    "P06": "src/aegisquant/backtest/",
    "P07": "src/aegisquant/features/; src/aegisquant/labels/; src/aegisquant/research/validation/",
    "P08": "src/aegisquant/research/; src/aegisquant/intelligence/",
    "P09": "src/aegisquant/intelligence/static_analysis/; knowledge/",
    "P10": "src/aegisquant/intelligence/world/; src/aegisquant/intelligence/collectors.py",
    "P11": "src/aegisquant/portfolio/; src/aegisquant/risk/",
    "P12": "src/aegisquant/execution/",
    "P13": "src/aegisquant/runtime/; docs/runbooks/; reports/runtime/",
    "P14": "src/aegisquant/readmodels/; src/aegisquant/api/; apps/web/",
    "P15": "src/aegisquant/readmodels/; src/aegisquant/api/; apps/web/",
    "P16": "src/aegisquant/observability/; infra/; reports/security/",
    "P17": "reports/data/provider_bakeoff/",
    "P18": "src/aegisquant/operations/live_readiness/; reports/live_readiness/",
}

TEST_BY_PHASE: Final = {
    "ALL": "tests/p00/test_traceability.py",
    "P00": "tests/p00/; tests/security/; tests/contract/",
    "P01": "tests/unit/; tests/property/; tests/contract/",
    "P02": "tests/unit/data/; tests/property/; tests/performance/",
    "P03": "tests/contract/binance/; tests/replay/",
    "P04": "tests/contract/providers/; tests/replay/intelligence/",
    "P05": "tests/p05/; tests/property/; tests/mutation/",
    "P06": "tests/p06/; tests/contract/; tests/property/; tests/performance/; tests/mutation/",
    "P07": "tests/unit/features/; tests/property/pit/; tests/research/",
    "P08": "tests/research/; tests/security/prompt_safety/",
    "P09": "tests/security/static_analysis/; tests/intelligence/",
    "P10": "tests/intelligence/world/; tests/contract/providers/; tests/p10/",
    "P11": "tests/risk/; tests/property/; tests/mutation/",
    "P12": "tests/execution/; tests/chaos/; tests/contract/exchanges/",
    "P13": "tests/runtime/; tests/replay/; tests/chaos/; tests/integration/; tests/performance/",
    "P14": "tests/contract/api/; apps/web/tests/",
    "P15": "tests/p15/; tests/contract/api/; tests/integration/; apps/web/tests/; apps/web/e2e/",
    "P16": "tests/security/; tests/chaos/; tests/integration/",
    "P17": "tests/research/provider_bakeoff/",
    "P18": "tests/operations/live_readiness/; tests/p18/; tests/chaos/",
}

REQUIREMENT_OVERRIDES: Final = {
    46: (
        "state/SPEC_INDEX.md; state/REQUIREMENTS_TRACEABILITY.csv",
        "tests/p00/test_traceability.py",
    ),
    47: ("state/PROJECT_PHASE_STATE.yaml", "tests/p00/test_phase_boundary.py"),
    48: ("reports/phases/P00/PLAN.md", "tests/p00/test_required_reports.py"),
    49: ("state/PROJECT_PHASE_STATE.yaml", "tests/p00/test_phase_boundary.py"),
    50: ("reports/phases/P00/ACCEPTANCE.md", "tests/p00/test_no_incomplete_implementation.py"),
    51: ("docs/adr/", "tests/p00/test_adr_inventory.py"),
    52: ("docs/adr/ADR-0001-runtime-and-version-policy.md", "tests/contract/"),
    53: ("state/PROJECT_PHASE_STATE.yaml", "tests/p00/test_phase_boundary.py"),
    117: ("SECURITY.md", "tests/security/test_secret_boundaries.py"),
    118: ("configs/exchanges/adapter_registry.json", "tests/security/test_live_lock.py"),
    122: ("src/aegisquant/bootstrap/live_lock.py", "tests/security/test_live_lock.py"),
    231: ("state/HOST_CAPABILITIES.json; reports/access/", "tests/p00/test_host_capabilities.py"),
    412: ("state/DEPENDENCY_MATRIX.json", "tests/contract/test_candidate_runtime.py"),
    508: ("uv.lock; pnpm-lock.yaml", "tests/p00/test_dependency_locks.py"),
    1642: ("reports/access/", "tests/p00/test_access_requests.py"),
    1651: ("reports/access/SECRET_SETUP_GUIDE.md", "tests/p00/test_access_requests.py"),
    5906: (".git; docs/governance/BRANCH_PROTECTION.md", "tests/p00/test_repository_baseline.py"),
    5907: ("docs/spec/AegisQuant_Master_Taskbook_v3_1.md", "tests/p00/test_spec_integrity.py"),
    5908: ("state/REQUIREMENTS_TRACEABILITY.csv", "tests/p00/test_traceability.py"),
    5909: ("state/DIRECTORY_MANIFEST.json", "tests/p00/test_directory_manifest.py"),
    5910: ("state/HOST_CAPABILITIES.json", "tests/p00/test_host_capabilities.py"),
    5911: (
        "docs/adr/ADR-0001-runtime-and-version-policy.md",
        "tests/contract/test_candidate_runtime.py",
    ),
    5912: ("pyproject.toml; uv.lock", "tests/p00/test_dependency_locks.py"),
    5913: ("apps/web/; pnpm-lock.yaml", "apps/web/tests/locked-page.test.tsx"),
    5914: ("pyproject.toml; apps/web/package.json", "scripts/ci.py"),
    5915: ("docs/adr/ADR-0002-event-engine-selection.md", "tests/contract/test_nautilus_replay.py"),
    5916: ("docs/adr/ADR-0002-event-engine-selection.md", "tests/p00/test_adr_inventory.py"),
    5917: ("state/DEPENDENCY_MATRIX.json; reports/security/", "scripts/security_scan.py"),
    5918: (
        "src/aegisquant/bootstrap/live_lock.py; configs/exchanges/adapter_registry.json",
        "tests/security/test_live_lock.py",
    ),
    5919: (
        "state/PROJECT_PHASE_STATE.yaml; reports/phases/P00/",
        "tests/p00/test_required_reports.py",
    ),
    5920: ("reports/access/", "tests/p00/test_access_requests.py"),
    5921: ("schemas/source_processing_policy.schema.json", "tests/contract/test_source_policy.py"),
    5922: ("knowledge/source_policies/", "tests/p00/test_intelligence_templates.py"),
    5923: (
        "reports/security/THREAT_MODEL_DRAFT.md; SECURITY.md",
        "tests/p00/test_ci_security_artifacts.py",
    ),
    5924: (".github/workflows/ci.yml; scripts/ci.py", "tests/p00/test_ci_security_artifacts.py"),
    5925: ("docs/adr/README.md; docs/CODING_STANDARDS.md", "tests/p00/test_adr_inventory.py"),
    5926: ("CODEX_BOOTSTRAP.md", "tests/p00/test_repository_baseline.py"),
    5927: ("reports/phases/P00/TEST_RESULTS.json", "scripts/ci.py"),
    5949: ("README.md", "scripts/ci.py"),
    5950: ("uv.lock; pnpm-lock.yaml", "tests/p00/test_dependency_locks.py"),
    5951: ("src/aegisquant/", "tests/security/test_import_side_effects.py"),
    5952: (
        "reports/security/SECURITY_SCAN_RESULTS.json",
        "tests/p00/test_ci_security_artifacts.py",
    ),
    5953: ("apps/web/app/page.tsx", "apps/web/e2e/locked-page.spec.ts"),
    5954: (
        "tests/contract/test_nautilus_replay.py",
        "reports/compatibility/NAUTILUS_COMPATIBILITY.json",
    ),
    5955: ("src/aegisquant/bootstrap/live_lock.py", "tests/security/test_live_lock.py"),
    5956: (
        "reports/phases/P00/; state/PROJECT_PHASE_STATE.yaml",
        "tests/p00/test_required_reports.py",
    ),
    5957: ("state/PROJECT_PHASE_STATE.yaml", "tests/p00/test_phase_boundary.py"),
    5969: (
        "src/aegisquant/domain/identifiers.py; src/aegisquant/domain/time.py; "
        "src/aegisquant/domain/values.py",
        "tests/unit/domain/; tests/property/test_domain_properties.py",
    ),
    5970: ("src/aegisquant/domain/entities.py", "tests/unit/domain/test_entities.py"),
    5971: (
        "src/aegisquant/domain/intelligence.py",
        "tests/unit/domain/test_intelligence.py; tests/contract/test_event_contracts.py",
    ),
    5972: ("src/aegisquant/domain/policy.py", "tests/unit/domain/test_policy.py"),
    5973: ("src/aegisquant/domain/execution.py", "tests/unit/domain/test_execution.py"),
    5974: ("src/aegisquant/domain/accounting.py", "tests/unit/domain/test_accounting.py"),
    5975: (
        "src/aegisquant/domain/serialization.py; schemas/events/",
        "tests/contract/test_event_contracts.py",
    ),
    5976: ("src/aegisquant/domain/errors.py", "tests/unit/domain/test_errors.py"),
    5977: ("src/aegisquant/config/; schemas/config/", "tests/contract/test_config_contract.py"),
    5978: (
        "src/aegisquant/persistence/; migrations/",
        "tests/integration/test_postgres_contract.py",
    ),
    5979: ("schemas/events/", "tests/contract/test_event_contracts.py"),
    5980: ("src/aegisquant/domain/", "tests/property/test_domain_properties.py"),
    5981: (
        "migrations/; docs/database_boundaries.md",
        "tests/integration/test_postgres_contract.py",
    ),
    5996: ("src/aegisquant/domain/", "tests/architecture/test_domain_boundaries.py"),
    5997: ("src/aegisquant/domain/time.py", "tests/architecture/test_domain_boundaries.py"),
    5998: ("src/aegisquant/domain/values.py", "tests/property/test_domain_properties.py"),
    5999: (
        "src/aegisquant/domain/serialization.py; schemas/events/",
        "tests/contract/test_event_contracts.py",
    ),
    6000: (
        "src/aegisquant/persistence/messaging.py",
        "tests/integration/test_postgres_contract.py",
    ),
    6001: ("migrations/", "tests/integration/test_postgres_contract.py"),
    6002: ("src/aegisquant/domain/", "tests/property/test_domain_properties.py"),
    6014: (
        "src/aegisquant/data/provider_registry.py; data/catalogs/provider_registry.yaml",
        "tests/unit/data/test_provider_registry.py",
    ),
    6015: (
        "src/aegisquant/data/lake.py; data/manifests/",
        "tests/unit/data/test_lake.py; tests/chaos/data/test_atomic_lake_write.py",
    ),
    6016: (
        "src/aegisquant/data/manifest.py; src/aegisquant/data/lineage.py",
        "tests/unit/data/test_manifest.py",
    ),
    6017: (
        "src/aegisquant/data/query.py; src/aegisquant/data/transforms.py",
        "tests/contract/test_columnar_stack.py",
    ),
    6018: (
        "src/aegisquant/data/quality.py; data/quarantine/",
        "tests/unit/data/test_quality.py",
    ),
    6019: (
        "src/aegisquant/data/models.py; src/aegisquant/data/pit.py",
        "tests/property/test_pit_properties.py",
    ),
    6020: (
        "src/aegisquant/data/archive.py",
        "tests/unit/data/test_archive.py",
    ),
    6021: (
        "src/aegisquant/data/pit.py; reports/data/PIT_LEAKAGE_TESTS.md",
        "tests/property/test_pit_properties.py",
    ),
    6022: (
        "src/aegisquant/data/scanner.py; reports/data/LOCAL_ASSET_INVENTORY.parquet",
        "tests/unit/data/test_scanner.py",
    ),
    6023: (
        "src/aegisquant/data/scanner.py",
        "tests/security/test_read_only_scanner.py",
    ),
    6024: (
        "src/aegisquant/data/catalog.py",
        "tests/unit/data/test_catalog.py",
    ),
    6025: (
        "src/aegisquant/data/provider_registry.py",
        "tests/unit/data/test_provider_registry.py",
    ),
    6026: (
        "src/aegisquant/data/cli.py; src/aegisquant/data/catalog.py",
        "tests/contract/test_data_cli.py",
    ),
    6027: (
        "scripts/run_data_benchmark.py; reports/data/DATA_LAKE_BENCHMARK.md",
        "tests/performance/test_data_foundation.py",
    ),
    6028: (
        "docs/data_storage_lifecycle.md",
        "tests/p02/test_required_artifacts.py",
    ),
    6032: (
        "src/aegisquant/data/scanner.py; reports/access/LOCAL_PATH_REQUESTS.md",
        "tests/security/test_read_only_scanner.py",
    ),
    6033: (
        "scripts/generate_p02_evidence.py; reports/data/LOCAL_ASSET_INVENTORY.md",
        "tests/p02/test_required_artifacts.py",
    ),
    6047: (
        "src/aegisquant/data/manifest.py",
        "tests/property/test_data_foundation_properties.py",
    ),
    6048: (
        "src/aegisquant/data/lake.py",
        "tests/chaos/data/test_atomic_lake_write.py",
    ),
    6049: (
        "src/aegisquant/data/archive.py",
        "tests/unit/data/test_archive.py",
    ),
    6050: (
        "src/aegisquant/data/pit.py",
        "tests/property/test_pit_properties.py",
    ),
    6051: (
        "src/aegisquant/data/quality.py",
        "tests/unit/data/test_quality.py",
    ),
    6052: (
        "reports/data/DATA_LAKE_BENCHMARK.md",
        "tests/performance/test_data_foundation.py",
    ),
    6865: ("state/SPEC_INDEX.md", "tests/p00/test_spec_integrity.py"),
    6867: ("state/PROJECT_PHASE_STATE.yaml", "tests/p00/test_phase_boundary.py"),
    6869: ("reports/phases/P00/", "tests/p00/test_required_reports.py"),
    6871: ("src/aegisquant/bootstrap/live_lock.py; SECURITY.md", "tests/security/"),
}


def phase_for_line(line_number: int) -> str:
    for start, end, phase in PHASE_RANGES:
        if start <= line_number <= end:
            return phase
    if line_number <= 216:
        return "P00" if line_number <= 145 else "ALL"
    if line_number <= 232:
        return "P00"
    if line_number <= 395:
        return "ALL"
    if line_number <= 576:
        return "P00"
    if line_number <= 768:
        return "P00"
    if line_number <= 1222:
        return "P01"
    if line_number <= 1672:
        return "P00|P02" if line_number >= 1640 else "P02"
    if line_number <= 1992:
        return "P09"
    if line_number <= 2194:
        return "P07"
    if line_number <= 2674:
        return "P04|P10" if line_number <= 2386 else "P10"
    if line_number <= 3033:
        return "P08"
    if line_number <= 3194:
        return "P07"
    if line_number <= 3297:
        return "P11"
    if line_number <= 3523:
        return "P06"
    if line_number <= 3680:
        return "P05"
    if line_number <= 3882:
        return "P11|P18" if line_number >= 3863 else "P11"
    if line_number <= 4139:
        return "P12"
    if line_number <= 4265:
        return "P13|P18"
    if line_number <= 5091:
        return "P14|P15"
    if line_number <= 5290:
        return "P16"
    if line_number <= 5449:
        return "P00|P16"
    if line_number <= 5554:
        return "P16"
    if line_number <= 5705:
        return "P01|P14|P16"
    if line_number <= 5849:
        return "ALL"
    if line_number <= 6710:
        return "P18"
    if line_number <= 6740:
        return "P00|P02"
    if line_number <= 6760:
        return "P09"
    if line_number <= 6778:
        return "P04|P10"
    if line_number <= 6786:
        return "P12"
    if line_number <= 6799:
        return "P17"
    if line_number <= 6814:
        return "P18"
    if line_number <= 6859:
        return "P18"
    if line_number <= 6881:
        return "P00"
    if line_number <= 6992:
        return "P00"
    return "ALL"


def clause_for_match(line: str, start: int, end: int) -> str:
    left = max((match.end() for match in CLAUSE_BOUNDARY_RE.finditer(line, 0, start)), default=0)
    boundary = CLAUSE_BOUNDARY_RE.search(line, end)
    right = boundary.start() if boundary else len(line)
    clause = line[left:right].strip(" \t-|`>*#0123456789.")
    return re.sub(r"\s+", " ", clause)


def requirements_from_lines(lines: Iterable[str]) -> list[Requirement]:
    requirements: list[Requirement] = []
    heading = "文档元数据"
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\r\n")
        if line.startswith("#"):
            heading = line.lstrip("# ").strip()
        for occurrence, match in enumerate(KEYWORD_RE.finditer(line), start=1):
            requirements.append(
                Requirement(
                    line_number=line_number,
                    occurrence=occurrence,
                    keyword=match.group(0),
                    clause=clause_for_match(line, match.start(), match.end()),
                    section=heading,
                    owner_phase=phase_for_line(line_number),
                )
            )
    return requirements


def primary_phase(owner_phase: str) -> str:
    return owner_phase.split("|")[0]


def artifact_and_test(requirement: Requirement) -> tuple[str, str]:
    override = REQUIREMENT_OVERRIDES.get(requirement.line_number)
    if override is not None:
        return override
    phase = primary_phase(requirement.owner_phase)
    return ARTIFACT_BY_PHASE[phase], TEST_BY_PHASE[phase]


def phase_status(owner_phase: str, statuses: Mapping[str, str]) -> str:
    """Return the status of the earliest owning phase."""
    phase = primary_phase(owner_phase)
    if phase == "ALL":
        return "active_global"
    return statuses.get(phase, "planned_future")


def render_csv(requirements: Iterable[Requirement], statuses: Mapping[str, str]) -> str:
    """Render the full deterministic matrix using normalized LF endings."""
    output_file = io.StringIO(newline="")
    writer = csv.writer(output_file, lineterminator="\n")
    writer.writerow(
        (
            "requirement_id",
            "spec_sha256",
            "source_section",
            "source_line",
            "normative_keyword",
            "requirement_text",
            "owner_phase",
            "implementation_artifact",
            "verification_type",
            "verification_artifact",
            "status",
            "notes",
        )
    )
    for requirement in requirements:
        artifact, test = artifact_and_test(requirement)
        status = phase_status(requirement.owner_phase, statuses)
        writer.writerow(
            (
                f"AQ-R{requirement.line_number:04d}-{requirement.occurrence:02d}",
                SPEC_SHA256,
                requirement.section,
                requirement.line_number,
                requirement.keyword,
                requirement.clause,
                requirement.owner_phase,
                artifact,
                "automated_or_review",
                test,
                status,
                "按规范原文关键词逐出现位置追踪",
            )
        )
    return output_file.getvalue()


def write_csv(
    requirements: Iterable[Requirement], output_path: Path, statuses: Mapping[str, str]
) -> None:
    """Write a rendered matrix to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_csv(requirements, statuses), encoding="utf-8", newline="")


def parse_phase_statuses(values: Iterable[str]) -> dict[str, str]:
    """Parse repeatable PHASE=STATUS command-line values."""
    statuses: dict[str, str] = {}
    allowed_statuses = {"planned", "verified"}
    for value in values:
        phase, separator, status = value.partition("=")
        if separator != "=" or not re.fullmatch(r"P(?:0[0-9]|1[0-8])", phase):
            raise ValueError(f"invalid phase status: {value}")
        if status not in allowed_statuses:
            raise ValueError(f"invalid phase status: {value}")
        statuses[phase] = status
    return statuses


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--spec",
        type=Path,
        default=Path("AegisQuant_v3.1_Multimodal_Event_Intelligence_Codex_Master_Taskbook.md"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("state/REQUIREMENTS_TRACEABILITY.csv"),
    )
    parser.add_argument(
        "--phase-status",
        action="append",
        default=[],
        metavar="PHASE=STATUS",
        help="repeatable phase status, for example P00=verified",
    )
    parser.add_argument(
        "--p00-status",
        choices=("planned", "verified"),
        help="deprecated compatibility alias for --phase-status P00=...",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    raw = args.spec.read_bytes()
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != SPEC_SHA256:
        raise SystemExit(f"spec hash mismatch: {actual_hash}")
    text = raw.decode("utf-8")
    requirements = requirements_from_lines(text.splitlines())
    try:
        statuses = parse_phase_statuses(args.phase_status)
    except ValueError as error:
        parser.error(str(error))
    if args.p00_status is not None:
        statuses["P00"] = args.p00_status
    statuses.setdefault("P00", "planned")
    rendered = render_csv(requirements, statuses)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit("traceability matrix is stale")
        print(f"verified {len(requirements)} requirements in {args.output}")
        return 0
    write_csv(requirements, args.output, statuses)
    print(f"wrote {len(requirements)} requirements to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
