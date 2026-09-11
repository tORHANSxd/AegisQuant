"""Strict read-only evidence contracts and report assembly; no strategy execution entry."""

from __future__ import annotations

import ast
import csv
import difflib
import importlib.util
import json
import math
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from types import FrameType
from typing import Any, cast

import polars as pl
import yaml

from aegisquant.data.hashing import canonical_sha256, safe_relative_path, sha256_file
from aegisquant.research.experiments.journal import ExperimentEventJournal
from aegisquant.research.validation.experiment_registry import registered_run

Row = Mapping[str, Any]
ZERO = Decimal(0)
ONE = Decimal(1)
# Saved portfolio/report columns are binary64, not original Decimal ledger entries.
# At < 1e6 USDT, 1e-8 covers serialization and five-sleeve summation error.
# Original string-valued cost components retain a separate 1e-18 USDT tolerance.
MONEY_TOLERANCE = Decimal("1e-8")
RETURN_TOLERANCE = Decimal("1e-10")
LEDGER_TOLERANCE = Decimal("1e-18")
COMPARISONS = (
    "G1-G0",
    "G1-F0",
    "G1-F5",
    "G1-G1_PASSIVE",
    "G1-CASH",
    "G1_H3-G0",
    "G1_H10-G0",
    "G1_R24-G0",
    "G1_R72-G0",
)


class EvidenceStatus(StrEnum):
    VERIFIED = "VERIFIED"
    DERIVED_ONLY = "DERIVED_ONLY"
    HASH_ONLY = "HASH_ONLY"
    NOT_RECEIVED = "NOT_RECEIVED"
    NOT_COLLECTED = "NOT_COLLECTED"
    NOT_VERIFIED = "NOT_VERIFIED"
    CONFLICT = "CONFLICT"


