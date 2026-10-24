"""Charts for the structured EDA (one figure per analysis question).

Every chart has a title that states what is shown, labelled axes with units,
and an on-chart annotation (n, median, fence ...) so that it can be read on
its own. Figures are saved as PNG under ``visualizations/eda/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import config, palette
from .eda import pairwise_counts
from .visualizations import (GRID, MUTED, SAVE_BG, TEXT, _empty_figure, _new_fig, _shorten,
                             _style_ax, _title)

DPI = 160


def _save(fig: plt.Figure, name: str, out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    fig.savefig(path, dpi=DPI, facecolor=SAVE_BG)
    plt.close(fig)
    return str(path)


def _note(ax, text: str, loc: str = "upper right") -> None:
    x, ha = (0.98, "right") if "right" in loc else (0.02, "left")
    y, va = (0.04, "bottom") if "lower" in loc else (0.96, "top")
    ax.text(x, y, text, transform=ax.transAxes, ha=ha, va=va, fontsize=8.5,
            color=MUTED, bbox=dict(boxstyle="round,pad=0.35", fc=palette.SURFACE_ALT,
                                   ec=palette.BORDER, lw=0.8))


def fig_missing_values(df: pd.DataFrame, summary: Dict) -> plt.Figure:
    miss = summary["missing"].head(14).iloc[::-1]
    fig, ax = _new_fig(8, 5)
    colors = [palette.ERROR if v >= 80 else palette.WARNING if v >= 30 else palette.COBALT
              for v in miss["missing_pct"]]
    ax.barh(miss["column"], miss["missing_pct"], color=colors, height=0.62)
    for y, (pct, n) in enumerate(zip(miss["missing_pct"], miss["missing"])):
        ax.text(pct + 1, y, f"{pct:.0f}%  ({n})", va="center", fontsize=8, color=MUTED)
    ax.set_xlim(0, 125)
    ax.set_xlabel("Missing values (% of rows)", color=MUTED, fontsize=9)
    _title(ax, f"Missing values by column (top {len(miss)} of {len(summary['missing'])})")
    _style_ax(ax, xgrid=True, ygrid=False)
    _note(ax, f"n = {len(df)} flights", "lower right")
    return fig


def fig_status(df: pd.DataFrame, summary: Dict) -> plt.Figure:
    counts = df["flight_status"].value_counts()
    fig, ax = _new_fig(7, 4.2)
    colors = [palette.STATUS_COLORS.get(s, palette.COBALT) for s in counts.index]
    bars = ax.bar(counts.index.str.title(), counts.values, color=colors, width=0.55)
    for b, v in zip(bars, counts.values):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v}\n({100 * v / len(df):.1f}%)",
                ha="center", va="bottom", fontsize=9, color=TEXT)
    ax.set_ylim(0, counts.max() * 1.22)
    ax.set_ylabel("Flights", color=MUTED, fontsize=9)
    ax.set_xlabel("Flight status", color=MUTED, fontsize=9)
    _title(ax, "Flight status distribution")
    _style_ax(ax)
    return fig


def fig_top_airlines(df: pd.DataFrame, summary: Dict) -> plt.Figure:
    top = df["airline_name"].value_counts().head(10).iloc[::-1]
    fig, ax = _new_fig(8, 4.8)
    ax.barh([_shorten(x, 30) for x in top.index], top.values, color=palette.COBALT, height=0.62)
    for y, v in enumerate(top.values):
        ax.text(v + 0.15, y, str(v), va="center", fontsize=8.5, color=MUTED)
    ax.set_xlabel("Flights stored", color=MUTED, fontsize=9)
    _title(ax, "Ten most frequent airlines")
    _style_ax(ax, xgrid=True, ygrid=False)
    _note(ax, f"{df['airline_name'].nunique()} airlines in total", "lower right")
    return fig


def fig_top_routes_airports(df: pd.DataFrame, summary: Dict) -> plt.Figure:
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.6), facecolor=SAVE_BG, layout="constrained")
    dep = df["dep_iata"].replace("", np.nan).dropna().value_counts().head(8).iloc[::-1]
    rte = df["route"].dropna().value_counts().head(8).iloc[::-1]
    for ax, data, title, color in ((axes[0], dep, "Busiest departure airports", palette.COBALT),
                                   (axes[1], rte, "Most frequent routes", palette.TEAL)):
        ax.set_facecolor(SAVE_BG)
        ax.barh(data.index, data.values, color=color, height=0.62)
        for y, v in enumerate(data.values):
            ax.text(v + 0.2, y, str(v), va="center", fontsize=8.5, color=MUTED)
        ax.set_xlabel("Flights stored", color=MUTED, fontsize=9)
        _title(ax, title)
        _style_ax(ax, xgrid=True, ygrid=False)
    return fig


def fig_duration(df: pd.DataFrame, summary: Dict) -> plt.Figure:
    d = df["scheduled_duration_min"].dropna()
    out = summary["outliers"]["scheduled_duration_min"]
    fig, ax = _new_fig(8, 4.5)
    ax.hist(d, bins=28, color=palette.COBALT, edgecolor=SAVE_BG, linewidth=0.6)
    ax.axvline(d.median(), color=palette.TEAL, lw=1.6, ls="-", label=f"Median {d.median():.0f} min")
    ax.axvline(d.mean(), color=palette.WARNING, lw=1.6, ls="--", label=f"Mean {d.mean():.0f} min")
    if "upper_fence" in out:
        ax.axvline(out["upper_fence"], color=palette.ERROR, lw=1.4, ls=":",
                   label=f"IQR upper fence {out['upper_fence']:.0f} min")
    ax.set_xlabel("Scheduled block time (minutes, UTC-corrected)", color=MUTED, fontsize=9)
    ax.set_ylabel("Flights", color=MUTED, fontsize=9)
    ax.margins(y=0.12)
    ax.legend(frameon=False, fontsize=8.5, labelcolor=TEXT, loc="upper right")
    _title(ax, f"Distribution of scheduled flight duration (n = {len(d)} of {len(df)})")
    _style_ax(ax)
    return fig


def fig_delay(df: pd.DataFrame, summary: Dict) -> plt.Figure:
    d = df["max_delay_min"].dropna()
    pos = d[d > 0]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.5, 4.4), facecolor=SAVE_BG,
                                 layout="constrained", gridspec_kw={"width_ratios": [1, 1.25]})
    for ax in (a1, a2):
        ax.set_facecolor(SAVE_BG)
    on, late = int((d == 0).sum()), int((d > 0).sum())
    a1.bar(["No delay\n(0 min)", "Delayed\n(> 0 min)"], [on, late],
           color=[palette.COBALT, palette.WARNING], width=0.55)
    for x, v in enumerate([on, late]):
        a1.text(x, v, f"{v}\n({100 * v / len(d):.1f}%)", ha="center", va="bottom", fontsize=9, color=TEXT)
    a1.set_ylim(0, max(on, late) * 1.25)
    a1.set_ylabel("Flights with a reported delay value", color=MUTED, fontsize=9)
    _title(a1, "Delayed vs not delayed")
    _style_ax(a1)
    a2.hist(pos, bins=np.arange(0, pos.max() + 6, 5), color=palette.WARNING, edgecolor=SAVE_BG, linewidth=0.6)
    a2.axvline(pos.median(), color=palette.NAVY, lw=1.6, label=f"Median {pos.median():.0f} min")
    a2.set_xlabel("Delay (minutes), delayed flights only", color=MUTED, fontsize=9)
    a2.set_ylabel("Flights", color=MUTED, fontsize=9)
    a2.legend(frameon=False, fontsize=8.5, labelcolor=TEXT)
    _title(a2, "How long are the delays?")
    _style_ax(a2)
    _note(a2, f"n = {len(pos)} delayed flights\nmax = {pos.max():.0f} min")
    return fig


def fig_hourly(df: pd.DataFrame, summary: Dict) -> plt.Figure:
    h = summary["hourly"]
    fig, ax = _new_fig(9, 4.5)
    ax.bar(h["dep_hour_local"], h["flights"], color=palette.COBALT, width=0.75, label="Flights")
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel("Scheduled departure hour (airport local time)", color=MUTED, fontsize=9)
    ax.set_ylabel("Flights", color=MUTED, fontsize=9)
    ax2 = ax.twinx()
    ok = h[h["delay_reported"] >= 5]
    ax2.plot(ok["dep_hour_local"], ok["delayed_pct_of_reported"], color=palette.WARNING,
             marker="o", lw=1.8, label="% delayed (hours with >= 5 delay values)")
    ax2.set_ylabel("Delayed (% of flights with delay data)", color=palette.WARNING, fontsize=9)
    ax2.set_ylim(0, 100)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.tick_params(colors=palette.WARNING, labelsize=9, length=0)
    _title(ax, "Departures and delay rate by local departure hour")
    _style_ax(ax)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, frameon=False, fontsize=8.5, loc="upper left", labelcolor=TEXT)
    return fig


def fig_trend_dates(df: pd.DataFrame, summary: Dict) -> plt.Figure:
    t = summary["trend_by_date"]
    fig, ax = _new_fig(7.4, 4.3)
    labels = [str(d) for d in t["date"]]
    ax.bar(labels, t["flights"], color=palette.COBALT, width=0.5, label="Flights stored")
    ax.bar(labels, t["delay_reported"], color=palette.TEAL, width=0.28, label="...with delay value")
    for x, (n, dly, pct) in enumerate(zip(t["flights"], t["delayed"], t["delayed_pct_of_reported"])):
        txt = f"{n}" + (f"\n{dly} delayed ({pct:.0f}%)" if pd.notna(pct) else "\nno delay data")
        ax.text(x, n, txt, ha="center", va="bottom", fontsize=8.5, color=TEXT)
    ax.set_ylim(0, t["flights"].max() * 1.3)
    ax.set_xlabel("Flight date", color=MUTED, fontsize=9)
    ax.set_ylabel("Flights", color=MUTED, fontsize=9)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right", labelcolor=TEXT)
    _title(ax, "Flights per capture date")
    _style_ax(ax)
    return fig


def fig_correlation(df: pd.DataFrame, summary: Dict) -> plt.Figure:
    corr = summary["correlation_spearman"]
    if corr.shape[0] < 2:
        return _empty_figure("Not enough numeric data for a correlation matrix.")
    names = {"dep_delay_min": "Dep. delay", "arr_delay_min": "Arr. delay",
             "scheduled_duration_min": "Duration", "live_speed_kmh": "Live speed",
             "live_altitude": "Live altitude", "dep_hour_local": "Local dep. hour"}
    labels = [names.get(c, c) for c in corr.columns]
    fig, ax = _new_fig(6.8, 5.4)
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(labels)), labels, rotation=35, ha="right", fontsize=9)
    ax.set_yticks(range(len(labels)), labels, fontsize=9)
    for i in range(len(labels)):
        for j in range(len(labels)):
            v = corr.values[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8.5,
                    color="white" if abs(v) > 0.55 else TEXT)
    fig.colorbar(im, ax=ax, shrink=0.8, label="Spearman rank correlation")
    counts = pairwise_counts(df, corr.columns).values
    off = counts[~np.eye(len(counts), dtype=bool)]
    ax.set_xlabel(f"rows behind each cell: {int(off.min())} to {int(off.max())} (small n - read with care)",
                  color=MUTED, fontsize=8.5)
    _title(ax, "Correlation between numeric fields")
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    return fig


def fig_codeshare(df: pd.DataFrame, summary: Dict) -> plt.Figure:
    cs = summary["codeshare_vs_delay"]
    g, t = cs["groups"], cs["test"]
    labels = ["Operated\n(not codeshared)", "Codeshared\nlisting"]
    pct = [100 * g["operated"]["delayed"] / max(g["operated"]["n"], 1),
           100 * g["codeshared"]["delayed"] / max(g["codeshared"]["n"], 1)]
    fig, ax = _new_fig(6.4, 4.4)
    bars = ax.bar(labels, pct, color=[palette.COBALT, palette.TEAL], width=0.5)
    for b, v, key in zip(bars, pct, ("operated", "codeshared")):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.0f}%\n({g[key]['delayed']} of {g[key]['n']})",
                ha="center", va="bottom", fontsize=9, color=TEXT)
    ax.set_ylim(0, max(pct) * 1.35 + 1)
    ax.set_ylabel("Delayed flights (% of flights with delay data)", color=MUTED, fontsize=9)
    p = t["p_value"]
    _title(ax, "Delay rate: operated vs codeshared listings")
    _style_ax(ax)
    if p is not None:
        _note(ax, f"two-proportion z-test: p {'< 0.001' if p < 0.001 else '= ' + str(p)}")
    return fig


def fig_delay_by_airline(df: pd.DataFrame, summary: Dict) -> plt.Figure:
    t = summary["delay_by_airline"].head(8).iloc[::-1]
    if t.empty:
        return _empty_figure("No airline has enough flights with delay data (>= 4).")
    fig, ax = _new_fig(8.2, 4.6)
    ax.barh([f"{_shorten(a, 26)} (n={n})" for a, n in zip(t["airline_name"], t["flights_with_delay_data"])],
            t["mean_delay_min"], color=palette.WARNING, height=0.6)
    for y, (m, mx) in enumerate(zip(t["mean_delay_min"], t["max_delay_min"])):
        ax.text(m + 0.2, y, f"{m:.1f} min (max {mx:.0f})", va="center", fontsize=8.5, color=MUTED)
    ax.set_xlim(0, t["mean_delay_min"].max() * 1.5 + 1)
    ax.set_xlabel("Mean reported delay (minutes)", color=MUTED, fontsize=9)
    _title(ax, "Mean delay by airline (airlines with >= 4 delay values)")
    _style_ax(ax, xgrid=True, ygrid=False)
    return fig


def fig_outliers(df: pd.DataFrame, summary: Dict) -> plt.Figure:
    specs = [("scheduled_duration_min", "Scheduled duration (min)", False),
             ("max_delay_min", "Delay of delayed flights (min)", True),
             ("live_speed_kmh", "Live ground speed (km/h)", False)]
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 4.4), facecolor=SAVE_BG, layout="constrained")
    for ax, (col, label, pos_only) in zip(axes, specs):
        ax.set_facecolor(SAVE_BG)
        s = df[col].dropna()
        if pos_only:
            s = s[s > 0]
        ax.boxplot(s, widths=0.5, patch_artist=True,
                   boxprops=dict(facecolor=palette.COBALT_TINT, edgecolor=palette.COBALT),
                   medianprops=dict(color=palette.NAVY, lw=1.8),
                   flierprops=dict(marker="o", markerfacecolor=palette.ERROR,
                                   markeredgecolor=SAVE_BG, markersize=5.5),
                   whiskerprops=dict(color=palette.COBALT), capprops=dict(color=palette.COBALT))
        ax.set_xticks([])
        ax.set_ylabel(label, color=MUTED, fontsize=9)
        key = {"scheduled_duration_min": "scheduled_duration_min", "max_delay_min": "delay_min_positive",
               "live_speed_kmh": "live_speed_kmh"}[col]
        o = summary["outliers"][key]
        _title(ax, label.split(" (")[0])
        _style_ax(ax)
        _note(ax, f"n = {len(s)}\n{o.get('outliers', 0)} outliers", "upper left")
    for ax in axes:
        ax.set_xlabel("Tukey rule: 1.5 x IQR", color=MUTED, fontsize=8.5)
    return fig


FIGURES = [
    ("01_missing_values.png", fig_missing_values),
    ("02_status_distribution.png", fig_status),
    ("03_top_airlines.png", fig_top_airlines),
    ("04_top_airports_routes.png", fig_top_routes_airports),
    ("05_duration_distribution.png", fig_duration),
    ("06_delay_distribution.png", fig_delay),
    ("07_hourly_profile.png", fig_hourly),
    ("08_flights_per_date.png", fig_trend_dates),
    ("09_correlation_heatmap.png", fig_correlation),
    ("10_codeshare_vs_delay.png", fig_codeshare),
    ("11_delay_by_airline.png", fig_delay_by_airline),
    ("12_outliers_boxplots.png", fig_outliers),
]


def save_all(df: pd.DataFrame, summary: Dict, out_dir: Path = None) -> Dict[str, str]:
    """Render and save every EDA figure; returns ``{file name: path}``."""
    out_dir = Path(out_dir) if out_dir else config.EDA_FIGURES_DIR
    saved: Dict[str, str] = {}
    for name, builder in FIGURES:
        try:
            fig = builder(df, summary)
        except Exception as exc:  # one failing chart must not stop the others
            from .utils import get_logger
            get_logger().warning("EDA chart %s could not be drawn: %s", name, exc)
            fig = _empty_figure(f"Chart unavailable for this dataset:\n{exc}")
        saved[name] = _save(fig, name, out_dir)
    return saved
