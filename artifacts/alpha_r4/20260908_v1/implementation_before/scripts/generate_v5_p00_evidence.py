"""Generate or verify the deterministic V5-P00 evidence reset inventories."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Final, cast

from aegisquant.domain.evidence import EvidenceTier

ROOT: Final = Path(__file__).resolve().parents[1]
REPORT_ROOT: Final = ROOT / "reports"
V5_REPORT_ROOT: Final = REPORT_ROOT / "v5"
OUTPUT_ROOT: Final = V5_REPORT_ROOT / "P00"
AUDIT_PATH: Final = OUTPUT_ROOT / "FIXTURE_AUDIT.json"
MIGRATION_PATH: Final = OUTPUT_ROOT / "EVIDENCE_TIER_MIGRATION.json"
SPEC_PATH: Final = ROOT / "AegisQuant_v5.0_Truth_Causal_AI_Forecast_Codex_Master_Plan.md"
TEXT_SUFFIXES: Final = frozenset({".csv", ".json", ".jsonl", ".md", ".txt", ".yaml", ".yml"})
PLACEHOLDER_HASH_RE: Final = re.compile(r"(?<![0-9a-f])([0-9a-f])\1{63}(?![0-9a-f])", re.IGNORECASE)
SYNTHETIC_TRUE_RE: Final = re.compile(
    r'["\'](?:synthetic|synthetic_fixture)["\']\s*:\s*true', re.IGNORECASE
)


def sha256_file(path: Path) -> str:
    """Hash a file without loading binary artifacts into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def historical_report_paths() -> tuple[Path, ...]:
    """Return every pre-v5 report artifact in stable relative-path order."""

    return tuple(
        sorted(
            (
                path
                for path in REPORT_ROOT.rglob("*")
                if path.is_file() and V5_REPORT_ROOT not in path.parents
            ),
            key=lambda path: path.relative_to(ROOT).as_posix(),
        )
    )


def text_if_supported(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def classify(path: Path, text: str | None) -> tuple[EvidenceTier, tuple[str, ...]]:
    relative = path.relative_to(ROOT).as_posix().lower()
    if "synthetic" in relative or (text is not None and SYNTHETIC_TRUE_RE.search(text)):
        return EvidenceTier.SYNTHETIC, ("EXPLICIT_SYNTHETIC_EVIDENCE", "NO_ALPHA_PROMOTION")
    if "fixture" in relative or "golden" in relative:
        reasons = ["FIXTURE_OR_GOLDEN_ARTIFACT", "NO_ALPHA_PROMOTION"]
        if "reports/backtests/p06-golden/" in relative:
            reasons.extend(("UPSTREAM_PLACEHOLDER_HASHES", "EXTREME_SHORT_WINDOW"))
        return EvidenceTier.FIXTURE, tuple(reasons)
    return EvidenceTier.DEVELOPMENT, (
        "LEGACY_EVIDENCE_NOT_REQUALIFIED_BY_V5",
        "NO_ALPHA_PROMOTION",
    )


def parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def short_window_seconds(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        payload_object: object = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload_object, dict):
        return None
    payload = cast("dict[str, object]", payload_object)
    started = parse_datetime(payload.get("start_time"))
    finished = parse_datetime(payload.get("end_time"))
    if started is None or finished is None or finished < started:
        return None
    duration = (finished - started).total_seconds()
    return duration if duration < 60 else None


def build_payloads() -> tuple[dict[str, object], dict[str, object]]:
    entries: list[dict[str, object]] = []
    placeholder_findings: list[dict[str, object]] = []
    short_window_findings: list[dict[str, object]] = []
    tier_counts: Counter[str] = Counter()

    for path in historical_report_paths():
        relative = path.relative_to(ROOT).as_posix()
        text = text_if_supported(path)
        tier, reasons = classify(path, text)
        tier_counts[tier.value] += 1
        entries.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "evidence_tier": tier.value,
                "alpha_promotion_eligible": False,
                "reason_codes": list(reasons),
            }
        )
        if text is not None:
            placeholders = sorted(
                {match.group(0).lower() for match in PLACEHOLDER_HASH_RE.finditer(text)}
            )
            if placeholders:
                placeholder_findings.append(
                    {
                        "path": relative,
                        "placeholder_hashes": placeholders,
                        "disposition": "QUARANTINED_NO_ALPHA_PROMOTION",
                    }
                )
        duration = short_window_seconds(text)
        if duration is not None:
            short_window_findings.append(
                {
                    "path": relative,
                    "duration_seconds": duration,
                    "disposition": "FIXTURE_ONLY_NO_ALPHA_PROMOTION",
                }
            )

    spec_sha256 = sha256_file(SPEC_PATH)
    common = {
        "phase": "V5-P00",
        "spec_sha256": spec_sha256,
        "evidence_tier": EvidenceTier.DEVELOPMENT.value,
        "alpha_promotion_eligible": False,
        "live_trading_locked": True,
    }
    migration: dict[str, object] = {
        "schema_version": "v5-p00-evidence-tier-migration-v1",
        **common,
        "scope": "reports/** excluding reports/v5/**",
        "default_tier": EvidenceTier.DEVELOPMENT.value,
        "default_policy": "fail closed until a later v5 phase supplies qualifying evidence",
        "artifact_count": len(entries),
        "tier_counts": dict(sorted(tier_counts.items())),
        "promotion_eligible_count": 0,
        "all_historical_reports_classified": True,
        "artifacts": entries,
    }
    audit: dict[str, object] = {
        "schema_version": "v5-p00-fixture-audit-v1",
        **common,
        "scope": "reports/** excluding reports/v5/**",
        "historical_report_count": len(entries),
        "fixture_or_synthetic_count": tier_counts[EvidenceTier.FIXTURE.value]
        + tier_counts[EvidenceTier.SYNTHETIC.value],
        "placeholder_hash_finding_count": len(placeholder_findings),
        "short_window_finding_count": len(short_window_findings),
        "placeholder_hash_findings": placeholder_findings,
        "short_window_findings": short_window_findings,
        "dashboard_disposition": "P06_GOLDEN_FIXTURE_DISCLOSED_AND_NOT_PROMOTABLE",
        "hard_isolation_status": "ENFORCED_BY_TIER_AND_ALPHA_PROMOTION_FLAG",
    }
    return audit, migration


def rendered(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def write_or_check(path: Path, payload: dict[str, object], *, check: bool) -> None:
    expected = rendered(payload)
    if check:
        if not path.is_file() or path.read_text(encoding="utf-8") != expected:
            raise RuntimeError(f"V5-P00 evidence is stale: {path.relative_to(ROOT).as_posix()}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(expected, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    audit, migration = build_payloads()
    write_or_check(AUDIT_PATH, audit, check=args.check)
    write_or_check(MIGRATION_PATH, migration, check=args.check)
    action = "verified" if args.check else "wrote"
    print(f"{action} V5-P00 evidence reset for {migration['artifact_count']} historical reports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