class CostMode(StrEnum):
    REDECIDE_FUNDED = "REDECIDE_FUNDED"
    FROZEN_ORDERS_FUNDED = "FROZEN_ORDERS_FUNDED"
    SAME_FILL_SHADOW = "SAME_FILL_SHADOW"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def decimal(value: object) -> Decimal:
    """Do not silently turn a binary float into purported original ledger precision."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise TypeError("AQ-EVIDENCE-DECIMAL-REQUIRES-ORIGINAL-TEXT")
    result = Decimal(value)
    require(result.is_finite(), "AQ-EVIDENCE-NONFINITE")
    return result


def utc(value: str | datetime) -> datetime:
    result = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    require(result.utcoffset() == timedelta(0), "AQ-EVIDENCE-NON-UTC")
    return result.astimezone(UTC)


def checked_path(root: Path, name: str, *, protected_roots: Sequence[Path] = ()) -> Path:
    """Check lexical and resolved ancestry before opening, including Windows junctions."""
    relative = safe_relative_path(name)
    require(":" not in relative, "AQ-EVIDENCE-ALTERNATE-STREAM")
    candidate = root / relative
    for part in (candidate, *candidate.parents):
        if part.is_symlink() or part.is_junction():
            raise PermissionError("AQ-EVIDENCE-LINK-FORBIDDEN")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise PermissionError("AQ-EVIDENCE-OUTSIDE-ROOT")
    if "holdout" in {part.lower() for part in candidate.parts} or any(
        resolved.is_relative_to(p.resolve()) for p in protected_roots
    ):
        raise PermissionError("AQ-EVIDENCE-PROTECTED-HOLDOUT")
    if candidate.name == ".env" or candidate.name.startswith(".env."):
        raise PermissionError("AQ-EVIDENCE-CREDENTIAL-FILE")
    return candidate


def claim_output(root: Path, name: str, *, frozen_roots: Sequence[Path] = ()) -> Path:
    output = checked_path(root, name)
    allowed = (root / "artifacts/alpha_v5").resolve()
    if output.resolve() == allowed or not output.resolve().is_relative_to(allowed):
        raise PermissionError("AQ-EVIDENCE-OUTPUT-OUTSIDE-AUDIT-ROOT")
    if any(
        output.resolve().is_relative_to(p.resolve()) or p.resolve().is_relative_to(output.resolve())
        for p in frozen_roots
    ):
        raise PermissionError("AQ-EVIDENCE-FROZEN-OUTPUT")
    # mkdir(exist_ok=False) is the generation claim, even for an empty previous attempt.
    output.mkdir(parents=True, exist_ok=False)
    return output


def resolve_required_evidence(*, collected: bool, received: bool, verified: bool = False) -> str:
    if not collected:
        require(not received, "AQ-EVIDENCE-UNEXECUTED-RESULT-CONFLICT")
        return EvidenceStatus.NOT_COLLECTED
    if not received:
        return EvidenceStatus.NOT_RECEIVED
    return EvidenceStatus.VERIFIED if verified else EvidenceStatus.NOT_VERIFIED


def verify_full_bundle(path: Path | None, expected_sha256: str) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"status": EvidenceStatus.NOT_RECEIVED, "full_raw_bundle_received": False}
    actual = sha256_file(checked_path(path.parent, path.name))
    require(actual == expected_sha256, "AQ-EVIDENCE-FULL-BUNDLE-HASH-CONFLICT")
    return {"status": EvidenceStatus.HASH_ONLY, "full_raw_bundle_received": True, "sha256": actual}


def load_evidence_manifest(root: Path, name: str = "MANIFEST.json") -> dict[str, Any]:
    path = checked_path(root, name)
    if not path.exists():
        return {"status": EvidenceStatus.NOT_RECEIVED, "listed_files_verified": 0}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    listed = manifest["files"]
    files: list[dict[str, Any]]
    if isinstance(listed, dict):
        entries = cast(dict[str, Any], listed)
        files = [
            {**cast(dict[str, Any], value), "path": key}
            if isinstance(value, dict)
            else {"path": key, "sha256": value}
            for key, value in entries.items()
        ]
    else:
        files = listed
    names: set[str] = set()
    for item in files:
        require(item["path"] not in names, "AQ-EVIDENCE-MANIFEST-DUPLICATE")
        names.add(item["path"])
        member = checked_path(root, item["path"])
        require(member.is_file(), "AQ-EVIDENCE-LISTED-FILE-MISSING")
        require(sha256_file(member) == item["sha256"], "AQ-EVIDENCE-MANIFEST-HASH-CONFLICT")
        if "bytes" in item:
            require(member.stat().st_size == item["bytes"], "AQ-EVIDENCE-MANIFEST-SIZE-CONFLICT")
    return {
        "status": EvidenceStatus.VERIFIED,
        "listed_files_verified": len(names),
        "manifest_sha256": sha256_file(path),
    }


@dataclass(frozen=True)
class VersionBinding:
    source_head: str
    source_manifest_sha256: str
    generation: str
    strategy: str
    start: str
    end_exclusive: str
    tier: str


def validate_version_binding(actual: VersionBinding, expected: VersionBinding) -> None:
    require(actual == expected, "AQ-EVIDENCE-VERSION-STRATEGY-PERIOD-CONFLICT")
    require(utc(actual.start) < utc(actual.end_exclusive), "AQ-EVIDENCE-PERIOD")


def check_calendar_contract(
    rows: Sequence[Row], *, start: str, end: str, interval: timedelta = timedelta(days=1)
) -> list[datetime]:
    require(bool(rows) and interval > timedelta(0), "AQ-EVIDENCE-EMPTY-CALENDAR")
    times = [utc(r["time"]) for r in rows]
    require(len(times) == len(set(times)), "AQ-EVIDENCE-DUPLICATE-TIME")
    require(times == sorted(times), "AQ-EVIDENCE-TIME-ORDER")
    require(times[0] == utc(start) and times[-1] == utc(end), "AQ-EVIDENCE-CALENDAR-ENDPOINTS")
    require(
        all(b - a == interval for a, b in pairwise(times)),
        "AQ-EVIDENCE-CALENDAR-GAP",
    )
    if interval == timedelta(days=1):
        require(all(t.time() == datetime.min.time() for t in times), "AQ-EVIDENCE-NON-DAY-BOUNDARY")
    return times


def quarter_returns(rows: Sequence[Row]) -> list[dict[str, Any]]:
    """Return ending at a quarter boundary belongs to the preceding quarter."""
    factors: dict[str, Decimal] = {}
    with localcontext() as ctx:
        ctx.prec = 50
        for before, after in pairwise(rows):
            time = utc(after["time"]) - timedelta(microseconds=1)
            key = f"{time.year}Q{(time.month - 1) // 3 + 1}"
            initial = decimal(before["equity"])
            require(initial > 0, "AQ-EVIDENCE-NONPOSITIVE-EQUITY")
            factors[key] = factors.get(key, ONE) * decimal(after["equity"]) / initial
        return [{"quarter": key, "return": value - ONE} for key, value in factors.items()]


def audit_equity(
    rows: Sequence[Row],
    summaries: Sequence[Row],
    *,
    start: str,
    end: str,
    initial_cash: Decimal,
    interval: timedelta = timedelta(days=1),
    quarters: Sequence[Row] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for row in rows:
        groups[str(row["arm"]), str(row["cost"])].append(row)
    summary = {(str(r["arm"]), str(r["cost"])): r for r in summaries}
    require(
        len(summary) == len(summaries) and set(groups) == set(summary),
        "AQ-EVIDENCE-ARM-COST-COVERAGE",
    )
    results: list[dict[str, Any]] = []
    for key, group in sorted(groups.items()):
        times = check_calendar_contract(group, start=start, end=end, interval=interval)
        modes = {(r["mode"], r["capital_mode"]) for r in group}
        require(len(modes) == 1, "AQ-EVIDENCE-MIXED-CAPITAL-MODE")
        mode, capital_mode = next(iter(modes))
        require(CostMode(mode) != CostMode.SAME_FILL_SHADOW, "AQ-EVIDENCE-SHADOW-NOT-ACCOUNT")
        require(
            capital_mode == "FIVE_EQUAL_INITIAL_SLEEVES_NO_TRANSFERS",
            "AQ-EVIDENCE-CAPITAL-CONTRACT",
        )
        require(
            decimal(group[0]["equity"]) == initial_cash == decimal(summary[key]["initial_equity"]),
            "AQ-EVIDENCE-INITIAL-CAPITAL",
        )
        balances: list[Decimal] = []
        nav_checks: list[Decimal] = []
        for row in group:
            equity, cash, inventory = (
                decimal(row[k]) for k in ("equity", "cash", "position_value")
            )
            require(
                equity > 0 and cash >= -MONEY_TOLERANCE and inventory >= 0,
                "AQ-EVIDENCE-UNFUNDED-ACCOUNT",
            )
            residual = equity - cash - inventory
            require(abs(residual) <= MONEY_TOLERANCE, "AQ-EVIDENCE-CASH-INVENTORY-IDENTITY")
            balances.append(abs(residual))
            if "external_flow" in row:
                require(decimal(row["external_flow"]) == 0, "AQ-EVIDENCE-EXTRA-PRINCIPAL")
            if "cumulative_net_pnl" in row:
                residual = equity - initial_cash - decimal(row["cumulative_net_pnl"])
                require(abs(residual) <= MONEY_TOLERANCE, "AQ-EVIDENCE-CAPITAL-PNL-IDENTITY")
                nav_checks.append(residual)
            if "quantity" in row and "mark_price" in row:
                require(
                    abs(inventory - decimal(row["quantity"]) * decimal(row["mark_price"]))
                    <= MONEY_TOLERANCE,
                    "AQ-EVIDENCE-INVENTORY-VALUATION",
                )
        terminal = decimal(group[-1]["equity"]) - decimal(summary[key]["final_equity"])
        require(abs(terminal) <= MONEY_TOLERANCE, "AQ-EVIDENCE-TERMINAL-MISMATCH")
        quarter = quarter_returns(group)
        with localcontext() as ctx:
            ctx.prec = 50
            compound = math.prod((ONE + q["return"] for q in quarter), start=ONE) - ONE
            total = decimal(group[-1]["equity"]) / initial_cash - ONE
            residual = compound - total
        require(abs(residual) <= RETURN_TOLERANCE, "AQ-EVIDENCE-QUARTER-COMPOUND")
        require(
            abs(total - decimal(summary[key]["net_compound_return"])) <= RETURN_TOLERANCE,
            "AQ-EVIDENCE-RETURN-SUMMARY",
        )
        require(len(quarter) == int(summary[key]["quarter_count"]), "AQ-EVIDENCE-QUARTER-COUNT")
        if "positive_quarter_fraction" in summary[key]:
            fraction = Decimal(sum(q["return"] > 0 for q in quarter)) / len(quarter)
            require(
                abs(fraction - decimal(summary[key]["positive_quarter_fraction"]))
                <= RETURN_TOLERANCE,
                "AQ-EVIDENCE-POSITIVE-QUARTERS",
            )
        if quarters is not None:
            expected = {
                q["quarter"]: decimal(q["return"])
                for q in quarters
                if (str(q["arm"]), str(q["cost"])) == key
            }
            require(len(expected) == len(quarter), "AQ-EVIDENCE-QUARTER-COVERAGE")
            for q in quarter:
                require(
                    q["quarter"] in expected
                    and abs(q["return"] - expected[q["quarter"]]) <= RETURN_TOLERANCE,
                    "AQ-EVIDENCE-QUARTER-ROW-MISMATCH",
                )
        results.append(
            {
                "arm": key[0],
                "cost": key[1],
                "status": EvidenceStatus.DERIVED_ONLY,
                "points": len(times),
                "start": times[0],
                "end": times[-1],
                "initial_equity": initial_cash,
                "final_equity": decimal(group[-1]["equity"]),
                "terminal_residual": terminal,
                "max_balance_residual": max(balances),
                "quarter_compound_residual": residual,
                "quarters": quarter,
                "positive_quarters": sum(q["return"] > 0 for q in quarter),
                "external_capital_and_pnl": EvidenceStatus.VERIFIED
                if len(nav_checks) == len(group) and all("external_flow" in r for r in group)
                else EvidenceStatus.NOT_VERIFIED,
            }
        )
    return results


def audit_fills(rows: Sequence[Row], summaries: Sequence[Row]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for row in rows:
        groups[str(row["arm"]), str(row["cost"])].append(row)
    summary = {(str(r["arm"]), str(r["cost"])): r for r in summaries}
    require(
        set(groups) == set(summary) and len(summary) == len(summaries),
        "AQ-EVIDENCE-FILL-ARM-COST-COVERAGE",
    )
    results: list[dict[str, Any]] = []
    with localcontext() as ctx:
        ctx.prec = 50
        for key, group in sorted(groups.items()):
            require(
                len({(r["symbol"], r["fill_id"]) for r in group}) == len(group),
                "AQ-EVIDENCE-DUPLICATE-FILL",
            )
            costs: list[Decimal] = []
            notionals: list[Decimal] = []
            residuals: list[Decimal] = []
            for r in group:
                cost = decimal(r["total_cost"])
                notional = decimal(r["filled_notional"])
                quantity = decimal(r["filled_qty"])
                # Frozen fill_attribution exports signed quantity and gross notional.
                require(
                    quantity != 0 and notional > 0 and cost >= 0,
                    "AQ-EVIDENCE-FILL-AMOUNT",
                )
                if r["reason_primary"] in {"ORDINARY_RISK_REDUCE", "ORDINARY_RISK_RESTORE"}:
                    require(
                        (quantity < 0) == (r["reason_primary"] == "ORDINARY_RISK_REDUCE"),
                        "AQ-EVIDENCE-LONG-ONLY-RESIZE-DIRECTION",
                    )
                residual = cost - sum(
                    (
                        decimal(r[k])
                        for k in ("fee_paid", "spread_cost", "slippage_cost", "impact_cost")
                    ),
                    ZERO,
                )
                require(abs(residual) <= LEDGER_TOLERANCE, "AQ-EVIDENCE-COST-COMPONENTS")
                costs.append(cost)
                notionals.append(notional)
                residuals.append(abs(residual))
            reasons = Counter(str(r["reason_primary"]) for r in group)
            ordinary = reasons["ORDINARY_RISK_REDUCE"] + reasons["ORDINARY_RISK_RESTORE"]
            target = summary[key]
            require(
                len(group) == int(target["fills"]) and ordinary == int(target["risk_resize_fills"]),
                "AQ-EVIDENCE-FILL-REASON-COUNT",
            )
            cost_residual = sum(costs, ZERO) - decimal(target["total_cost"])
            notional_residual = sum(notionals, ZERO) - decimal(target["traded_notional"])
            require(
                abs(cost_residual) <= MONEY_TOLERANCE and abs(notional_residual) <= MONEY_TOLERANCE,
                "AQ-EVIDENCE-FILL-TOTALS",
            )
            results.append(
                {
                    "arm": key[0],
                    "cost": key[1],
                    "status": EvidenceStatus.DERIVED_ONLY,
                    "filled_qty_semantics": "SIGNED_BUY_POSITIVE_SELL_NEGATIVE",
                    "fills": len(group),
                    "ordinary_resize_fills": ordinary,
                    "reason_counts": dict(sorted(reasons.items())),
                    "notional": sum(notionals, ZERO),
                    "total_cost": sum(costs, ZERO),
                    "notional_residual": notional_residual,
                    "cost_residual": cost_residual,
                    "max_component_residual": max(residuals),
                    "raw_order_fill_reconstruction": EvidenceStatus.NOT_VERIFIED,
                }
            )
    return results


def audit_cost_path(
    mode: CostMode, rows: Sequence[Row], *, require_fill_identity: bool = True
) -> dict[str, Any]:
    mode = CostMode(mode)
    require(len(rows) >= 2, "AQ-EVIDENCE-COST-SCENARIOS")
    ordered = sorted(rows, key=lambda r: decimal(r["cost"]))
    require(len({decimal(r["cost"]) for r in rows}) == len(rows), "AQ-EVIDENCE-COST-DUPLICATE")
    for row in rows:
        require(
            decimal(row["cost"]) >= 0 and decimal(row["total_cost"]) >= 0,
            "AQ-EVIDENCE-NEGATIVE-COST",
        )
        decimal(row["final_equity"])
    if any("arm" in r or "symbol" in r for r in rows):
        require(
            all("arm" in r and "symbol" in r for r in rows), "AQ-EVIDENCE-COST-IDENTITY-MISSING"
        )
        require(
            len({(r["arm"], r["symbol"]) for r in rows}) == 1, "AQ-EVIDENCE-COST-IDENTITY-CONFLICT"
        )
    if mode != CostMode.SAME_FILL_SHADOW:
        return {
            "mode": mode,
            "monotonic_wealth_required": False,
            "reason": "Funded cash, partial fills, refusals and inventory paths may differ.",
        }
    identity = all("fill_path" in r for r in rows)
    if require_fill_identity:
        require(identity, "AQ-EVIDENCE-SHADOW-FILL-PATH-MISSING")
    if identity:
        # Each path includes time, quantity, side, reference price and inventory after the fill.
        fields = {"time", "quantity", "side", "reference_price", "inventory"}
        for r in rows:
            require(
                all(fields <= f.keys() for f in r["fill_path"]), "AQ-EVIDENCE-SHADOW-PATH-FIELDS"
            )
        require(
            all(r["fill_path"] == rows[0]["fill_path"] for r in rows),
            "AQ-EVIDENCE-SHADOW-PATH-CHANGED",
        )
    for before, after in pairwise(ordered):
        cost_delta = decimal(after["total_cost"]) - decimal(before["total_cost"])
        wealth_delta = decimal(after["final_equity"]) - decimal(before["final_equity"])
        require(
            cost_delta >= -LEDGER_TOLERANCE and wealth_delta <= LEDGER_TOLERANCE,
            "AQ-EVIDENCE-SHADOW-ADVERSE-COST-IMPROVES-PNL",
        )
        require(
            abs(cost_delta + wealth_delta) <= LEDGER_TOLERANCE,
            "AQ-EVIDENCE-SHADOW-ACCOUNTING-IDENTITY",
        )
    return {
        "mode": mode,
        "status": EvidenceStatus.VERIFIED if identity else EvidenceStatus.NOT_VERIFIED,
        "saved_table_arithmetic_status": EvidenceStatus.DERIVED_ONLY,
        "monotonic_wealth_required": True,
        "fill_path_identity": EvidenceStatus.VERIFIED if identity else EvidenceStatus.NOT_VERIFIED,
        "funding_feasibility_claimed": False,
    }


def statistics_identity(original: Row, settings: Row) -> dict[str, Any]:
    require(
        tuple(settings["comparisons"]) == COMPARISONS
        and set(original["comparisons"]) == set(COMPARISONS),
        "AQ-EVIDENCE-STATISTICAL-FAMILY-CHANGED",
    )
    require(
        original["dsr"] is None and original["pbo"] is None,
        "AQ-EVIDENCE-UNKNOWN-TRIAL-HISTORY-CANNOT-PASS",
    )
    rows = {}
    for name in COMPARISONS:
        old = original["comparisons"][name]
        for field in ("one_sided_mean_p_value", "holm_adjusted_p_value"):
            require(ZERO <= decimal(old[field]) <= ONE, "AQ-EVIDENCE-P-VALUE")
        require(decimal(old["ci95_lower"]) <= decimal(old["ci95_upper"]), "AQ-EVIDENCE-CI-ORDER")
        rows[name] = {
            "original_values": dict(old),
            "p_value_estimand": "DAILY_MEAN_RETURN_DIFFERENCE",
            "secondary_interval_estimand": "COMPOUNDED_RETURN_DIFFERENCE",
            "secondary_interval_multiplicity_adjusted": False,
            "correction": "HOLM",
        }
    return {
        "status": EvidenceStatus.DERIVED_ONLY,
        "original_statistics": dict(original),
        "comparisons": rows,
        "family_size": len(COMPARISONS),
        "family_sha256": canonical_sha256(list(COMPARISONS)),
        "bootstrap": {
            "seed": settings["seed"],
            "repetitions": settings["repetitions"],
            "block_days": original["block_days"],
            "method": "PAIRED_CIRCULAR_BLOCK",
            "source": "FROZEN_PREREGISTRATION_AND_IMPLEMENTATION",
        },
        "new_resamples": 0,
        "dsr": None,
        "pbo": None,
        "dsr_pbo_status": original["dsr_pbo_status"],
        "independent_trial_count": None,
        "promotion_authorization": False,
    }


@dataclass(frozen=True)
class ReviewClock:
    last_event: datetime | None = None
    last_review: datetime | None = None
    last_submitted: datetime | None = None
    last_fill: datetime | None = None


def review_clock_transition(
    state: ReviewClock,
    event: str,
    time: datetime,
    *,
    interval: timedelta = timedelta(hours=48),
    good: bool = True,
    trend: bool = True,
    held: Decimal = ONE,
    pending: bool = False,
) -> tuple[ReviewClock, bool]:
    """Synthetic projection of frozen cat_replay lines 502-513 and 837-847, not a scheduler."""
    time = utc(time)
    require(interval > timedelta(0) and decimal(held) >= 0, "AQ-EVIDENCE-CLOCK-INPUT")
    require(all(type(v) is bool for v in (good, trend, pending)), "AQ-EVIDENCE-CLOCK-FLAGS")
    for previous in (state.last_event, state.last_review, state.last_submitted, state.last_fill):
        require(previous is None or utc(previous) <= time, "AQ-EVIDENCE-CLOCK-BACKWARDS")
    require(
        event
        in {
            "DECISION",
            "SUBMIT",
            "REJECT",
            "PARTIAL_FILL",
            "FILL",
            "CANCEL_REQUEST",
            "CANCEL_ACK",
            "GAP",
        },
        "AQ-EVIDENCE-CLOCK-EVENT",
    )
    due = state.last_review is None or time - state.last_review >= interval
    result = replace(state, last_event=time)
    if event == "DECISION" and due and good and trend and held > 0 and not pending:
        result = replace(result, last_review=time)
    if event == "SUBMIT":
        result = replace(result, last_review=time, last_submitted=time)
    if event in {"PARTIAL_FILL", "FILL"}:
        result = replace(result, last_fill=time)
    return result, due


def resize_cost_allowed(benefit: Decimal, cost_fraction: Decimal, multiplier: Decimal) -> bool:
    require(
        decimal(benefit) >= 0 and decimal(cost_fraction) >= 0 and decimal(multiplier) > 0,
        "AQ-EVIDENCE-UTILITY-INPUT",
    )
    return benefit > 0 and cost_fraction <= multiplier * benefit


def write_json_exclusive(path: Path, value: object) -> None:
    def encode(item: object) -> str:
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, datetime):
            return item.isoformat()
        raise TypeError(f"unsupported evidence value: {type(item).__name__}")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, default=encode, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def write_csv_exclusive(path: Path, rows: Sequence[Row]) -> None:
    require(bool(rows), "AQ-EVIDENCE-EMPTY-CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


BASE = "d8c6d4013097f6323ab8b7a424c860ba0ccbd62b"
NEW_FILES = (
    "src/aegisquant/research/validation/evidence_contract.py",
    "scripts/audit_alpha_v5_evidence.py",
    "configs/research/alpha_v5_review_contract.yaml",
    "tests/alpha_v5/test_evidence_contract.py",
    "tests/alpha_v5/test_resize_semantics_contract.py",
    "docs/research/alpha_v5_review_contract.md",
)
ZERO_BUDGETS = (
    "historical_strategy_engine_runs",
    "real_return_model_fits",
    "real_calibration_fits",
    "final_holdout_accesses",
    "real_orders",
)
LOCKS = (
    "production_ml_enabled",
    "paper_trading_admitted",
    "live_trading",
    "order_submission_enabled",
)


class EvidenceReader:
    """Hash each actually read input and refuse protected paths before opening it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.reads: dict[str, dict[str, Any]] = {}

    def path(self, name: str, scope: str = "SAVED_CONTENT") -> Path:
        path = checked_path(self.root, name)
        digest = sha256_file(path)
        if name in self.reads:
            require(digest == self.reads[name]["sha256"], "AQ-EVIDENCE-INPUT-CHANGED-DURING-READ")
        self.reads[name] = {"sha256": digest, "bytes": path.stat().st_size, "scope": scope}
        return path

    def json(self, name: str, *, native: bool = False) -> dict[str, Any]:
        text = self.path(name).read_text(encoding="utf-8")
        return json.loads(text) if native else json.loads(text, parse_float=Decimal)

    def table(self, name: str) -> list[dict[str, Any]]:
        path = self.path(name, "SAVED_DERIVED_TABLE_NOT_RAW_LEDGER")
        # The file itself contains binary64 portfolio columns. repr explicitly preserves
        # their shortest round-trip text; it does not assert original Decimal precision.
        return [
            {key: repr(value) if isinstance(value, float) else value for key, value in row.items()}
            for row in pl.read_parquet(path).to_dicts()
        ]


