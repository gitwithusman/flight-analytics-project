"""Matplotlib drawing functions for the travel / operations screens.

Each function draws onto a given ``Figure`` (so the GUI can embed it and the
report generator can reuse it), with a title, labelled axes, readable dates and
sample-size notes. They never invent data: callers pass already-computed frames.
"""

from __future__ import annotations

from typing import Optional, Sequence  # noqa: F401

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from . import palette as P
from .visualizations import GRID, MUTED, TEXT

C1, C2, C3, C4, WARN, ERR = P.COBALT, P.TEAL, P.NAVY_SOFT, "#6F86A8", P.WARNING, P.ERROR


def _ax(fig: Figure, title: str, xlabel: str = "", ylabel: str = "", grid: str = "y"):
    ax = fig.add_subplot(111)
    ax.set_facecolor("none")
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color=TEXT, pad=8)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8.5, length=0)
    if grid:
        ax.grid(axis=grid, color=GRID, lw=0.8)
        ax.set_axisbelow(True)
    return ax


def _note(ax, text: str, loc: str = "upper right") -> None:
    x, ha = (0.98, "right") if "right" in loc else (0.02, "left")
    y, va = (0.96, "top") if "upper" in loc else (0.04, "bottom")
    ax.text(x, y, text, transform=ax.transAxes, ha=ha, va=va, fontsize=8, color=MUTED,
            bbox=dict(boxstyle="round,pad=0.3", fc=P.SURFACE_ALT, ec=P.BORDER, lw=0.8))


def _dates(ax) -> None:
    loc = mdates.AutoDateLocator(minticks=3, maxticks=7)
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))


def empty(fig: Figure, message: str) -> None:
    ax = fig.add_subplot(111)
    ax.axis("off")
    ax.text(0.5, 0.5, message, ha="center", va="center", color=MUTED, fontsize=10, wrap=True, transform=ax.transAxes)


# --------------------------------------------------------------------------- delays / status
def delay_by_group(fig: Figure, tbl: pd.DataFrame, label_col: str, title: str, top: int = 10) -> None:
    if tbl.empty:
        return empty(fig, "No delay data for the selected filters\n(groups need at least 3 flights that report a delay).")
    t = tbl.head(top).iloc[::-1]
    ax = _ax(fig, title, "Mean reported delay (minutes)", "", grid="x")
    y = np.arange(len(t))
    ax.barh(y, t["avg_delay_min"], color=WARN, height=0.55)
    for yi, (m, p, n) in enumerate(zip(t["avg_delay_min"], t["delayed_pct"], t["delay_values"])):
        ax.text(m, yi, f"  {m:.1f} min | {p:.0f}% delayed | n={n}", va="center", fontsize=7.5, color=MUTED, clip_on=False)
    ax.set_yticks(y, t[label_col].astype(str), fontsize=8.5)
    ax.set_xlim(0, max(t["avg_delay_min"].max() * 2.4, 1))


def delay_distribution(fig: Figure, delays: pd.Series) -> None:
    d = delays.dropna()
    if d.empty:
        return empty(fig, "No flights in the current selection report a delay value.")
    pos = d[d > 0]
    ax = _ax(fig, "Reported delay distribution", "Delay (minutes)", "Flights")
    bins = np.arange(0, max(d.max(), 10) + 5, 5)
    ax.hist(d, bins=bins, color=C1, edgecolor="white", lw=0.6)
    if len(pos):
        ax.axvline(pos.median(), color=WARN, lw=1.6, label=f"Median of delayed flights {pos.median():.0f} min")
        ax.legend(frameon=False, fontsize=8.5, labelcolor=TEXT)
    _note(ax, f"{len(d)} flights with a delay value\n{len(pos)} delayed ({100 * len(pos) / len(d):.0f}%)", "upper right")


def delay_by_hour(fig: Figure, tbl: pd.DataFrame) -> None:
    if tbl.empty:
        return empty(fig, "Not enough delay data per departure hour\n(hours need at least 3 flights with a delay value).")
    ax = _ax(fig, "Delay by departure hour (local time)", "Hour of day", "Delayed flights (%)")
    ax.bar(tbl["hour"], tbl["delayed_pct"], color=C1, width=0.7)
    for h, p, n in zip(tbl["hour"], tbl["delayed_pct"], tbl["delay_values"]):
        ax.text(h, p, f"n={n}", ha="center", va="bottom", fontsize=7, color=MUTED)
    ax.set_xticks(range(0, 24, 2))
    ax.set_ylim(0, 115)


def status_mix(fig: Figure, counts: dict, title: str = "Flight status mix") -> None:
    if not counts:
        return empty(fig, "No status data.")
    ax = fig.add_subplot(111)
    colors = {"scheduled": C3, "active": C2, "landed": C1, "cancelled": ERR, "delayed": WARN}
    labels, vals = list(counts), list(counts.values())
    ax.pie(vals, labels=[f"{l.title()} ({v})" for l, v in zip(labels, vals)], colors=[colors.get(l, C4) for l in labels],
           startangle=90, counterclock=False, wedgeprops=dict(width=0.42, edgecolor="white"), textprops=dict(fontsize=8.5, color=TEXT))
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color=TEXT)


