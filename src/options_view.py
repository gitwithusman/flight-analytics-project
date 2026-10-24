"""Presentation logic for flight-search results (no Qt): display frame, filters, sorting."""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from .providers.base import DATA_ORIGIN_LABELS
from .providers.demo import CARRIERS

SORTS = {
    "Departure (earliest first)": ("departure_at", True),
    "Duration (shortest first)": ("duration_min", True),
    "Fewest stops": ("stops", True),
    "Airline (A-Z)": ("airline_iata", True),
}
TIME_BUCKETS = {"Any time": None, "Early (00:00-05:59)": (0, 6), "Morning (06:00-11:59)": (6, 12),
                "Afternoon (12:00-17:59)": (12, 18), "Evening (18:00-23:59)": (18, 24)}


def airline_names(db_path=None) -> Dict[str, str]:
    """IATA -> airline name from stored flights plus the labelled sample carriers."""
    from . import database
    names = {code: f"{name} (sample)" for code, name in CARRIERS}
    try:
        with database.connect(db_path) as conn:
            for code, name in conn.execute("SELECT iata, name FROM airlines WHERE name IS NOT NULL"):
                names.setdefault(code, name)
    except Exception:
        pass
    return names


def fmt_duration(minutes) -> str:
    if minutes is None or (isinstance(minutes, float) and np.isnan(minutes)):
        return "not provided"
    m = int(minutes)
    return f"{m // 60}h {m % 60:02d}m"


def fmt_stops(stops) -> str:
    if stops is None or (isinstance(stops, float) and np.isnan(stops)):
        return "not provided"
    s = int(stops)
    return "Direct" if s == 0 else f"{s} stop{'s' if s > 1 else ''}"


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Add parsed datetimes and a departure hour used by the filters."""
    out = df.copy()
    if out.empty:
        return out
    out["dep_dt"] = pd.to_datetime(out["departure_at"], utc=True, errors="coerce")
    out["arr_dt"] = pd.to_datetime(out["arrival_at"], utc=True, errors="coerce")
    out["dep_hour"] = out["dep_dt"].dt.hour
    return out


def apply_filters(df: pd.DataFrame, airline: Optional[str] = None, max_stops: Optional[int] = None,
                  bucket: Optional[str] = None, max_duration_h: Optional[float] = None) -> pd.DataFrame:
    out = prepare(df)
    if out.empty:
        return out
    if airline:
        out = out[out["airline_iata"] == airline]
    if max_stops is not None:
        out = out[out["stops"].fillna(99) <= max_stops]
    rng = TIME_BUCKETS.get(bucket or "Any time")
    if rng:
        out = out[(out["dep_hour"] >= rng[0]) & (out["dep_hour"] < rng[1])]
    if max_duration_h:
        out = out[out["duration_min"].isna() | (out["duration_min"] <= max_duration_h * 60)]
    return out


def sort_options(df: pd.DataFrame, label: str) -> pd.DataFrame:
    col, asc = SORTS.get(label, SORTS["Departure (earliest first)"])
    if df.empty or col not in df:
        return df
    return df.sort_values([col, "departure_at"], ascending=[asc, True], na_position="last")


def display_frame(df: pd.DataFrame, names: Dict[str, str]) -> pd.DataFrame:
    """Human-readable table. ``not provided`` is shown wherever the source gave nothing."""
    if df.empty:
        return pd.DataFrame()
    d = prepare(df)
    rows = []
    for idx, r in d.iterrows():
        rows.append({
            "Airline": names.get(r["airline_iata"], r["airline_iata"] or "not provided"),
            "Flight": r["flight_number"] or "not provided",
            "Route": f"{r['origin_iata']} \u2192 {r['destination_iata']}",
            "Departs (UTC)": r["dep_dt"].strftime("%Y-%m-%d %H:%M") if pd.notna(r["dep_dt"]) else "",
            "Arrives (UTC)": (r["arr_dt"].strftime("%Y-%m-%d %H:%M") + (" *" if r.get("arrival_derived") else ""))
            if pd.notna(r["arr_dt"]) else "not provided",
            "Duration": fmt_duration(r["duration_min"]), "Stops": fmt_stops(r["stops"]),
            "Baggage": r["baggage"] if isinstance(r["baggage"], str) and r["baggage"] else "not provided",
            "Data": DATA_ORIGIN_LABELS.get(r["data_origin"], r["data_origin"]),
        })
    return pd.DataFrame(rows, index=d.index)
