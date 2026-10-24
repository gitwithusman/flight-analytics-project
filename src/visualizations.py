"""Matplotlib/Seaborn chart builders with a consistent light theme.

Each function takes the flights DataFrame and returns a
``matplotlib.figure.Figure`` (or ``None`` when the data cannot support the
chart). The terminal app saves the figures to ``visualizations/``; the GUI
embeds the same figures in a Qt canvas - identical output either way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

import matplotlib

matplotlib.use("Agg")  # safe default; the GUI swaps in a Qt canvas

import matplotlib.pyplot as plt
import pandas as pd

from . import analytics, config, palette
from .utils import get_logger, timestamp_for_filename

logger = get_logger()

# ---------------------------------------------------------------------------
# Theme (shared design tokens live in src/palette.py)
# ---------------------------------------------------------------------------

TEXT = palette.TEXT
MUTED = palette.TEXT_MUTED
GRID = "#E6EAF0"
SAVE_BG = palette.SURFACE  # chart background, on screen and in saved PNGs
SERIES = palette.SERIES
STATUS_COLORS = palette.STATUS_COLORS


def _new_fig(w: float, h: float):
    # constrained layout re-flows labels whenever the canvas is resized, so
    # charts stay readable at any window size (tight_layout runs only once).
    fig = plt.Figure(figsize=(w, h), facecolor=SAVE_BG, layout="constrained")
    ax = fig.add_subplot(111)
    ax.set_facecolor(SAVE_BG)
    return fig, ax


def _style_ax(ax, xgrid: bool = False, ygrid: bool = True) -> None:
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    if ygrid:
        ax.grid(axis="y", color=GRID, linewidth=0.8)
    if xgrid:
        ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for item in (ax.title, ax.xaxis.label, ax.yaxis.label):
        item.set_color(TEXT)


def _title(ax, text: str) -> None:
    ax.set_title(text, fontsize=12, fontweight="bold", color=TEXT,
                 pad=10, loc="left")


def _empty_figure(message: str) -> plt.Figure:
    """A figure that explains *why* a chart is unavailable."""
    fig = plt.Figure(figsize=(7, 4), facecolor=SAVE_BG, layout="constrained")
    ax = fig.add_subplot(111)
    ax.set_facecolor(SAVE_BG)
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=11,
            color=MUTED, transform=ax.transAxes, wrap=True)
    ax.set_axis_off()
    return fig


def _top_n_barh(labels, values, title, xlabel, color=palette.COBALT) -> plt.Figure:
    fig, ax = _new_fig(8, 4.6)
    positions = list(range(len(labels)))[::-1]
    ax.barh(positions, values, color=color, height=0.62, edgecolor="none")
    ax.set_yticks(positions)
    ax.set_yticklabels([_shorten(l) for l in labels], fontsize=9, color=TEXT)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    ax.margins(x=0.12)
    _title(ax, title)
    _style_ax(ax, xgrid=True, ygrid=False)
    for pos, val in zip(positions, values):
        ax.text(val, pos, f"  {val}", va="center", color=MUTED, fontsize=8)
    return fig


def _shorten(label, width: int = 34) -> str:
    text = str(label)
    return text if len(text) <= width else text[: width - 1] + "\u2026"


def chart_status_distribution(df: pd.DataFrame) -> plt.Figure:
    """Donut chart of the flight-status mix with the total in the centre."""
    dist = analytics.status_distribution(df)
    if dist.empty:
        return _empty_figure("No flight-status data available yet.")

    labels = dist["flight_status"].str.title().tolist()
    values = dist["flights"].tolist()
    colors = [STATUS_COLORS.get(s, palette.COBALT)
              for s in dist["flight_status"]]

    fig, ax = _new_fig(6.4, 4.6)
    wedges, _ = ax.pie(
        values, colors=colors, startangle=90, counterclock=False,
        wedgeprops=dict(width=0.42, edgecolor=SAVE_BG, linewidth=2),
    )
    total = sum(values)
    ax.text(0, 0.08, f"{total}", ha="center", va="center", fontsize=22,
            fontweight="bold", color=TEXT)
    ax.text(0, -0.18, "flights", ha="center", va="center", fontsize=9,
            color=MUTED)
    ax.legend(
        wedges, [f"{l}  ({v})" for l, v in zip(labels, values)],
        loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False,
        fontsize=9, labelcolor=TEXT,
    )
    _title(ax, "Flight Status Distribution")
    return fig


def chart_top_airlines(df: pd.DataFrame, n: int = 10) -> plt.Figure:
    top = analytics.top_airlines(df, n)
    if top.empty:
        return _empty_figure("No airline data available yet.")
    return _top_n_barh(
        list(top["airline"]), list(top["flights"]),
        f"Top {len(top)} Airlines by Stored Flights", "Flights", palette.NAVY_SOFT,
    )


def _airport_labels(top: pd.DataFrame) -> list:
    """'Name (IATA)' labels; the name is shortened so the code never is."""
    return [f"{_shorten(a, 24)} ({i})" if pd.notna(i) else _shorten(a, 30)
            for a, i in zip(top["airport"], top["iata"])]


def chart_top_departure_airports(df: pd.DataFrame, n: int = 10) -> plt.Figure:
    top = analytics.top_airports(df, "dep", n)
    if top.empty:
        return _empty_figure("No departure airport data available yet.")
    labels = _airport_labels(top)
    return _top_n_barh(
        labels, list(top["flights"]),
        f"Top {len(top)} Departure Airports", "Departing flights", palette.COBALT,
    )


def chart_top_arrival_airports(df: pd.DataFrame, n: int = 10) -> plt.Figure:
    top = analytics.top_airports(df, "arr", n)
    if top.empty:
        return _empty_figure("No arrival airport data available yet.")
    labels = _airport_labels(top)
    return _top_n_barh(
        labels, list(top["flights"]),
        f"Top {len(top)} Arrival Airports", "Arriving flights", palette.TEAL,
    )


def chart_top_routes(df: pd.DataFrame, n: int = 10) -> plt.Figure:
    top = analytics.top_routes(df, n)
    if top.empty:
        return _empty_figure("No route data available yet.")
    return _top_n_barh(
        list(top["route"]), list(top["flights"]),
        f"Top {len(top)} Routes", "Flights", palette.NAVY_SOFT,
    )


def chart_delay_histogram(df: pd.DataFrame) -> plt.Figure:
    stats = analytics.delay_statistics(df)
    if not stats.get("available"):
        return _empty_figure(
            stats.get("reason", "No delay data in the dataset."))
    fig, ax = _new_fig(7.4, 4.4)
    delays = df["max_delay_min"].dropna()
    ax.hist(delays, bins=25, color=palette.COBALT, edgecolor=SAVE_BG,
            linewidth=0.6)
    ax.axvline(delays.mean(), color=palette.ERROR, linestyle="--", linewidth=1.4,
               label=f"Mean {delays.mean():.0f} min")
    ax.set_xlabel("Delay (minutes)", color=MUTED, fontsize=9)
    ax.set_ylabel("Flights", color=MUTED, fontsize=9)
    ax.legend(frameon=False, fontsize=9, labelcolor=TEXT)
    _title(ax, "Distribution of Reported Delays")
    _style_ax(ax)
    return fig


def chart_departure_hours(df: pd.DataFrame) -> plt.Figure:
    dist = analytics.departure_hour_distribution(df)
    if dist.empty:
        return _empty_figure(
            "Scheduled departure times are unavailable or unparsable.")
    fig, ax = _new_fig(8, 4.2)
    ax.bar(dist["hour"], dist["flights"], color=palette.COBALT, width=0.78)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel("Hour of day (airport local time)", color=MUTED, fontsize=9)
    ax.set_ylabel("Flights", color=MUTED, fontsize=9)
    _title(ax, "Flights by Scheduled Departure Hour")
    _style_ax(ax)
    return fig


def chart_live_positions(df: pd.DataFrame) -> plt.Figure:
    """Map-style scatter of live flight positions (lat/lon from the API).

    This is the practical alternative to an interactive map: AviationStack's
    free tier supplies aircraft positions only for live-tracked flights, so
    airport coordinates are not available for a true route map.
    """
    if df.empty or "live_latitude" not in df or "live_longitude" not in df:
        return _empty_figure("No live position data in the dataset.")
    live = df.dropna(subset=["live_latitude", "live_longitude"])
    if live.empty:
        return _empty_figure(
            "No live-tracked flights right now - positions appear only\n"
            "for aircraft the API is tracking in real time.")
    fig, ax = _new_fig(8, 4.6)
    ax.set_facecolor(palette.SURFACE_ALT)
    for lon in range(-180, 181, 30):
        ax.axvline(lon, color=GRID, linewidth=0.6)
    for lat in range(-80, 81, 20):
        ax.axhline(lat, color=GRID, linewidth=0.6)
    ax.scatter(live["live_longitude"], live["live_latitude"],
               s=42, c=palette.COBALT, alpha=0.85, edgecolors=SAVE_BG,
               linewidths=0.6, zorder=3)
    for _, row in live.head(12).iterrows():
        label = row.get("flight_iata") or ""
        if isinstance(label, str) and label:
            ax.annotate(label, (row["live_longitude"], row["live_latitude"]),
                        textcoords="offset points", xytext=(5, 5),
                        fontsize=7, color=MUTED)
    ax.set_xlim(-180, 180)
    ax.set_ylim(-85, 85)
    ax.set_xlabel("Longitude", color=MUTED, fontsize=9)
    ax.set_ylabel("Latitude", color=MUTED, fontsize=9)
    _title(ax, f"Live Flight Positions ({len(live)} tracked)")
    ax.tick_params(colors=MUTED, labelsize=8)
    return fig


# Registry shared by the terminal menu and the GUI chart selectors.
CHART_TYPES: Dict[str, Dict[str, object]] = {
    "status": {"title": "Flight Status Distribution",
               "builder": chart_status_distribution},
    "airlines": {"title": "Top Airlines",
                 "builder": chart_top_airlines},
    "dep_airports": {"title": "Top Departure Airports",
                     "builder": chart_top_departure_airports},
    "arr_airports": {"title": "Top Arrival Airports",
                     "builder": chart_top_arrival_airports},
    "routes": {"title": "Top Routes",
               "builder": chart_top_routes},
    "delays": {"title": "Delay Distribution",
               "builder": chart_delay_histogram},
    "dep_hours": {"title": "Departures by Hour",
                  "builder": chart_departure_hours},
    "live_map": {"title": "Live Flight Positions",
                 "builder": chart_live_positions},
}


def build_chart(chart_key: str, df: pd.DataFrame,
                with_title: bool = True) -> plt.Figure:
    """Build one registered chart by key.

    ``with_title=False`` drops the in-chart title - used by the GUI, whose
    card header already shows it.
    """
    entry = CHART_TYPES.get(chart_key)
    if not entry:
        return _empty_figure(f"Unknown chart '{chart_key}'.")
    builder: Callable[[pd.DataFrame], plt.Figure] = entry["builder"]  # type: ignore
    fig = builder(df)
    if not with_title:
        for ax in fig.axes:
            for loc in ("left", "center", "right"):
                ax.set_title("", loc=loc)
    return fig


def save_chart(chart_key: str, df: pd.DataFrame,
               out_dir: Optional[Path] = None) -> Path:
    """Render a chart and save it as PNG under ``visualizations/``."""
    fig = build_chart(chart_key, df)
    out_dir = Path(out_dir) if out_dir else config.VISUALIZATIONS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{chart_key}_{timestamp_for_filename()}.png"
    fig.savefig(path, dpi=130, bbox_inches="tight", facecolor=SAVE_BG)
    plt.close(fig)
    logger.info("Chart saved to %s", path)
    return path


def save_all_charts(df: pd.DataFrame) -> Dict[str, Path]:
    """Generate and save every supported chart; returns key -> path."""
    paths = {}
    for key in CHART_TYPES:
        try:
            paths[key] = save_chart(key, df)
        except Exception as exc:  # keep going even if one chart fails
            logger.warning("Chart %s failed: %s", key, exc)
    return paths
