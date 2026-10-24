"""Route table + geometry for the interactive map (real airport coordinates only)."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from . import reference


def route_table(flights: pd.DataFrame, ref: pd.DataFrame) -> pd.DataFrame:
    """Aggregate flights per (origin, destination) with coordinates. Routes
    with a missing coordinate are dropped from the table and counted in ``attrs['dropped_no_coords']``."""
    cols = ["origin", "destination", "flights", "airlines", "airline_list", "distance_km", "o_lat", "o_lon",
            "d_lat", "d_lon"]
    if flights is None or flights.empty:
        return pd.DataFrame(columns=cols)
    f = flights[(flights["dep_iata"] != "") & (flights["arr_iata"] != "") & (flights["dep_iata"] != flights["arr_iata"])]
    g = f.groupby(["dep_iata", "arr_iata"]).agg(
        flights=("id", "size"), airlines=("airline_iata", "nunique"),
        airline_list=("airline_name", lambda s: ", ".join(sorted({str(x) for x in s.dropna()})[:4]))).reset_index() \
        .rename(columns={"dep_iata": "origin", "arr_iata": "destination"})
    lut = ref.set_index("iata")[["latitude", "longitude"]]
    for side, col in (("o", "origin"), ("d", "destination")):
        g[f"{side}_lat"] = g[col].map(lut["latitude"])
        g[f"{side}_lon"] = g[col].map(lut["longitude"])
    missing = int(g[["o_lat", "o_lon", "d_lat", "d_lon"]].isna().any(axis=1).sum())
    g = g.dropna(subset=["o_lat", "o_lon", "d_lat", "d_lon"]).copy()
    g["distance_km"] = [round(reference.haversine_km(a, b, c, d)) for a, b, c, d in
                        zip(g.o_lat, g.o_lon, g.d_lat, g.d_lon)]
    g = g.sort_values("flights", ascending=False).reset_index(drop=True)
    g.attrs["dropped_no_coords"] = missing
    return g[cols]


def airport_points(routes: pd.DataFrame) -> pd.DataFrame:
    """Unique airports appearing in ``routes`` with a traffic count."""
    if routes.empty:
        return pd.DataFrame(columns=["iata", "lat", "lon", "flights"])
    a = pd.concat([routes[["origin", "o_lat", "o_lon", "flights"]].set_axis(["iata", "lat", "lon", "flights"], axis=1),
                   routes[["destination", "d_lat", "d_lon", "flights"]].set_axis(["iata", "lat", "lon", "flights"], axis=1)])
    return a.groupby(["iata", "lat", "lon"], as_index=False)["flights"].sum().sort_values("flights", ascending=False)


def filter_routes(routes: pd.DataFrame, origin: Optional[str] = None, destination: Optional[str] = None,
                  min_flights: int = 1, airline: Optional[str] = None) -> pd.DataFrame:
    r = routes
    if origin:
        r = r[r["origin"] == origin.upper()]
    if destination:
        r = r[r["destination"] == destination.upper()]
    if airline:
        r = r[r["airline_list"].str.contains(airline, case=False, na=False)]
    return r[r["flights"] >= min_flights]
