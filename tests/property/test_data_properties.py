"""Property tests for deterministic manifests and PIT anti-leakage."""

from datetime import timedelta

import pyarrow as pa
from hypothesis import given, settings
from hypothesis import strategies as st

from aegisquant.data.hashing import canonical_sha256
from aegisquant.data.pit import point_in_time_join
from tests.p02.helpers import NOW


@given(st.dictionaries(st.text(min_size=1, max_size=12), st.integers(), max_size=12))
def test_canonical_hash_is_independent_of_mapping_insertion_order(
    payload: dict[str, int],
) -> None:
    reversed_payload = dict(reversed(tuple(payload.items())))
    assert canonical_sha256(payload) == canonical_sha256(reversed_payload)


@settings(max_examples=30, deadline=None)
@given(
    event_offset=st.integers(min_value=-3600, max_value=0),
    available_offset=st.integers(min_value=-3600, max_value=3600),
)
def test_pit_property_never_exposes_future_available_fact(
    event_offset: int, available_offset: int
) -> None:
    decisions = pa.table({"asset": ["BTC"], "decision_time": [NOW]})
    facts = pa.table(
        {
            "asset": ["BTC"],
            "event_time": [NOW + timedelta(seconds=event_offset)],
            "available_time": [NOW + timedelta(seconds=available_offset)],
            "value": [42],
        }
    )
    row = point_in_time_join(decisions=decisions, facts=facts, keys=("asset",)).to_pylist()[0]
    if available_offset <= 0:
        assert row["fact_value"] == 42
    else:
        assert row["fact_value"] is None
