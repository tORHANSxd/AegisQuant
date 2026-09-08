# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Export the saved portfolio curves as a standalone research chart and CSV."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import polars as pl

matplotlib.use("Agg")
import matplotlib.pyplot as plt

STYLES = {
    "B1": ("Quarterly buy & hold", "#9ba8b8"),
    "B3": ("Transparent trend", "#1984a3"),
    "B5": ("XGBoost filter", "#d48132"),
    "LIGHTGBM": ("LightGBM filter", "#9d6fbb"),
    "ELASTIC_NET": ("Elastic Net filter", "#13856c"),
    "B7": ("XGBoost + risk sizing", "#d65a70"),
}


def main() -> None:
    parent = Path(__file__).resolve().parents[1] / "artifacts/alpha_v4_multi_asset"
    source = pl.read_parquet(parent / "summary/portfolio_mtm_equity.parquet")
    expected = pl.read_parquet(parent / "summary/aggregate_stress.parquet")
    fig, (axis, downside) = plt.subplots(
        2,
        1,
        figsize=(12, 8),
        sharex=True,
        height_ratios=(2, 1),
        gridspec_kw={"hspace": 0.11},
        layout="constrained",
    )
    fig.set_facecolor("#f7f9fc")
    rows: list[dict[str, Any]] = []
    for level, (label, color) in STYLES.items():
        frame = source.filter((pl.col("level") == level) & (pl.col("scenario") == "cost_1"))
        times: list[Any] = []
        linked = [1.0]
        for fold in sorted(frame["fold_id"].unique().to_list()):
            part = frame.filter(pl.col("fold_id") == fold).sort("time")
            values = np.asarray([float(value) for value in part["equity"]])
            if not times:
                times.append(part["time"][0])
            times.extend(part["time"].to_list()[1:])
            linked.extend((linked[-1] * values[1:] / values[0]).tolist())
        nav = np.asarray(linked)
        reported = expected.filter(
            (pl.col("symbol") == "EQUAL_FIVE")
            & (pl.col("level") == level)
            & (pl.col("scenario") == "cost_1")
        )["net_compound_return"][0]
        if abs(nav[-1] - 1 - reported) > 1e-10:
            raise ValueError("plotted path differs from the reported compounded return")
        drawdown = nav / np.maximum.accumulate(nav) - 1
        axis.plot(times, nav, label=f"{label}  {reported:+.1%}", color=color, linewidth=1.7)
        if level in {"B1", "B3", "ELASTIC_NET"}:
            downside.plot(times, drawdown * 100, color=color, linewidth=1.4)
        rows.extend(
            {"level": level, "time": time, "normalized_nav": float(value), "drawdown": float(dd)}
            for time, value, dd in zip(times, nav, drawdown, strict=True)
        )
    axis.set_title(
        "Five-asset portfolio: BTC / ETH / BNB / SOL / XRP", loc="left", fontsize=17, pad=16
    )
    axis.set_ylabel("Quarterly-linked net asset value")
    axis.legend(loc="upper left", fontsize=9, frameon=False, ncol=2)
    downside.set_ylabel("Drawdown (%)")
    downside.set_xlabel("2022-04 to 2025-10 | 14 calendar test folds | Base cost assumptions")
    for panel in (axis, downside):
        panel.set_facecolor("white")
        panel.grid(alpha=0.2, linewidth=0.7)
        panel.spines[["top", "right"]].set_visible(False)
    fig.suptitle(
        "Fixed model settings; equal funded sleeves each quarter; all entry and exit costs included.\n"
        "Development evidence on surviving assets, with proxy execution costs. No proven trading alpha.",
        fontsize=10,
        color="#526070",
        x=0.09,
        ha="left",
        y=1.04,
    )
    fig.savefig(parent / "summary/portfolio_performance.png", dpi=160, bbox_inches="tight")
    fig.savefig(parent / "summary/portfolio_performance.svg", bbox_inches="tight")
    pl.DataFrame(rows).write_csv(parent / "summary/portfolio_chart_data.csv")
    plt.close(fig)


if __name__ == "__main__":
    main()