def validate_config(config: Mapping[str, Any]) -> None:
    match = re.fullmatch(r"alpha-r5-review-contract-(\d{8})-v([1-9]\d*)", config["generation"])
    require(match is not None, "AQ-EVIDENCE-GENERATION")
    if match is None:
        return
    require(
        config["output"] == f"artifacts/alpha_v5/{match[1]}_review_contract_v{match[2]}",
        "AQ-EVIDENCE-GENERATION-OUTPUT-BINDING",
    )
    require(
        len(config.get("prior_report_failures", [])) == int(match[2]) - 1,
        "AQ-EVIDENCE-PRIOR-REPORT-ATTEMPTS-MISSING",
    )
    require(
        config["source"]["github_base"] == BASE and config["branch_required"] == "main",
        "AQ-EVIDENCE-BASE-IDENTITY",
    )
    require(
        config["scope"] == "READ_ONLY_EVIDENCE_AND_SYNTHETIC_CONTRACT_TESTS"
        and config["kind"] == "EVIDENCE_REPORT_NOT_ALPHA_TRIAL",
        "AQ-EVIDENCE-SCOPE",
    )
    require(
        config["budgets"] == {"report_jobs": 1, **dict.fromkeys(ZERO_BUDGETS, 0)},
        "AQ-EVIDENCE-NONZERO-RESEARCH-BUDGET",
    )
    require(tuple(config["comparisons"]) == COMPARISONS, "AQ-EVIDENCE-COMPARISONS")
    require(set(config["cost_modes"]) == {m.value for m in CostMode}, "AQ-EVIDENCE-COST-MODES")
    require(
        config["research_conclusion"] == "NO_PROVEN_ALPHA"
        and config["production_policy"] == "CASH"
        and all(config[k] is False for k in LOCKS),
        "AQ-EVIDENCE-SAFETY-LOCK",
    )


