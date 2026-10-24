"""Airline performance metrics computed from the stored flights.

Every metric states its sample size; a row is flagged ``small_sample`` below the
thresholds so the UI never ranks airlines on too little evidence.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

MIN_FLIGHTS = 10
MIN_DELAY_VALUES = 5

METRIC_DEFINITIONS: Dict[str, str] = {
    "flights": "Number of stored flight records for the airline (codeshare listings are counted as records).",
    "routes": "Distinct origin-destination pairs among those records.",
    "avg_delay_min": "Mean of reported delay minutes over flights that report a delay value (missing is not zero).",
    "delayed_pct": "Delayed flights (reported delay > 0) as % of flights that report a delay value.",
    "cancel_rate_pct": "Cancelled flights as % of the airline's stored flight records (needs status data).",
}


def table(flights: pd.DataFrame) -> pd.DataFrame:
    """One row per airline with metrics and sample sizes."""
    cols = ["airline_iata", "airline_name", "flights", "routes", "delay_values",
            "avg_delay_min", "delayed_pct", "cancelled", "cancel_rate_pct",
            "first_date", "last_date", "small_sample"]
    if flights is None or flights.empty:
        return pd.DataFrame(columns=cols)
    f = flights[flights["airline_iata"].notna() & (flights["airline_iata"] != "")].copy()
    f["route"] = f["dep_iata"] + "-" + f["arr_iata"]
    if f.empty:
        return pd.DataFrame(columns=cols)
    code = f["airline_iata"]
    grp = f.groupby("airline_iata", sort=True)
    out = grp.agg(flights=("airline_iata", "size"), routes=("route", "nunique"),
                  first_date=("flight_date", "min"), last_date=("flight_date", "max"))
    delay = f["max_delay_min"]
    known = delay.notna()
    out["delay_values"] = known.groupby(code).sum().astype(int)
    mean = delay.groupby(code).mean()
    out["avg_delay_min"] = mean.map(lambda v: round(float(v), 2) if pd.notna(v) else np.nan)
    delayed = ((delay > 0) & known).groupby(code).sum()
    share = 100 * delayed / out["delay_values"].where(out["delay_values"] > 0)
    out["delayed_pct"] = share.map(lambda v: round(float(v), 1) if pd.notna(v) else np.nan)
    cancelled = (f["flight_status"] == "cancelled").groupby(code).sum().astype(int)
    out["cancelled"] = cancelled
    out["cancel_rate_pct"] = (100 * cancelled / out["flights"]).map(lambda v: round(float(v), 1))
    out["first_date"] = out["first_date"].astype(str).str[:10]
    out["last_date"] = out["last_date"].astype(str).str[:10]
    # most frequent non-missing name per airline; ties resolved alphabetically (same as Series.mode()[0])
    named = f.dropna(subset=["airline_name"])
    if named.empty:
        names = pd.Series(dtype=object)
    else:
        counts = named.groupby(["airline_iata", "airline_name"]).size().reset_index(name="n")
        counts = counts.sort_values(["airline_iata", "n", "airline_name"], ascending=[True, False, True])
        names = counts.drop_duplicates("airline_iata").set_index("airline_iata")["airline_name"]
    out["airline_name"] = [names.get(c, c) for c in out.index]
    out = out.reset_index()
    out["small_sample"] = (out["flights"] < MIN_FLIGHTS) | (out["delay_values"] < MIN_DELAY_VALUES)
    return out.sort_values("flights", ascending=False).reset_index(drop=True)[cols]


def reporting_period(flights: pd.DataFrame) -> str:
    if flights is None or flights.empty:
        return "no data"
    d = pd.to_datetime(flights["flight_date"], errors="coerce").dropna()
    return f"{d.min().date()} to {d.max().date()} ({d.dt.date.nunique()} flight dates, {len(flights)} flight records)"


def compare(tbl: pd.DataFrame, selected) -> pd.DataFrame:
    """Side-by-side comparison of selected airlines (rows = metrics)."""
    sel = tbl[tbl["airline_iata"].isin(list(selected))]
    if sel.empty:
        return pd.DataFrame()
    metrics = ["flights", "routes", "delay_values", "avg_delay_min", "delayed_pct", "cancel_rate_pct"]
    return sel.set_index("airline_name")[metrics].T
