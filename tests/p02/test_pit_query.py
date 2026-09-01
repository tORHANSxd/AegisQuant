"""Point-in-time and hardened DuckDB query tests."""

from datetime import timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aegisquant.data.duckdb_security import secure_duckdb_connection
from aegisquant.data.pit import point_in_time_join
from aegisquant.data.query import DuckDbQueryLayer
from tests.p02.helpers import NOW


def test_pit_join_filters_future_availability_revision_and_engagement() -> None:
    decisions = pa.table(
        {
            "instrument_id": ["BTC-USDT", "BTC-USDT"],
            "decision_time": [NOW, NOW + timedelta(hours=1)],
        }
    )
    facts = pa.table(
        {
            "instrument_id": ["BTC-USDT"] * 4,
            "event_time": [
                NOW - timedelta(hours=1),
                NOW - timedelta(minutes=30),
                NOW - timedelta(minutes=40),
                NOW - timedelta(minutes=35),
            ],
            "available_time": [
                NOW - timedelta(minutes=55),
                NOW + timedelta(minutes=5),
                NOW - timedelta(minutes=35),
                NOW - timedelta(minutes=30),
            ],
            "revision_time": [
                NOW - timedelta(minutes=50),
                NOW + timedelta(minutes=10),
                NOW + timedelta(minutes=10),
                NOW - timedelta(minutes=25),
            ],
            "engagement_snapshot_time": [
                NOW - timedelta(minutes=45),
                NOW + timedelta(minutes=15),
                NOW - timedelta(minutes=30),
                NOW + timedelta(minutes=30),
            ],
            "value": ["visible", "available-later", "revised-later", "engagement-later"],
        }
    )
    result = point_in_time_join(
        decisions=decisions,
        facts=facts,
        keys=("instrument_id",),
    ).to_pylist()
    assert result[0]["fact_value"] == "visible"
    assert result[1]["fact_value"] == "available-later"


def test_pit_identifier_injection_is_rejected() -> None:
    decisions = pa.table({"instrument_id": ["BTC"], "decision_time": [NOW]})
    facts = pa.table(
        {
            "instrument_id": ["BTC"],
            "event_time": [NOW],
            "available_time": [NOW],
        }
    )
    with pytest.raises(ValueError, match="invalid SQL identifier"):
        point_in_time_join(
            decisions=decisions,
            facts=facts,
            keys=('instrument_id"; DROP TABLE facts; --',),
        )


def test_point_in_time_join_excludes_content_deleted_by_decision_time() -> None:
    decisions = pa.table(
        {
            "content_id": ["post-1", "post-1"],
            "decision_time": [NOW + timedelta(minutes=30), NOW + timedelta(hours=2)],
        }
    )
    facts = pa.table(
        {
            "content_id": ["post-1"],
            "event_time": [NOW],
            "available_time": [NOW + timedelta(minutes=1)],
            "deleted_time": [NOW + timedelta(hours=1)],
            "value": ["visible-before-delete"],
        }
    )
    result = point_in_time_join(decisions=decisions, facts=facts, keys=("content_id",))
    assert result.column("fact_value").to_pylist() == ["visible-before-delete", None]


def test_query_layer_allows_only_local_parquet_and_counts_without_materializing(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    inside_path = allowed / "events.parquet"
    outside_path = outside / "events.parquet"
    table = pa.table({"event_id": ["a", "b", "c"], "value": [1, 2, 3]})
    with pq.ParquetWriter(inside_path, table.schema) as writer:
        writer.write_table(table)
    with pq.ParquetWriter(outside_path, table.schema) as writer:
        writer.write_table(table)

    layer = DuckDbQueryLayer(allowed_root=allowed)
    assert layer.count_rows((inside_path,)) == 3
    assert layer.read((inside_path,), columns=("value",)).column_names == ["value"]
    with pytest.raises(ValueError, match="AQ-DATA-QUERY-PATH-ESCAPE"):
        layer.count_rows((outside_path,))
    with pytest.raises(ValueError, match="invalid column name"):
        layer.read((inside_path,), columns=("value; DROP TABLE events",))


def test_duckdb_security_configuration_is_locked(tmp_path: Path) -> None:
    connection = secure_duckdb_connection(allowed_root=tmp_path)
    try:
        enabled = connection.execute("SELECT current_setting('enable_external_access')").fetchone()
        assert enabled == (False,)
        with pytest.raises(Exception, match=r"locked|configuration"):
            connection.execute("SET enable_external_access = true")
    finally:
        connection.close()
