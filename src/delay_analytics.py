"""Flight status & delay analytics over stored snapshots (HISTORICAL data)."""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd


def filter_flights(df: pd.DataFrame, airline: Optional[str] = None, airport: Optional[str] = None,
                   date_from: Optional[str] = None, date_to: Optional[str] = None,
                   status: Optional[str] = None) -> pd.DataFrame:
    out = df
    if airline:
        out = out[out["airline_iata"] == airline]
    if airport:
        out = out[(out["dep_iata"] == airport) | (out["arr_iata"] == airport)]
    if date_from:
        out = out[out["flight_date"].astype(str) >= date_from]
    if date_to:
        out = out[out["flight_date"].astype(str) <= date_to]
    if status:
        out = out[out["flight_status"] == status]
    return out


def display_status(row) -> str:
    """User-facing status; 'Delayed' only when the source reports a delay > 0."""
    s = str(row.get("flight_status") or "")
    d = row.get("max_delay_min")
    if s == "cancelled":
        return "Cancelled"
    if s == "landed":
        return "Arrived" + (" (late)" if pd.notna(d) and d > 0 else "")
    if pd.notna(d) and d > 0:
        return "Delayed"
    if s in ("scheduled", "active"):
        return "On time" if pd.notna(d) and d == 0 else ("Scheduled" if s == "scheduled" else "In air")
    return s.title() or "Unknown"


def by_airline(df: pd.DataFrame, min_values: int = 3) -> pd.DataFrame:
    d = df[df["max_delay_min"].notna()]
    if d.empty:
        return pd.DataFrame(columns=["airline_name", "delay_values", "avg_delay_min", "delayed_pct"])
    g = d.groupby("airline_name").agg(delay_values=("max_delay_min", "size"), avg_delay_min=("max_delay_min", "mean"),
                                       delayed=("max_delay_min", lambda s: int((s > 0).sum()))).reset_index()
    g["delayed_pct"] = (100 * g["delayed"] / g["delay_values"]).round(1)
    g["avg_delay_min"] = g["avg_delay_min"].round(2)
    return g[g["delay_values"] >= min_values].sort_values("avg_delay_min", ascending=False)


def by_airport(df: pd.DataFrame, min_values: int = 3) -> pd.DataFrame:
    d = df[df["max_delay_min"].notna() & (df["dep_iata"] != "")]
    if d.empty:
        return pd.DataFrame(columns=["dep_iata", "delay_values", "avg_delay_min", "delayed_pct"])
    g = d.groupby("dep_iata").agg(delay_values=("max_delay_min", "size"), avg_delay_min=("max_delay_min", "mean"),
                                   delayed=("max_delay_min", lambda s: int((s > 0).sum()))).reset_index()
    g["delayed_pct"] = (100 * g["delayed"] / g["delay_values"]).round(1)
    g["avg_delay_min"] = g["avg_delay_min"].round(2)
    return g[g["delay_values"] >= min_values].sort_values("avg_delay_min", ascending=False)


def by_departure_hour(df: pd.DataFrame, min_values: int = 3) -> pd.DataFrame:
    d = df[df["max_delay_min"].notna() & df["dep_local_hour"].notna()]
    if d.empty:
        return pd.DataFrame(columns=["hour", "delay_values", "avg_delay_min", "delayed_pct"])
    g = d.groupby("dep_local_hour").agg(delay_values=("max_delay_min", "size"), avg_delay_min=("max_delay_min", "mean"),
                                         delayed=("max_delay_min", lambda s: int((s > 0).sum()))).reset_index() \
        .rename(columns={"dep_local_hour": "hour"})
    g["delayed_pct"] = (100 * g["delayed"] / g["delay_values"]).round(1)
    return g[g["delay_values"] >= min_values]


def cancellation_stats(df: pd.DataFrame) -> Dict:
    n = len(df)
    c = int((df["flight_status"] == "cancelled").sum()) if n else 0
    return {"flights": n, "cancelled": c, "rate_pct": round(100 * c / n, 1) if n else None}