@contextmanager
def zero_budget_guard(output: Path, root: Path, counters: dict[str, int]) -> Generator[None]:
    """Deny dangerous calls before their bodies, network, protected reads and outside writes."""
    active = True
    previous_profile = sys.getprofile()
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    forbidden = {
        "replay_cat": "historical_strategy_engine_runs",
        "load_completed_bars": "historical_strategy_engine_runs",
        "fit": "real_return_model_fits",
        "fit_transform": "real_return_model_fits",
        "calibrate": "real_calibration_fits",
        "submit_order": "real_orders",
        "submit_orders": "real_orders",
    }

    def profile(frame: FrameType, event: str, arg: object) -> None:
        if event != "call":
            return
        filename = frame.f_code.co_filename.replace("\\", "/").lower()
        key = forbidden.get(frame.f_code.co_name)
        if "persistent_holdout" in filename:
            key = "final_holdout_accesses"
        if key:
            counters[key] += 1
            raise PermissionError(f"AQ-EVIDENCE-FORBIDDEN-CALL:{key}")

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if not active:
            return
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system"}:
            raise PermissionError("AQ-EVIDENCE-NETWORK-OR-SUBPROCESS-FORBIDDEN")
        if event != "open" or not args or not isinstance(args[0], (str, bytes)):
            return
        path = Path(args[0].decode() if isinstance(args[0], bytes) else args[0]).absolute()
        if "holdout" in {p.lower() for p in path.parts}:
            counters["final_holdout_accesses"] += 1
            raise PermissionError("AQ-EVIDENCE-PROTECTED-HOLDOUT")
        if path.name == ".env" or path.name.startswith(".env."):
            raise PermissionError("AQ-EVIDENCE-CREDENTIAL-FILE")
        mode = args[1] or ""
        flags = args[2] or 0
        if any(c in mode for c in "wax+") or flags & 3:
            if not path.resolve().is_relative_to(output.resolve()):
                raise PermissionError("AQ-EVIDENCE-INPUTS-ARE-READ-ONLY")
        elif path.is_relative_to(root.absolute()):
            checked_path(root, path.relative_to(root.absolute()).as_posix())

    sys.addaudithook(audit)
    sys.setprofile(profile)
    try:
        yield
    finally:
        active = False
        sys.setprofile(previous_profile)
        sys.dont_write_bytecode = previous_bytecode


