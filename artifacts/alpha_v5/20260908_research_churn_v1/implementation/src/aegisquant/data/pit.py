"""Point-in-time joins that reject unavailable facts, revisions, and engagement."""

from __future__ import annotations

import re

import pyarrow as pa

from aegisquant.data.duckdb_security import secure_duckdb_connection

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _identifier(value: str) -> str:
    if IDENTIFIER_RE.fullmatch(value) is None:
        raise ValueError(f"invalid SQL identifier: {value}")
    return f'"{value}"'


def point_in_time_join(
    *,
    decisions: pa.Table,
    facts: pa.Table,
    keys: tuple[str, ...],
    decision_time_column: str = "decision_time",
    fact_event_time_column: str = "event_time",
    available_time_column: str = "available_time",
    revision_time_column: str | None = "revision_time",
    engagement_snapshot_column: str | None = "engagement_snapshot_time",
    deleted_time_column: str | None = "deleted_time",
) -> pa.Table:
    """Join each decision to the latest fact that was actually visible at that time."""
    for name in (*keys, decision_time_column, fact_event_time_column, available_time_column):
        _identifier(name)
    required_decision = {*keys, decision_time_column}
    required_fact = {*keys, fact_event_time_column, available_time_column}
    if missing := required_decision - set(decisions.column_names):
        raise ValueError(f"decision columns missing: {sorted(missing)}")
    if missing := required_fact - set(facts.column_names):
        raise ValueError(f"fact columns missing: {sorted(missing)}")
    optional_filters: list[str] = []
    ordering = [
        f"f.{_identifier(fact_event_time_column)} DESC",
        f"f.{_identifier(available_time_column)} DESC",
    ]
    if revision_time_column is not None and revision_time_column in facts.column_names:
        _identifier(revision_time_column)
        optional_filters.append(
            f"(f.{_identifier(revision_time_column)} IS NULL OR "
            f"f.{_identifier(revision_time_column)} <= d.{_identifier(decision_time_column)})"
        )
        ordering.append(f"f.{_identifier(revision_time_column)} DESC NULLS LAST")
    if engagement_snapshot_column is not None and engagement_snapshot_column in facts.column_names:
        _identifier(engagement_snapshot_column)
        optional_filters.append(
            f"(f.{_identifier(engagement_snapshot_column)} IS NULL OR "
            f"f.{_identifier(engagement_snapshot_column)} <= d.{_identifier(decision_time_column)})"
        )
    if deleted_time_column is not None and deleted_time_column in facts.column_names:
        _identifier(deleted_time_column)
        optional_filters.append(
            f"(f.{_identifier(deleted_time_column)} IS NULL OR "
            f"f.{_identifier(deleted_time_column)} > d.{_identifier(decision_time_column)})"
        )
    key_filters = [f"f.{_identifier(key)} = d.{_identifier(key)}" for key in keys]
    time_filters = [
        f"f.{_identifier(fact_event_time_column)} <= d.{_identifier(decision_time_column)}",
        f"f.{_identifier(available_time_column)} <= d.{_identifier(decision_time_column)}",
    ]
    fact_columns = [column for column in facts.column_names if column not in keys]
    fact_projection = ", ".join(
        f"f.{_identifier(column)} AS {_identifier(f'fact_{column}')}" for column in fact_columns
    )
    projection = "d.*" if not fact_projection else f"d.*, {fact_projection}"
    predicates = " AND ".join([*key_filters, *time_filters, *optional_filters])
    # Every interpolated identifier passed the strict IDENTIFIER_RE check above.
    query = " ".join(
        (
            # Dynamic identifiers passed IDENTIFIER_RE before query assembly.
            f"SELECT {projection}",  # nosec B608
            "FROM decisions AS d",
            "LEFT JOIN LATERAL (SELECT * FROM facts AS candidate",
            f"WHERE {predicates.replace('f.', 'candidate.')}",
            f"ORDER BY {', '.join(ordering).replace('f.', 'candidate.')}",
            "LIMIT 1) AS f ON TRUE",
            f"ORDER BY d.{_identifier(decision_time_column)}, "
            f"{', '.join(f'd.{_identifier(key)}' for key in keys)}",
        )
    )
    connection = secure_duckdb_connection()
    try:
        connection.register("decisions", decisions)
        connection.register("facts", facts)
        return connection.execute(query).to_arrow_table()
    finally:
        connection.close()