# --------------------------------------------------------------------------- airports / airlines
def airport_traffic(fig: Figure, tbl: pd.DataFrame, top: int = 12) -> None:
    if tbl.empty:
        return empty(fig, "No airport traffic data.")
    t = tbl.head(top).iloc[::-1]
    ax = _ax(fig, f"Busiest airports in this dataset (top {len(t)})", "Flight records", "", grid="x")
    y = np.arange(len(t))
    ax.barh(y, t["departures"], color=C1, height=0.6, label="Departures")
    ax.barh(y, t["arrivals"], left=t["departures"], color=C2, height=0.6, label="Arrivals")
    ax.set_yticks(y, [f"{i}  {str(n)[:26]}" for i, n in zip(t["iata"], t["name"].fillna(""))], fontsize=8)
    ax.legend(frameon=False, fontsize=8.5, loc="lower right", labelcolor=TEXT)


def bar_counts(fig: Figure, labels: Sequence[str], values: Sequence[float], title: str, xlabel: str, color: str = C1) -> None:
    if not len(values):
        return empty(fig, "No data.")
    ax = _ax(fig, title, xlabel, "", grid="x")
    y = np.arange(len(values))[::-1]
    ax.barh(y, values, color=color, height=0.6)
    for yi, v in zip(y, values):
        ax.text(v, yi, f"  {v:,.0f}", va="center", fontsize=8, color=MUTED)
    ax.set_yticks(y, [str(l) for l in labels], fontsize=8.5)
    ax.set_xlim(0, max(values) * 1.15)


def airline_compare(fig: Figure, comp: pd.DataFrame) -> None:
    """Grouped bars for selected airlines (rows = metrics from airline_analytics.compare)."""
    if comp.empty:
        return empty(fig, "Select two or more airlines to compare.")
    metrics = [("flights", "Flights"), ("delayed_pct", "Delayed (%)"), ("avg_delay_min", "Mean delay (min)")]
    axes = fig.subplots(1, len(metrics))
    for ax, (key, label) in zip(np.atleast_1d(axes), metrics):
        vals = comp.loc[key].astype(float)
        ax.set_facecolor("none")
        ax.bar(range(len(vals)), vals.fillna(0), color=[C1, C2, WARN, C3, C4][: len(vals)], width=0.6)
        for i, v in enumerate(vals):
            ax.text(i, 0 if np.isnan(v) else v, "n/a" if np.isnan(v) else f"{v:,.1f}", ha="center", va="bottom", fontsize=8)
        ax.set_xticks(range(len(vals)), [str(c)[:14] for c in vals.index], rotation=25, ha="right", fontsize=8)
        ax.set_title(label, fontsize=10, fontweight="bold", color=TEXT, loc="left")
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(colors=MUTED, length=0, labelsize=8)


# --------------------------------------------------------------------------- ETL
def etl_records(fig: Figure, hist: pd.DataFrame) -> None:
    if hist.empty:
        return empty(fig, "No pipeline runs recorded yet.")
    h = hist.iloc[::-1].tail(25).reset_index(drop=True)
    ax = _ax(fig, "Records per pipeline run (latest 25)", "Run", "Records")
    x = np.arange(len(h))
    ax.bar(x, h["records_inserted"], color=C1, label="Inserted", width=0.7)
    ax.bar(x, h["records_updated"], bottom=h["records_inserted"], color=C2, label="Updated / duplicates skipped", width=0.7)
    ax.bar(x, h["records_rejected"], bottom=h["records_inserted"] + h["records_updated"], color=ERR, label="Rejected", width=0.7)
    ax.set_xticks(x, [str(i) for i in h["id"]], fontsize=7, rotation=90)
    ax.legend(frameon=False, fontsize=8, labelcolor=TEXT)


def etl_quality(fig: Figure, metrics: dict) -> None:
    items = [("Flights missing a delay value", metrics.get("flights_missing_delay_pct")),
             ("Flights missing airline code", metrics.get("flights_missing_airline_pct")),
             ("Flights missing scheduled times", metrics.get("flights_missing_times_pct"))]
    items = [(l, v) for l, v in items if v is not None]
    if not items:
        return empty(fig, "No stored data to assess yet.")
    ax = _ax(fig, "Data-quality indicators (% of stored rows)", "Percent of rows", "", grid="x")
    y = np.arange(len(items))[::-1]
    ax.barh(y, [v for _, v in items], color=[WARN if v > 25 else C1 for _, v in items], height=0.55)
    for yi, (_, v) in zip(y, items):
        ax.text(v, yi, f"  {v:.1f}%", va="center", fontsize=8.5, color=TEXT)
    ax.set_yticks(y, [l for l, _ in items], fontsize=8.5)
    ax.set_xlim(0, 110)


def weather_daily(fig: Figure, daily: dict, label: str) -> None:
    tmax, tmin = daily.get("temperature_2m_max"), daily.get("temperature_2m_min")
    if tmax is None or tmin is None:
        return empty(fig, "No temperature data for this date.")
    ax = _ax(fig, f"Temperature range - {label}", "", "Temperature (\u00b0C)")
    ax.bar([0], [tmax - tmin], bottom=[tmin], color=C1, width=0.35)
    ax.text(0, tmax, f"{tmax:.0f}\u00b0", ha="center", va="bottom", fontsize=11, color=TEXT)
    ax.text(0, tmin, f"{tmin:.0f}\u00b0", ha="center", va="top", fontsize=11, color=TEXT)
    ax.set_xlim(-1, 1)
    ax.set_xticks([])
    ax.set_ylim(min(tmin, 0) - 6, tmax + 8)
