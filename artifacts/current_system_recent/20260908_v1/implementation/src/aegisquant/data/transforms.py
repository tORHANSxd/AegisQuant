"""Bounded Arrow/Polars conversion and lazy transformation helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

import polars as pl
import pyarrow as pa

LazyTransform = Callable[[pl.LazyFrame], pl.LazyFrame]


class _PolarsFromArrow(Protocol):
    def __call__(self, data: pa.Table, *, rechunk: bool) -> pl.DataFrame | pl.Series: ...


def arrow_to_lazy(table: pa.Table) -> pl.LazyFrame:
    """Expose an Arrow table as a lazy Polars plan."""
    frame = cast(_PolarsFromArrow, getattr(pl, "from_arrow"))(  # noqa: B009
        table, rechunk=False
    )
    if not isinstance(frame, pl.DataFrame):
        raise TypeError("Arrow Table did not produce a Polars DataFrame")
    return frame.lazy()


def collect_lazy(transform: pl.LazyFrame) -> pa.Table:
    """Collect a lazy plan through Polars streaming and return Arrow."""
    return transform.collect(engine="streaming").to_arrow()


def transform_arrow(table: pa.Table, transform: LazyTransform) -> pa.Table:
    """Run one caller-supplied pure lazy transformation."""
    return collect_lazy(transform(arrow_to_lazy(table)))
