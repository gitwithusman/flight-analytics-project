"""Queries behind the ETL Monitoring screen (run history, quality, logs)."""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional

import pandas as pd

from . import config, database
from .providers.http import scrub


def run_history(pipeline: Optional[str] = None, limit: int = 200, db_path=None) -> pd.DataFrame:
    sql = ("SELECT id, refreshed_at, pipeline, source, data_origin, status, records_fetched, records_valid, "
           "records_rejected, records_inserted, records_updated, duration_s, message FROM refresh_log")
    params: tuple = ()
    if pipeline:
        sql += " WHERE pipeline = ?"
        params = (pipeline,)
    sql += " ORDER BY id DESC LIMIT ?"
    with database.connect(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=params + (limit,))


def pipeline_overview(db_path=None) -> pd.DataFrame:
    """Per pipeline: runs, last run, last success, totals."""
    h = run_history(limit=100000, db_path=db_path)
    if h.empty:
        return pd.DataFrame(columns=["pipeline", "runs", "last_run", "last_status", "last_success", "records_loaded",
                                     "records_rejected", "avg_duration_s"])
    rows = []
    for p, g in h.groupby("pipeline"):
        ok = g[g["status"].isin(["success", "partial", "empty"])]
        rows.append({"pipeline": p, "runs": len(g), "last_run": g["refreshed_at"].iloc[0], "last_status": g["status"].iloc[0],
                     "last_success": ok["refreshed_at"].iloc[0] if len(ok) else None,
                     "records_loaded": int(g["records_inserted"].sum() + g["records_updated"].sum()),
                     "records_rejected": int(g["records_rejected"].sum()),
                     "avg_duration_s": round(float(g["duration_s"].dropna().mean()), 2) if g["duration_s"].notna().any() else None})
    return pd.DataFrame(rows)


def rejection_reasons(db_path=None) -> pd.DataFrame:
    with database.connect(db_path) as conn:
        return pd.read_sql_query(
            "SELECT r.error_fields AS field, r.stage, l.pipeline, COUNT(*) AS rejected FROM rejected_records r "
            "LEFT JOIN refresh_log l ON l.id = r.run_id GROUP BY r.error_fields, r.stage, l.pipeline "
            "ORDER BY rejected DESC", conn)


def quality_metrics(db_path=None) -> Dict:
    """Data-quality indicators computed from the stored tables."""
    with database.connect(db_path) as conn:
        q = lambda sql: conn.execute(sql).fetchone()[0]
        flights = q("SELECT COUNT(*) FROM flights")
        out = {
            "flights": flights,
            "flights_missing_delay_pct": round(100 * q("SELECT COUNT(*) FROM flights WHERE max_delay_min IS NULL") / flights, 1) if flights else None,
            "flights_missing_airline_pct": round(100 * q("SELECT COUNT(*) FROM flights WHERE airline_iata IS NULL OR airline_iata = ''") / flights, 1) if flights else None,
            "flights_missing_times_pct": round(100 * q("SELECT COUNT(*) FROM flights WHERE dep_scheduled IS NULL") / flights, 1) if flights else None,
            "airports_without_coordinates": q("SELECT COUNT(*) FROM airports a LEFT JOIN airport_reference r ON r.iata = a.iata WHERE r.iata IS NULL"),
            "duplicate_flight_keys": q("SELECT COUNT(*) FROM (SELECT 1 FROM flights GROUP BY flight_date, flight_iata, dep_iata, arr_iata HAVING COUNT(*) > 1)"),
            "rejected_records": q("SELECT COUNT(*) FROM rejected_records"),
        }
    out["integrity"] = database.verify_database(db_path)["all_checks_passed"]
    return out


def log_tail(lines: int = 200) -> List[str]:
    """Last log lines with any secret removed."""
    path = config.LOG_DIR / "application.log"
    if not path.exists():
        return []
    with open(path, "rb") as fh:                      # read only the end: the log can be a megabyte or more
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - max(65536, lines * 400)))
        raw = fh.read().decode("utf-8", errors="replace")
    tail = raw.splitlines()[-lines:]
    return [scrub(line.rstrip("\n")) for line in tail]
