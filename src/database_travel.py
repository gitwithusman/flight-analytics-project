"""Persistence for saved flight searches, search-run logging and live-status snapshots.

Kept separate from ``database.py`` (flights ETL) but uses the same connection
helper, schema and transaction rules.
"""

from __future__ import annotations

import sqlite3
from typing import Optional, Sequence

import pandas as pd

from . import database
from .utils import DatabaseError, utc_now_iso


def _clean(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        return v.item()
    return v


# --------------------------------------------------------------------------- search run log
def log_search_run(*, source: str, fetched: int, accepted: int, rejected: Sequence = (), status: str = "success",
                   message: str = "", duration_s: Optional[float] = None, data_origin: str = "live_api",
                   db_path=None) -> int:
    """Log one flight-search run (and its rejected options) atomically; returns the run id."""
    try:
        with database.connect(db_path) as conn:
            run_id = database._insert_log(conn, source, fetched, accepted, 0, status, message, len(rejected), 0, 0,
                                          duration_s, pipeline="flight_search", data_origin=data_origin)
            database._insert_rejected(conn, run_id, rejected)
        return run_id
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to log the flight search (rolled back): {exc}")


# --------------------------------------------------------------------------- saved searches
def save_search(name: str, origin: str, destination: str, departure_date: str, return_date: Optional[str],
                adults: int, cabin: str, db_path=None) -> int:
    with database.connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO saved_searches (name, origin_iata, destination_iata, departure_date, return_date, "
            "adults, cabin, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (name.strip() or f"{origin.upper()}-{destination.upper()}", origin.upper(), destination.upper(), departure_date,
             return_date, int(adults), cabin, utc_now_iso()))
        return int(cur.lastrowid)


def list_saved_searches(db_path=None) -> pd.DataFrame:
    with database.connect(db_path) as conn:
        return pd.read_sql_query("SELECT * FROM saved_searches ORDER BY id DESC", conn)


def delete_saved_search(search_id: int, db_path=None) -> bool:
    with database.connect(db_path) as conn:
        return conn.execute("DELETE FROM saved_searches WHERE id = ?", (int(search_id),)).rowcount > 0


# --------------------------------------------------------------------------- status snapshots
def insert_status_observations(df: pd.DataFrame, db_path=None) -> int:
    if df.empty:
        return 0
    cols = list(df.columns)
    sql = (f"INSERT OR IGNORE INTO flight_status_observations ({', '.join(cols)}) "
           f"VALUES ({', '.join('?' for _ in cols)})")
    with database.connect(db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM flight_status_observations").fetchone()[0]
        conn.executemany(sql, [tuple(_clean(r[c]) for c in cols) for r in df.to_dict("records")])
        return conn.execute("SELECT COUNT(*) FROM flight_status_observations").fetchone()[0] - before


def fetch_status_observations(db_path=None, limit: int = 500) -> pd.DataFrame:
    with database.connect(db_path) as conn:
        return pd.read_sql_query("SELECT * FROM flight_status_observations ORDER BY id DESC LIMIT ?",
                                 conn, params=(limit,))