def verify_sources(
    reader: EvidenceReader, config: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    source = config["source"]
    r5 = source["r5"]
    path = reader.path(f"{r5}/audit_manifest.json")
    require(sha256_file(path) == source["r5_manifest_sha256"], "AQ-EVIDENCE-R5-MANIFEST-PIN")
    manifest = reader.json(f"{r5}/audit_manifest.json", native=True)
    require(
        manifest["sha256"]
        == canonical_sha256({k: v for k, v in manifest.items() if k != "sha256"}),
        "AQ-EVIDENCE-R5-MANIFEST-CANONICAL-HASH",
    )
    require(
        canonical_sha256(manifest["source_hashes"]) == manifest["code_sha256"],
        "AQ-EVIDENCE-R5-SOURCE-MANIFEST",
    )
    require(
        reader.path(f"{r5}/preregistration.json").read_bytes() == path.read_bytes(),
        "AQ-EVIDENCE-R5-PREREGISTRATION-CONFLICT",
    )
    journal = ExperimentEventJournal(
        reader.path(f"{r5}/experiment_events.jsonl", "FROZEN_RUN_HASH_CHAIN")
    )
    entries = journal.entries()
    require(
        {e.event.run_id for e in entries} == set(manifest["planned_run_ids"]),
        "AQ-EVIDENCE-FROZEN-RUN-COVERAGE",
    )
    for run_id in manifest["planned_run_ids"]:
        terminal = journal.history(run_id)[-1]
        require(terminal.event_type.value == "SUCCEEDED", "AQ-EVIDENCE-FROZEN-RUN-NOT-COMPLETE")
        details = terminal.details
        if "artifacts_sha256" in details:
            prefix = f"{r5}/runs/{details['arm']}/{details['symbol']}/{details['cost']}"
            for name, expected_hash in cast(dict[str, str], details["artifacts_sha256"]).items():
                require(
                    sha256_file(reader.path(f"{prefix}/{name}", "JOURNAL_BOUND_ARTIFACT_HASH_ONLY"))
                    == expected_hash,
                    f"AQ-EVIDENCE-RUN-ARTIFACT-HASH:{run_id}/{name}",
                )
        else:
            require(
                sha256_file(
                    reader.path(f"{r5}/baseline_reproduction.json", "REPRODUCTION_HASH_ONLY")
                )
                == details["baseline_result_sha256"],
                "AQ-EVIDENCE-BASELINE-RESULT-HASH",
            )
    expected_period = config["period_binding"]["r5_long"]
    actual = VersionBinding(
        manifest["source_head"],
        sha256_file(path),
        manifest["config"]["generation"],
        manifest["config"]["primary_candidate"],
        manifest["config"]["development"]["test_start"],
        manifest["config"]["development"]["end_exclusive"],
        expected_period["tier"],
    )
    expected = VersionBinding(
        BASE,
        source["r5_manifest_sha256"],
        source["r5_generation"],
        "G1",
        expected_period["start"],
        expected_period["end_exclusive"],
        expected_period["tier"],
    )
    validate_version_binding(actual, expected)
    workspace_differences: list[str] = []
    for name, expected_hash in manifest["source_hashes"].items():
        frozen = reader.path(f"{r5}/implementation/{name}", "FROZEN_SOURCE_HASH")
        require(sha256_file(frozen) == expected_hash, f"AQ-EVIDENCE-FROZEN-SOURCE-CONFLICT:{name}")
        current = reader.path(name, "CURRENT_SOURCE_HASH")
        if sha256_file(current) != expected_hash:
            workspace_differences.append(name)
    for name, expected_hash in manifest["frozen_evidence"].items():
        require(
            sha256_file(reader.path(name, "FROZEN_EVIDENCE_HASH_ONLY")) == expected_hash,
            f"AQ-EVIDENCE-FROZEN-ARTIFACT-CONFLICT:{name}",
        )
    recent_name = f"{source['recent']}/effective_config.json"
    recent_path = reader.path(recent_name)
    require(
        sha256_file(recent_path) == source["recent_config_sha256"],
        "AQ-EVIDENCE-RECENT-MANIFEST-PIN",
    )
    recent = reader.json(recent_name, native=True)
    period = config["period_binding"]["recent_r4"]
    validate_version_binding(
        VersionBinding(
            recent["source_head"],
            sha256_file(recent_path),
            recent["version"],
            recent["primary_candidate"],
            utc(recent["test_start"]).isoformat(),
            utc(recent["test_end_exclusive"]).isoformat(),
            period["tier"],
        ),
        VersionBinding(
            BASE,
            source["recent_config_sha256"],
            "recent-r4-fixed-20260908-v1",
            "F3",
            utc(period["start"]).isoformat(),
            utc(period["end_exclusive"]).isoformat(),
            period["tier"],
        ),
    )
    for name, expected_hash in recent["source_sha256"].items():
        frozen = reader.path(
            f"{source['recent']}/implementation/{name}", "RECENT_FROZEN_SOURCE_HASH"
        )
        require(sha256_file(frozen) == expected_hash, f"AQ-EVIDENCE-RECENT-SOURCE-CONFLICT:{name}")
    require("G1" not in recent["arms"], "AQ-EVIDENCE-RECENT-G1-IDENTITY-CONFLICT")
    return manifest, {
        "r5": asdict(actual),
        "recent_r4": {"config": recent_name, "strategy": "F3", **period},
        "source_manifest_status": EvidenceStatus.VERIFIED,
        "frozen_source_files_verified": len(manifest["source_hashes"]),
        "recent_frozen_source_files_verified": len(recent["source_sha256"]),
        "current_workspace_different_from_r5": workspace_differences,
        "audited_source": "FROZEN_IMPLEMENTATION",
        "strategy_stitching_allowed": False,
        "recent_g1": resolve_required_evidence(collected=False, received=False),
    }


def synthetic_resize_cases(
    reader: EvidenceReader, manifest: dict[str, Any], r5: str
) -> dict[str, Any]:
    name = "src/aegisquant/research/strategies/buffered_target.py"
    path = reader.path(f"{r5}/implementation/{name}", "FROZEN_PURE_UTILITY_SOURCE")
    require(sha256_file(path) == manifest["source_hashes"][name], "AQ-EVIDENCE-UTILITY-SOURCE-HASH")
    spec = importlib.util.spec_from_file_location("_aegis_frozen_review_buffer", path)
    require(spec is not None and spec.loader is not None, "AQ-EVIDENCE-FROZEN-UTILITY-LOAD")
    if spec is None or spec.loader is None:
        raise ValueError("frozen utility unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        benefit = module.rebalance_risk_benefit(
            Decimal(".40"), Decimal(".33"), Decimal(".30"), Decimal(".60"), timedelta(days=2)
        )
        away = module.rebalance_risk_benefit(
            Decimal(".40"), Decimal(".50"), Decimal(".30"), Decimal(".60"), timedelta(days=2)
        )
    finally:
        sys.modules.pop(spec.name, None)
    cost = Decimal(".07") * Decimal(".0016")
    events: list[dict[str, Any]] = []
    state = ReviewClock()
    start = datetime(2020, 1, 1, tzinfo=UTC)
    for hours, event, pending in (
        (0, "DECISION", False),
        (0, "REJECT", False),
        (47, "DECISION", False),
        (48, "DECISION", True),
        (48, "CANCEL_REQUEST", True),
        (48, "CANCEL_ACK", False),
        (48, "DECISION", False),
        (48, "SUBMIT", False),
        (48, "PARTIAL_FILL", True),
        (49, "FILL", False),
        (50, "REJECT", False),
        (60, "GAP", False),
        (96, "DECISION", False),
    ):
        before = state
        state, due = review_clock_transition(
            state, event, start + timedelta(hours=hours), pending=pending
        )
        events.append(
            {
                "hour": hours,
                "event": event,
                "pending": pending,
                "review_due_before": due,
                "before": asdict(before),
                "after": asdict(state),
            }
        )
    required_fields = [
        "decision_id",
        "raw_weight",
        "smoothed_weight",
        "current_weight",
        "proposed_weight_before_veto",
        "final_weight_after_second_rounding",
        "annual_volatility",
        "horizon_seconds",
        "review_due_before",
        "last_review_before",
        "last_review_after",
        "last_submitted_at",
        "last_fill_at",
        "pending_quantity",
        "each_gate_evaluated",
        "each_gate_reason",
        "superseded_by_hard_risk",
        "cost_fraction",
        "benefit",
        "rule_sha256",
        "source_sha256",
        "order_id",
        "fill_ids",
        "fee_asset",
        "position_by_symbol",
    ]
    traces: list[dict[str, Any]] = []
    for trial in manifest["planned_runs"]:
        prefix = f"{r5}/runs/{trial['arm']}/{trial['symbol']}/{trial['cost']}"
        path = reader.path(f"{prefix}/decision_trace.parquet", "TRACE_SCHEMA_ONLY_NO_ROW_JOIN")
        schema = pl.read_parquet_schema(path)
        raw = reader.path(f"{prefix}/result.json.gz", "ORIGINAL_RESULT_HASH_ONLY_NO_DECOMPRESSION")
        traces.append(
            {
                **trial,
                "trace": str(path.relative_to(reader.root).as_posix()),
                "trace_sha256": sha256_file(path),
                "result_sha256": sha256_file(raw),
                "missing_new_schema_fields": sorted(set(required_fields) - set(schema)),
                "row_join_status": EvidenceStatus.NOT_VERIFIED,
            }
        )
    return {
        "kind": "SYNTHETIC_ONLY_NOT_A_RESEARCH_TRIAL",
        "frozen_utility_sha256": manifest["source_hashes"][name],
        "variance_case": {
            "current": ".40",
            "raw": ".30",
            "proposed": ".33",
            "annual_vol": ".60",
            "horizon_days": 2,
            "benefit_nav": benefit,
            "illustrative_cost_nav": cost,
            "cost_over_benefit": cost / benefit,
            "cost_assumption": "SYNTHETIC_16BPS_NOT_HISTORICAL_FEES",
            "lambda_1_allows": resize_cost_allowed(benefit, cost, Decimal(1)),
            "lambda_13_allows": resize_cost_allowed(benefit, cost, Decimal(13)),
            "move_away_benefit": away,
        },
        "clock_definition": "ELAPSED_SINCE_LAST_REVIEW_OR_SUBMITTED_ORDER",
        "clock_cases": events,
        "clock_source_lines": "frozen cat_replay.py:502-513,837-847",
        "trace_schema": {
            "schema_version": "resize-decision-evidence-v1",
            "required_fields": required_fields,
            "unknown_fields_are_null": True,
            "historical_backfill_allowed": False,
        },
        "original_trace_inventory": traces,
        "historical_mechanism_verification": EvidenceStatus.NOT_VERIFIED,
        "unverified_topics": [
            "raw/smoothed/proposed conflicts",
            "gate funnel over ALL decisions",
            "review/submission/fill clocks and pending/refusal joins",
            "second rounding",
            "ALL indicators warmup after gaps",
            "hard exits and pending reconciliation",
            "per-asset inventory and common shock for ALL worst 5% four-hour windows",
        ],
        "historical_veto_count": None,
        "worst_event_date": None,
    }


def failure_history(
    reader: EvidenceReader, manifest: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    history: list[dict[str, Any]] = []
    for version in (1, 2, 3):
        prefix = f"artifacts/alpha_v5/20260908_research_churn_v{version}"
        registered = reader.json(f"{prefix}/preregistration.json", native=True)
        path = reader.path(f"{prefix}/experiment_events.jsonl", "HASH_CHAIN_AND_SAVED_OUTCOMES")
        journal = ExperimentEventJournal(path)
        entries = journal.entries()
        observed = {e.event.run_id for e in entries}
        require(observed <= set(registered["planned_run_ids"]), "AQ-EVIDENCE-UNREGISTERED-HISTORY")
        trials: list[dict[str, Any]] = []
        for run_id in registered["planned_run_ids"]:
            events = [e.event.model_dump(mode="json") for e in entries if e.event.run_id == run_id]
            trials.append(
                {
                    "run_id": run_id,
                    "kind": "REPRODUCTION"
                    if run_id.endswith(":baseline")
                    else "REGISTERED_DEVELOPMENT_SLEEVE",
                    "events": events,
                    "status": events[-1]["event_type"] if events else "NOT_EXECUTED",
                    "observed_return_result": any(
                        "artifacts_sha256" in e["details"] and e["event_type"] == "SUCCEEDED"
                        for e in events
                    ),
                }
            )
        history.append(
            {
                "generation": registered["config"]["generation"],
                "journal_sha256": sha256_file(path),
                "registered_slots": len(registered["planned_run_ids"]),
                "trials": trials,
                "history_classification": "ENGINEERING_PRECONDITION_FAILURE_BEFORE_NEW_STRATEGY_RESULTS"
                if version < 3
                else "OBSERVED_DEVELOPMENT_RESULTS_AND_REPRODUCTIONS",
            }
        )
    recent: list[dict[str, Any]] = []
    for version in (1, 2):
        path = f"artifacts/current_system_recent/20260908_v{version}/failure.json"
        recent.append(
            {
                "source": path,
                "kind": "ENGINEERING_PRECONDITION_FAILURE",
                "record": reader.json(path),
            }
        )
    report_failures: list[dict[str, Any]] = []
    for prior in config.get("prior_report_failures", []):
        prefix = prior["output"]
        registered = reader.json(f"{prefix}/preregistration.json", native=True)
        failed = reader.json(f"{prefix}/failure.json", native=True)
        path = reader.path(f"{prefix}/OUTPUT_MANIFEST.json", "PRIOR_FAILED_REPORT_MANIFEST")
        require(
            sha256_file(path) == prior["output_manifest_sha256"], "AQ-EVIDENCE-PRIOR-REPORT-HASH"
        )
        verification = load_evidence_manifest(path.parent, path.name)
        journal = ExperimentEventJournal(reader.path(f"{prefix}/experiment_events.jsonl"))
        events = [entry.event.model_dump(mode="json") for entry in journal.entries()]
        require(
            registered["config"]["generation"] == prior["generation"]
            and registered["kind"] == "EVIDENCE_REPORT_NOT_ALPHA_TRIAL"
            and registered["planned_run_ids"] == [prior["generation"] + ":REPORT"]
            and all(event["run_id"] == prior["generation"] + ":REPORT" for event in events)
            and events[-1]["event_type"] == "ERROR"
            and failed["actual_attempts"] == dict.fromkeys(ZERO_BUDGETS, 0),
            "AQ-EVIDENCE-PRIOR-REPORT-IDENTITY",
        )
        report_failures.append(
            {**prior, "manifest_verification": verification, "failure": failed, "events": events}
        )
    return {
        "status": "INCOMPLETE_GLOBAL_RESEARCH_HISTORY",
        "r5_generations": history,
        "recent_failures": recent,
        "review_report_failures": report_failures,
        "report_attempts_including_current": len(report_failures) + 1,
        "retained_neighbors": ["G1_H3", "G1_H10", "G1_R24", "G1_R72"],
        "frozen_comparisons": manifest["config"]["statistics"]["comparisons"],
        "independent_trial_count": None,
        "report_is_alpha_trial": False,
        "bootstrap_draws_and_engine_runs_are_not_independent_trials": True,
    }


def collect_saved_tables(
    reader: EvidenceReader, config: dict[str, Any], output: Path
) -> dict[str, Any]:
    r5, r4 = (config["source"][k] for k in ("r5", "r4"))
    saved = reader.json(f"{r5}/root_cause_audit.json")
    summaries = saved["summary"]
    raw_equity = reader.table(f"{r5}/portfolio_equity.parquet")
    require(
        all(r["symbols"] == config["symbols"] for r in raw_equity), "AQ-EVIDENCE-SLEEVE-COVERAGE"
    )
    equity = [
        {**r, "mode": "REDECIDE_FUNDED", "capital_mode": "FIVE_EQUAL_INITIAL_SLEEVES_NO_TRANSFERS"}
        for r in raw_equity
    ]
    daily = [r for r in equity if utc(r["time"]).time() == datetime.min.time()]
    period = config["period_binding"]["r5_long"]
    arguments: dict[str, Any] = {
        "start": period["start"],
        "end": period["terminal_account_boundary"],
        "initial_cash": decimal(config["initial_total_cash_usdt"]),
    }
    four_hour = audit_equity(equity, summaries, interval=timedelta(hours=4), **arguments)
    daily_checks = audit_equity(daily, summaries, **arguments)
    write_csv_exclusive(
        output / "readable/r5_daily_equity_utc.csv",
        [{k: v for k, v in r.items() if k != "symbols"} for r in daily],
    )
    quarterly = [
        {"arm": r["arm"], "cost": r["cost"], **q} for r in daily_checks for q in r["quarters"]
    ]
    write_csv_exclusive(output / "readable/r5_quarterly_returns.csv", quarterly)
    fills = reader.table(f"{r5}/execution_reason_attribution.parquet")
    new_fill_count = len(fills)
    fills += [
        {**r, "cost": "1"} for r in reader.table(f"{r4}/execution_reason_attribution.parquet")
    ]
    fill_checks = audit_fills(fills, summaries)
    write_csv_exclusive(
        output / "readable/r5_execution_reason_summary.csv",
        [
            {"arm": r["arm"], "cost": r["cost"], "reason": reason, "fills": count}
            for r in fill_checks
            for reason, count in r["reason_counts"].items()
        ],
    )
    sleeves = reader.table(f"{r5}/sleeve_results.parquet")
    sleeves += [
        {
            **r,
            "cost": r["cost_multiplier"],
            "cost_paid": r["total_cost"],
            "final_equity": r["final_cash"],
        }
        for r in reader.table(f"{r4}/sleeve_results.parquet")
        if r["mode"] == "REDECIDE_FUNDED" and r["cost_multiplier"] == "1"
    ]
    for summary in summaries:
        group = [r for r in sleeves if (r["arm"], r["cost"]) == (summary["arm"], summary["cost"])]
        require(
            sorted(r["symbol"] for r in group) == config["symbols"],
            "AQ-EVIDENCE-SLEEVE-SUMMARY-COVERAGE",
        )
        require(sum(r["fills"] for r in group) == summary["fills"], "AQ-EVIDENCE-SLEEVE-FILL-COUNT")
        for column, target in (
            ("cost_paid", "total_cost"),
            ("traded_notional", "traded_notional"),
            ("final_equity", "final_equity"),
        ):
            residual = sum((decimal(r[column]) for r in group), Decimal(0)) - decimal(
                summary[target]
            )
            require(abs(residual) <= MONEY_TOLERANCE, f"AQ-EVIDENCE-SLEEVE-SUM:{target}")
    shadows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in reader.table(f"{r5}/same_fill_cost_shadow.parquet"):
        require(r["funded"] is False, "AQ-EVIDENCE-SHADOW-MISLABELLED-FUNDED")
        shadows[r["arm"], r["symbol"]].append(r)
    for (arm, symbol), rows in shadows.items():
        require(
            {decimal(r["cost"]) for r in rows} == {Decimal(1), Decimal("1.5"), Decimal(2)},
            "AQ-EVIDENCE-SHADOW-COST-COVERAGE",
        )
        base = next(r for r in rows if decimal(r["cost"]) == 1)
        funded = next(
            r for r in sleeves if r["arm"] == arm and r["symbol"] == symbol and r["cost"] == "1"
        )
        require(
            abs(decimal(base["final_equity"]) - decimal(funded["final_equity"])) <= LEDGER_TOLERANCE
            and abs(decimal(base["total_cost"]) - decimal(funded["cost_paid"])) <= LEDGER_TOLERANCE,
            "AQ-EVIDENCE-SHADOW-BASE-FUNDED-BINDING",
        )
    shadow_checks = [
        {
            "arm": key[0],
            "symbol": key[1],
            **audit_cost_path(CostMode.SAME_FILL_SHADOW, rows, require_fill_identity=False),
        }
        for key, rows in sorted(shadows.items())
    ]
    by_key = {(r["arm"], r["cost"]): r for r in summaries}
    g1, f0 = by_key["G1", "1"], by_key["F0", "1"]
    wealth = decimal(g1["final_equity"]) - decimal(f0["final_equity"])
    saving = decimal(f0["total_cost"]) - decimal(g1["total_cost"])
    recent_prefix = config["source"]["recent"]
    recent_summary = reader.json(f"{recent_prefix}/summary.json")
    recent_rows = [
        r
        for r in reader.table(f"{recent_prefix}/portfolio_equity.parquet")
        if r["arm"] == "F3" and r["mode"] == "REDECIDE_FUNDED" and r["cost_multiplier"] == "1"
    ]
    recent_period = config["period_binding"]["recent_r4"]
    check_calendar_contract(
        recent_rows,
        start=recent_period["start"],
        end=recent_period["end_exclusive"],
        interval=timedelta(hours=4),
    )
    recent_target = next(
        r
        for r in recent_summary["portfolio"]
        if r["arm"] == "F3" and r["mode"] == "REDECIDE_FUNDED" and r["cost_multiplier"] == "1"
    )
    require(
        abs(decimal(recent_rows[-1]["equity"]) - decimal(recent_target["final_equity"]))
        <= MONEY_TOLERANCE,
        "AQ-EVIDENCE-RECENT-TERMINAL",
    )
    recent_daily = [r for r in recent_rows if utc(r["time"]).time() == datetime.min.time()]
    recent = {
        "strategy": "F3",
        "generation": "FROZEN_R4_RECENT_ONLY",
        "full_terminal_time": recent_rows[-1]["time"],
        "full_terminal_equity": recent_rows[-1]["equity"],
        "last_daily_time": recent_daily[-1]["time"],
        "last_daily_equity": recent_daily[-1]["equity"],
        "terminal_half_day_pnl_included": decimal(recent_rows[-1]["equity"])
        - decimal(recent_daily[-1]["equity"]),
        "not_g1_oos": True,
    }
    return {
        "arithmetic_audit": {
            "status": EvidenceStatus.DERIVED_ONLY,
            "input_format": "LOCAL_FROZEN_PARQUET",
            "compact_csv_received": False,
            "daily_and_quarter_checks": daily_checks,
            "four_hour_checks": four_hour,
            "derived_fill_checks": fill_checks,
            "r5_derived_fill_rows": new_fill_count,
            "r4_derived_fill_rows": len(fills) - new_fill_count,
            "sleeve_summary_checks": len(summaries),
            "recent_f3_separate": recent,
            "tolerances": {
                "money_usdt": MONEY_TOLERANCE,
                "return": "1e-10",
                "string_cost_components_usdt": "1e-18",
                "basis": "Binary64 saved portfolio/summary serialization; string costs checked separately. No silent rounding.",
            },
            "terminal_convention": "R5 test excludes end; saved paid terminal exit boundary at end is retained in account and preceding-quarter returns.",
            "capital_flow_and_raw_inventory_reconstruction": EvidenceStatus.NOT_VERIFIED,
        },
        "cost_mode_audit": {
            "modes": {
                "REDECIDE_FUNDED": "Cost can change decisions, cash and fills; no terminal monotonic assertion.",
                "FROZEN_ORDERS_FUNDED": "Fixed order intents do not fix fills or funding; no terminal monotonic assertion.",
                "SAME_FILL_SHADOW": "Same time/quantity/side/reference/inventory; adverse costs cannot improve shadow PnL; funding not asserted.",
            },
            "r5_frozen_orders_funded_trial": EvidenceStatus.NOT_COLLECTED,
            "same_fill_shadow_checks": shadow_checks,
            "g1_vs_f0": {
                "wealth_difference": wealth,
                "nominal_reported_cost_difference": saving,
                "cost_difference_fraction_of_wealth_difference": saving / wealth,
                "wealth_plus_reported_cost_difference": wealth - saving,
                "interpretation": "Each own path plus accounted costs; NOT a funded zero-cost replay or alpha.",
            },
        },
        "retained_churn": {
            "churn_all_passed": saved["churn_all_passed"],
            "churn_checks": saved["churn_checks"],
            "source": f"{r5}/root_cause_audit.json",
            "new_churn_experiment": False,
        },
    }


def audit_existing_files(root: Path, baseline: dict[str, Any]) -> dict[str, Any]:
    changes: list[str] = []
    for name, expected in baseline["files"].items():
        path = checked_path(root, name)
        if not path.is_file() or sha256_file(path) != expected["sha256"]:
            changes.append(name)
    require(not changes, f"AQ-EVIDENCE-PREEXISTING-FILES-CHANGED:{changes}")
    return {
        "status": EvidenceStatus.VERIFIED,
        "files_checked": len(baseline["files"]),
        "changed": changes,
        "protected_holdout_contents_read": False,
        "basis": "SHA256 before implementation and after audit",
    }


def safety_literals(reader: EvidenceReader, manifest: dict[str, Any]) -> dict[str, Any]:
    for source in (
        manifest["config"],
        yaml.safe_load(
            reader.path("configs/research/aegis_alpha_v5.yaml").read_text(encoding="utf-8")
        ),
    ):
        require(
            source["production_policy"] == "CASH" and all(source[k] is False for k in LOCKS),
            "AQ-EVIDENCE-FROZEN-SAFETY-STATE",
        )
    tree = ast.parse(
        reader.path("src/aegisquant/bootstrap/live_lock.py").read_text(encoding="utf-8")
    )
    literals = {
        n.target.id: ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.AnnAssign)
        and isinstance(n.target, ast.Name)
        and n.value is not None
        and n.target.id in {"LIVE_TRADING", "ORDER_SUBMISSION_ENABLED", "LIVE_ADAPTERS"}
    }
    require(
        literals == {"LIVE_TRADING": False, "ORDER_SUBMISSION_ENABLED": False, "LIVE_ADAPTERS": ()},
        "AQ-EVIDENCE-LIVE-LOCK-CHANGED",
    )
    return literals


def seal_output(output: Path) -> None:
    files = {
        p.relative_to(output).as_posix(): {"sha256": sha256_file(p), "bytes": p.stat().st_size}
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    write_json_exclusive(
        output / "OUTPUT_MANIFEST.json",
        {
            "schema_version": "immutable-evidence-output-v1",
            "files": files,
            "content_sha256": canonical_sha256(files),
            "self_excluded": "OUTPUT_MANIFEST.json",
            "write_policy": "EXCLUSIVE_GENERATION_NO_REOPEN",
        },
    )


def validate_test_receipts(root: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    current = {name: sha256_file(checked_path(root, name)) for name in NEW_FILES}
    latest = {r["check"]: r for r in records if "check" in r}
    for name in ("pytest", "ruff", "format", "pyright"):
        require(
            name in latest and latest[name]["exit_code"] == 0,
            f"AQ-EVIDENCE-VALIDATION-NOT-PASSED:{name}",
        )
        require(
            latest[name]["source_sha256"] == current,
            f"AQ-EVIDENCE-VALIDATION-SOURCE-CHANGED:{name}",
        )
    command = latest["pytest"]["command"]
    require(all(name in command for name in NEW_FILES[3:5]), "AQ-EVIDENCE-PURE-TEST-FILES-NOT-RUN")
    return {
        "status": EvidenceStatus.VERIFIED,
        "source_sha256": current,
        "latest_passed_checks": list(latest),
        "pytest_stdout": latest["pytest"]["stdout"],
    }


def run_report(
    root: Path, config: dict[str, Any], preflight: Path, git_state: dict[str, Any]
) -> Path:
    validate_config(config)
    require(
        git_state["branch"] == "main" and git_state["head"] == BASE, "AQ-EVIDENCE-WORKSPACE-BASE"
    )
    baseline_path = checked_path(preflight, "baseline_workspace.json")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    require(
        baseline["branch"] == "main"
        and baseline["head"] == BASE
        and Path(baseline["root"]).resolve() == root.resolve(),
        "AQ-EVIDENCE-PREFLIGHT-BASE",
    )
    output = claim_output(
        root,
        config["output"],
        frozen_roots=[root / config["source"][k] for k in ("r5", "r4", "recent")],
    )
    counters: dict[str, int] = dict.fromkeys(ZERO_BUDGETS, 0)
    reader = EvidenceReader(root)
    run_id = config["generation"] + ":REPORT"
    try:
        with registered_run(  # noqa: SIM117 -- journal ERROR must be appended after guard exits.
            output, run_id, planned_run_ids=[run_id], bindings={"kind": config["kind"]}
        ):
            with zero_budget_guard(output, root, counters):
                write_json_exclusive(
                    output / "preregistration.json",
                    {
                        "registered_at": datetime.now(UTC),
                        "config": config,
                        "kind": config["kind"],
                        "planned_run_ids": [run_id],
                    },
                )
                for name in (
                    "baseline_workspace.json",
                    "workspace_before.patch",
                    "version_graph.txt",
                    "remote_main.txt",
                    "test_commands_and_results.txt",
                    "validation_records.json",
                ):
                    source = checked_path(preflight, name)
                    target = (
                        output
                        / (
                            "validation"
                            if name in {"test_commands_and_results.txt", "validation_records.json"}
                            else "preflight"
                        )
                        / name
                    )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        stream.write(source.read_bytes())
                test_receipts = validate_test_receipts(
                    root,
                    json.loads(
                        (output / "validation/validation_records.json").read_text(encoding="utf-8")
                    ),
                )
                validate_before = audit_existing_files(root, baseline)
                manifest, bindings = verify_sources(reader, config)
                source = config["source"]
                compact = (
                    load_evidence_manifest(Path(source["compact_directory"]))
                    if source["compact_directory"]
                    else {"status": EvidenceStatus.NOT_RECEIVED, "listed_files_verified": 0}
                )
                full_path = checked_path(root, source["full_bundle_filename"])
                full = verify_full_bundle(
                    full_path, source["full_bundle_sha256_expected_from_taskbook"]
                )
                bindings.update(
                    compact_manifest=compact,
                    full_bundle=full,
                    compact_package_version_map=EvidenceStatus.NOT_RECEIVED,
                    provided_patch=EvidenceStatus.NOT_RECEIVED,
                    current_workspace_patch_sha256=sha256_file(
                        output / "preflight/workspace_before.patch"
                    ),
                )
                write_json_exclusive(output / "source_and_version_bindings.json", bindings)
                products = collect_saved_tables(reader, config, output)
                for name in ("arithmetic_audit", "cost_mode_audit"):
                    write_json_exclusive(output / f"{name}.json", products[name])
                old_stats = f"{source['r5']}/paired_statistics.json"
                require(
                    sha256_file(reader.path(old_stats)) == source["r5_statistics_sha256"],
                    "AQ-EVIDENCE-STATISTICS-PIN",
                )
                stats = statistics_identity(
                    reader.json(old_stats), manifest["config"]["statistics"]
                )
                write_json_exclusive(output / "statistics_identity.json", stats)
                cases = synthetic_resize_cases(reader, manifest, source["r5"])
                write_json_exclusive(output / "resize_semantics_cases.json", cases)
                history = failure_history(reader, manifest, config)
                write_json_exclusive(output / "failure_history_index.json", history)
                gaps = [
                    {
                        "item": name,
                        "status": EvidenceStatus.NOT_RECEIVED,
                        "reason": "Not supplied in this workspace; no package verification claimed.",
                    }
                    for name in (
                        "README_FIRST.md",
                        "VERSION_MAP.json",
                        "FULL_EVIDENCE_REFERENCE.json",
                        "changes_since_github_main.patch",
                        "compact MANIFEST/readable CSV",
                        source["full_bundle_filename"],
                    )
                ]
                gaps += [
                    {"item": name, "status": EvidenceStatus.NOT_COLLECTED, "reason": reason}
                    for name, reason in (
                        (
                            "recent G1 trial",
                            "Frozen recent arms contain F3, not G1; no such G1 experiment was executed.",
                        ),
                        (
                            "real historical fees/rules/L2/latency",
                            "Current execution is explicitly a proxy.",
                        ),
                        (
                            "real PIT universe",
                            "Fixed surviving five assets; PIT tests are synthetic.",
                        ),
                        (
                            "complete independent trial history",
                            "Global history remains incomplete; DSR/PBO and trial count stay null.",
                        ),
                        (
                            "unused >=12 month final holdout",
                            "NOT_ALLOCATED; protected paths were not opened.",
                        ),
                    )
                ]
                gaps += [
                    {
                        "item": name,
                        "status": EvidenceStatus.NOT_VERIFIED,
                        "reason": "Saved raw result/trace hashes exist, but original ledger reconstruction and complete semantic fields are not verified.",
                        "required_hash_inventory": "resize_semantics_cases.json#original_trace_inventory",
                    }
                    for name in cases["unverified_topics"]
                ]
                write_json_exclusive(
                    output / "evidence_gaps.json",
                    {"gaps": gaps, "full_raw_bundle_received": full["full_raw_bundle_received"]},
                )
                locks = safety_literals(reader, manifest)
                for name in (
                    old_stats,
                    f"{source['r5']}/root_cause_audit.json",
                    source["arithmetic_reference"],
                ):
                    path = reader.path(name, "ORIGINAL_SAVED_REPORT_COPIED_BYTE_FOR_BYTE")
                    target = output / "sources" / path.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        stream.write(path.read_bytes())
                reference = reader.json(source["arithmetic_reference"])
                require(
                    sha256_file(reader.path(source["arithmetic_reference"]))
                    == source["arithmetic_reference_sha256"],
                    "AQ-EVIDENCE-REFERENCE-HASH",
                )
                for key, value in products["cost_mode_audit"]["g1_vs_f0"].items():
                    if key in reference["g1_vs_f0"]:
                        require(
                            abs(value - decimal(reference["g1_vs_f0"][key])) <= MONEY_TOLERANCE,
                            "AQ-EVIDENCE-REFERENCE-ARITHMETIC-CONFLICT",
                        )
                preservation = audit_existing_files(root, baseline)
                write_json_exclusive(
                    output / "safety_and_budget_audit.json",
                    {
                        "authorized": config["budgets"],
                        "actual": {"report_jobs": 1, **counters},
                        "report_attempts_including_retained_failures": history[
                            "report_attempts_including_current"
                        ],
                        "retained_failed_report_jobs": len(history["review_report_failures"]),
                        "report_budget_scope": "ONE_EXCLUSIVE_REPORT_JOB_PER_GENERATION",
                        "network_accounts_used": False,
                        "runtime_forbidden_call_guard": True,
                        "safety_literals": locks,
                        "existing_files_before_audit": validate_before,
                        "existing_files_after_audit": preservation,
                        "new_alpha_trials": 0,
                        "validation_receipts": test_receipts,
                        "significance_recalculations": 0,
                        "research_conclusion": "NO_PROVEN_ALPHA",
                        "production_policy": "CASH",
                        **dict.fromkeys(LOCKS, False),
                    },
                )
                write_json_exclusive(
                    output / "evidence_contract.json",
                    {
                        "scope": config["scope"],
                        "kind": config["kind"],
                        "states": [s.value for s in EvidenceStatus],
                        "reads": reader.reads,
                        "retained_churn": products["retained_churn"],
                        "derived_exports": "New Decimal arithmetic exports from saved Parquet; NOT received compact CSVs.",
                        "full_raw_bundle_received": full["full_raw_bundle_received"],
                        "row_level_market_or_order_reconstruction": EvidenceStatus.NOT_VERIFIED,
                        "recent_g1": EvidenceStatus.NOT_COLLECTED,
                    },
                )
                patch = "".join(
                    "".join(
                        difflib.unified_diff(
                            [],
                            checked_path(root, name)
                            .read_text(encoding="utf-8")
                            .splitlines(keepends=True),
                            fromfile="/dev/null",
                            tofile="b/" + name,
                        )
                    )
                    for name in NEW_FILES
                )
                with (output / "changes_this_batch.patch").open(
                    "x", encoding="utf-8", newline="\n"
                ) as stream:
                    stream.write(patch)
                write_json_exclusive(
                    output / "changed_files.json",
                    {
                        "new_files": {
                            name: sha256_file(checked_path(root, name)) for name in NEW_FILES
                        },
                        "modified_preexisting_files": [],
                        "git_at_audit": git_state,
                        "commits_created": 0,
                        "pushes": 0,
                        "branches_created": 0,
                    },
                )
                render_report(output, config, products, stats, cases, preservation)
    except BaseException as error:
        write_json_exclusive(
            output / "failure.json",
            {
                "status": "FAILED_RETAINED_DO_NOT_REOPEN",
                "error": f"{type(error).__name__}: {error}",
                "actual_attempts": counters,
                "research_conclusion": "NO_PROVEN_ALPHA",
                "production_policy": "CASH",
            },
        )
        seal_output(output)
        raise
    seal_output(output)
    return output


def render_report(
    output: Path,
    config: dict[str, Any],
    products: dict[str, Any],
    stats: dict[str, Any],
    cases: dict[str, Any],
    preservation: dict[str, Any],
) -> None:
    arithmetic = products["arithmetic_audit"]
    difference = products["cost_mode_audit"]["g1_vs_f0"]
    g1 = next(r for r in arithmetic["derived_fill_checks"] if r["arm"] == "G1" and r["cost"] == "1")
    f0 = next(r for r in arithmetic["derived_fill_checks"] if r["arm"] == "F0" and r["cost"] == "1")
    validation = json.loads(
        (output / "validation/validation_records.json").read_text(encoding="utf-8")
    )
    lines = [
        "# R5 B0 与 B1 只读／合成证据契约审计",
        "",
        "**NO_PROVEN_ALPHA / CASH。ML、纸面准入、实盘及订单提交全部关闭。**",
        "",
        f"本批 generation：`{config['generation']}`。实际读取已提交基线 `{BASE}` ＋本地冻结 R5 v3 源码与保存表；近期证据始终是 R4 F3。",
        "历史策略回放 0、真实模型拟合 0、真实校准拟合 0、最终留出访问 0、真实订单 0；没有重算显著性。",
        f"报告累计尝试 {len(config.get('prior_report_failures', [])) + 1} 次，每个独占 generation 使用 1 个报告槽；此前失败均保留并纳入 failure_history_index.json。",
        "原始市场逐行审计、逐单资金账本重建和完整 trace→order→fill 联结未完成（NOT_VERIFIED）。",
        "",
        "## 实际证据范围",
        "",
        "20260909 精简包、版本图、包补丁、MANIFEST、原 readable CSV 及完整 ZIP 未收到（NOT_RECEIVED）。随附算术审计 JSON 是历史审阅记录，本批未冒称完成其中的 2,465 文件包验证。",
        "使用本地冻结 Parquet 和 JSON 完成 Decimal 算术核对；新 readable CSV 仅是本批派生导出。原 result.json.gz 与 trace 文件存在，已核对哈希／schema，但未解压重建原始逐单凭证。完整新 trace 字段也未保存。",
        "G1 近期试验没有执行，状态为 NOT_COLLECTED；近期 F3 没有改名、拼接或变为 G1 样本外。",
        "",
        "## 算术、成本与统计",
        "",
        f"- {len(arithmetic['daily_and_quarter_checks'])} 个 arm/cost 组合共同 UTC 日历与四小时日历、50,000 USDT 初始资金、cash + inventory = equity、终值和 14 季度复合核对通过；空仓日及付费终止边界保留。",
        f"- R5 派生成交 {arithmetic['r5_derived_fill_rows']} 行，R4 {arithmetic['r4_derived_fill_rows']} 行；所有组合的成交数、普通调仓理由数、名义金额及成本对齐保存汇总。G1 为 {g1['fills']} fills、{g1['ordinary_resize_fills']} 次普通 resize，restore={g1['reason_counts'].get('ORDINARY_RISK_RESTORE', 0)}；F0 为 {f0['ordinary_resize_fills']}/{f0['fills']}。",
        f"- G1−F0 终值差 `{difference['wealth_difference']}` USDT；账面成本节省 `{difference['nominal_reported_cost_difference']}`；各自路径终值加回成本之差 `{difference['wealth_plus_reported_cost_difference']}`。最后一项不是零成本资金回放或 alpha。",
        "- 三种成本模式分别命名；funded 模式不要求费用越高终值越低。35 个 same-fill 影子分组的嵌套成本和净值恒等式通过，实际 fill-path 身份及资金可实现性仍未验证。",
        f"- 原 {stats['family_size']} 个比较及其 raw/adjusted p、CI、bootstrap 元数据完整保留。p 值对应日均收益差；CI 对应未作多重校正的复合收益差。未重采样；DSR/PBO 与独立 trial 数均为 null。",
        "- G1 原五项 churn 门槛通过与 NO_PROVEN_ALPHA 同时保留；盈利季度 6/14、Holm 未通过仍是旧研究结论。",
        "- 容差提前固定：保存 Float64 表的资金 1e-8 USDT、收益 1e-10；原字符串成本分项 1e-18 USDT。残差逐组输出，无静默取整。无原始现金流账本不能凭余额恒等式排除历史额外入金。",
        "",
        "## G1 合成机制",
        "",
        f"方差效用 `{cases['variance_case']['benefit_nav']}` NAV；合成 16bps 的单腿成本 `.000112` NAV，成本／效用 `{cases['variance_case']['cost_over_benefit']}`。增大乘在收益侧的 lambda 放宽门槛；移动远离 raw 的效用截为 0。16bps 没有被标作历史实测费用。",
        "时钟表遵循冻结语义：到期且具备持仓／行情／趋势、无 pending 的复核先更新 review；成本否决也消耗该次复核。SUBMIT 更新 review，REJECT／FILL／CANCEL 本身不更新。pending 不凭空删除，硬退出仍受订单协调与真实可成交条件约束。",
        "raw/smoothed/proposed 冲突、全部门槛漏斗、二次取整、gap 后所有指标 warmup、硬退出与尾部共同冲击列为待验证；不补造拒绝数或最差事件日期。",
        "",
        "## 验证与保全",
        "",
        f"本批实际命令及全部结果见 `validation/test_commands_and_results.txt`，共记录 {len(validation)} 次检查调用；不是旧 1,188 项日志。仅执行新增纯测试及针对新文件的静态检查，未运行全仓 pytest。",
        f"实施前后 {preservation['files_checked']} 个已有文件 SHA256 保持不变。用户 tracked/untracked 改动保留；没有 reset、clean、分支创建、提交或推送。新增文件与 diff 见 `changed_files.json` / `changes_this_batch.patch`。",
        "现有失败代次、失败配置及 H3/H10/R24/R72 全部保留。错误会消费独占 generation 并保存日志；输出 manifest 以 exclusive create 封存，重用目录被拒绝。",
        "本批 v1 因新审计器把派生 filled_qty 误当非负量而失败。冻结源码约定 BUY 为正、SELL 为负，名义额为正；v2 只修审计契约并增加买卖方向／零量反例，历史策略及源表不变。v1 是审计工程失败，不是新的 alpha 试验。"
        if config.get("prior_report_failures")
        else "没有前代报告失败。",
        "",
        "## 缺口与停止",
        "",
        "包级版本／manifest 缺件见 evidence_gaps；现有原始文件只做 hash/schema 核对，完整原始账本联结和新字段仍未验证。真实历史费用、规则、盘口、延迟、PIT、全量独立试验史和未使用留出仍缺证据。",
        "最小后续是另批提供精简包／完整包，核对包身份后只读联结现有原始凭证；若需要产生新的 trace 字段或历史机制消融，必须另获授权并使用新 generation。本批不进入该工作。",
        "**本批完成即停止。最终仍为 NO_PROVEN_ALPHA / CASH，所有准入与订单开关关闭。**",
        "",
    ]
    with (output / "report.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines))
