"""Airport analytics: traffic tables, detail views and honest scope notes."""

from __future__ import annotations

from typing import Dict

import pandas as pd


def traffic_table(flights: pd.DataFrame, ref: pd.DataFrame) -> pd.DataFrame:
    """One row per observed airport with counts and verified reference data."""
    cols = ["iata", "name", "city", "country", "latitude", "longitude", "departures", "arrivals", "total",
            "destinations", "origins", "airlines"]
    if flights is None or flights.empty:
        return pd.DataFrame(columns=cols)
    f = flights[(flights["dep_iata"] != "") & (flights["arr_iata"] != "")]
    dep = f.groupby("dep_iata").agg(departures=("id", "size"), destinations=("arr_iata", "nunique"))
    arr = f.groupby("arr_iata").agg(arrivals=("id", "size"), origins=("dep_iata", "nunique"))
    al = pd.concat([f[["dep_iata", "airline_iata"]].rename(columns={"dep_iata": "iata"}),
                    f[["arr_iata", "airline_iata"]].rename(columns={"arr_iata": "iata"})]).dropna()
    airlines = al.groupby("iata")["airline_iata"].nunique().rename("airlines")
    out = pd.concat([dep, arr, airlines], axis=1).fillna(0).astype(int).rename_axis("iata").reset_index()
    out["total"] = out["departures"] + out["arrivals"]
    out = out.merge(ref[["iata", "name", "city", "country", "latitude", "longitude"]], on="iata", how="left")
    # airport name fallback from the flights themselves when the reference has no entry
    names = pd.concat([f[["dep_iata", "dep_airport"]].set_axis(["iata", "n"], axis=1),
                       f[["arr_iata", "arr_airport"]].set_axis(["iata", "n"], axis=1)]).dropna().drop_duplicates("iata").set_index("iata")["n"]
    out["name"] = out["name"].fillna(out["iata"].map(names))
    return out.sort_values("total", ascending=False).reset_index(drop=True)[cols]


def scope_note(flights: pd.DataFrame, airports: pd.DataFrame) -> str:
    if flights is None or flights.empty:
        return "No flight data stored yet."
    d = pd.to_datetime(flights["flight_date"], errors="coerce").dropna()
    return (f"Based on {len(flights)} stored flight records on {d.dt.date.nunique()} flight date(s) "
            f"({d.min().date()} to {d.max().date()}) covering {len(airports)} airports. This is a sample of "
            "flights retrieved from the API, so 'busiest' means busiest IN THIS DATASET, not worldwide.")


def detail(flights: pd.DataFrame, iata: str) -> Dict:
    """Routes, airlines, status mix and delay figures for one airport."""
    iata = iata.upper()
    out = flights[flights["dep_iata"] == iata]
    inn = flights[flights["arr_iata"] == iata]
    both = pd.concat([out, inn])
    dest = out.groupby("arr_iata").agg(flights=("id", "size"), airlines=("airline_iata", "nunique")).reset_index() \
        .rename(columns={"arr_iata": "destination"}).sort_values("flights", ascending=False)
    orig = inn.groupby("dep_iata").agg(flights=("id", "size"), airlines=("airline_iata", "nunique")).reset_index() \
        .rename(columns={"dep_iata": "origin"}).sort_values("flights", ascending=False)
    air = both.groupby(["airline_iata", "airline_name"], dropna=False).size().rename("flights").reset_index() \
        .sort_values("flights", ascending=False)
    d = out["max_delay_min"].dropna()
    return {
        "iata": iata, "departures": len(out), "arrivals": len(inn), "destinations": dest, "origins": orig,
        "airlines": air, "status": both["flight_status"].value_counts().to_dict() if len(both) else {},
        "delay_values": len(d), "delayed_pct": round(100 * float((d > 0).mean()), 1) if len(d) else None,
        "avg_delay_min": round(float(d.mean()), 2) if len(d) else None,
        "flights": both.drop_duplicates("id") if "id" in both else both,
    }
