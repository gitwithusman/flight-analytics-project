"""SQLite persistence layer for Flight and Airport Analytics.

Design goals (the "Load" stage of the ETL pipeline):

* **Schema design** - three entity tables (``flights``, ``airports``,
  ``refresh_log``) plus ``rejected_records`` (an audit trail of everything
  Pydantic refused). Every table has an integer primary key; ``flights`` also
  carries a *natural* UNIQUE key (flight_date, flight_iata, dep_iata,
  arr_iata) and CHECK constraints for status and delay values;
  ``rejected_records.run_id`` is a foreign key to ``refresh_log``.
* **Duplicate prevention** - loading uses ``INSERT ... ON CONFLICT DO UPDATE``
  (a true upsert), so re-running the pipeline refreshes existing flights
  instead of duplicating them, and the original ``id`` / ``first_seen_at``
  survive.
* **Safe operations** - only parameterised SQL; identifiers that cannot be
  parameterised are checked against allow-lists.
* **Reliable transactions** - :func:`load_batch` writes flights, airports,
  the run log and rejected records in ONE transaction: either the whole batch
  is stored or nothing is.
* **Migration** - databases created by earlier versions are upgraded in place
  (user_version 4) without losing flight rows or run history.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Sequence

import pandas as pd

from . import config
from .data_processor import FLIGHT_COLUMNS, UNIQUE_KEY
from .utils import DatabaseError, get_logger, utc_now_iso

logger = get_logger()

SCHEMA_VERSION = 4

_FLIGHT_COLUMN_DDL = """
    flight_date TEXT NOT NULL,
    flight_status TEXT NOT NULL
        CHECK (flight_status IN
               ('scheduled','active','landed','cancelled','incident','diverted')),
    flight_iata TEXT NOT NULL DEFAULT '',
    flight_icao TEXT,
    flight_number TEXT,
    airline_name TEXT,
    airline_iata TEXT,
    airline_icao TEXT,
    dep_airport TEXT,
    dep_iata TEXT NOT NULL DEFAULT '',
    dep_icao TEXT,
    dep_terminal TEXT,
    dep_gate TEXT,
    dep_delay_min REAL CHECK (dep_delay_min IS NULL OR dep_delay_min >= 0),
    dep_scheduled TEXT,
    dep_estimated TEXT,
    dep_actual TEXT,
    dep_timezone TEXT,
    arr_airport TEXT,
    arr_iata TEXT NOT NULL DEFAULT '',
    arr_icao TEXT,
    arr_terminal TEXT,
    arr_gate TEXT,
    arr_baggage TEXT,
    arr_delay_min REAL CHECK (arr_delay_min IS NULL OR arr_delay_min >= 0),
    arr_scheduled TEXT,
    arr_estimated TEXT,
    arr_actual TEXT,
    arr_timezone TEXT,
    aircraft_registration TEXT,
    aircraft_icao24 TEXT,
    is_codeshared INTEGER NOT NULL DEFAULT 0 CHECK (is_codeshared IN (0, 1)),
    live_latitude REAL,
    live_longitude REAL,
    live_altitude REAL,
    live_speed_kmh REAL,
    live_is_ground INTEGER,
    route TEXT,
    is_delayed INTEGER NOT NULL DEFAULT 0 CHECK (is_delayed IN (0, 1)),
    max_delay_min REAL CHECK (max_delay_min IS NULL OR max_delay_min >= 0),
    scheduled_duration_min REAL,
    dep_local_hour INTEGER CHECK (dep_local_hour IS NULL OR dep_local_hour BETWEEN 0 AND 23),
    retrieved_at TEXT,
    first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (flight_date, flight_iata, dep_iata, arr_iata)
"""

_FLIGHTS_DDL = (
    "CREATE TABLE flights (\n    id INTEGER PRIMARY KEY AUTOINCREMENT,"
    + _FLIGHT_COLUMN_DDL
    + ")"
)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS flights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,{_FLIGHT_COLUMN_DDL});

CREATE TABLE IF NOT EXISTS airports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    iata TEXT UNIQUE NOT NULL,
    icao TEXT,
    airport_name TEXT,
    timezone TEXT,
    departures INTEGER NOT NULL DEFAULT 0,
    arrivals INTEGER NOT NULL DEFAULT 0,
    sightings INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS refresh_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    refreshed_at TEXT NOT NULL,
    source TEXT,
    records_fetched INTEGER,
    records_valid INTEGER,
    records_stored INTEGER,
    status TEXT,
    message TEXT,
    records_rejected INTEGER NOT NULL DEFAULT 0,
    records_inserted INTEGER NOT NULL DEFAULT 0,
    records_updated INTEGER NOT NULL DEFAULT 0,
    duration_s REAL,
    pipeline TEXT NOT NULL DEFAULT 'flights',
    data_origin TEXT NOT NULL DEFAULT 'live_api'
);

CREATE TABLE IF NOT EXISTS rejected_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES refresh_log(id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK (stage IN ('extract', 'transform')),
    record_index INTEGER,
    identifier TEXT,
    error_fields TEXT,
    error_messages TEXT,
    raw_json TEXT,
    rejected_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS airport_reference (
    iata TEXT PRIMARY KEY,
    icao TEXT,
    name TEXT,
    city TEXT,
    country_code TEXT,
    country TEXT,
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    elevation_ft REAL,
    airport_type TEXT,
    source TEXT NOT NULL DEFAULT 'OurAirports'
);

CREATE TABLE IF NOT EXISTS airlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    iata TEXT UNIQUE NOT NULL,
    name TEXT,
    icao TEXT,
    flights INTEGER NOT NULL DEFAULT 0,
    routes INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin_iata TEXT NOT NULL,
    destination_iata TEXT NOT NULL,
    flights INTEGER NOT NULL DEFAULT 0,
    airlines INTEGER NOT NULL DEFAULT 0,
    UNIQUE (origin_iata, destination_iata)
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    origin_iata TEXT NOT NULL,
    destination_iata TEXT NOT NULL,
    departure_date TEXT NOT NULL,
    return_date TEXT,
    adults INTEGER NOT NULL DEFAULT 1,
    cabin TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS flight_status_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    data_origin TEXT NOT NULL CHECK (data_origin IN ('live_api', 'sample')),
    flight_iata TEXT NOT NULL,
    flight_date TEXT,
    airline_name TEXT,
    dep_iata TEXT,
    arr_iata TEXT,
    dep_scheduled TEXT,
    dep_estimated TEXT,
    dep_actual TEXT,
    arr_scheduled TEXT,
    arr_estimated TEXT,
    arr_actual TEXT,
    status TEXT,
    dep_delay_min REAL,
    arr_delay_min REAL,
    api_updated TEXT,
    UNIQUE (flight_iata, flight_date, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_status_flight ON flight_status_observations(flight_iata);
CREATE INDEX IF NOT EXISTS idx_routes_origin ON routes(origin_iata);

CREATE INDEX IF NOT EXISTS idx_flights_status ON flights(flight_status);
CREATE INDEX IF NOT EXISTS idx_flights_airline ON flights(airline_name);
CREATE INDEX IF NOT EXISTS idx_flights_dep ON flights(dep_iata);
CREATE INDEX IF NOT EXISTS idx_flights_arr ON flights(arr_iata);
CREATE INDEX IF NOT EXISTS idx_flights_date ON flights(flight_date);
CREATE INDEX IF NOT EXISTS idx_rejected_run ON rejected_records(run_id);
"""

_NON_KEY_COLUMNS = [c for c in FLIGHT_COLUMNS if c not in UNIQUE_KEY]
_ALLOWED_TABLES = {
    "flights", "airports", "refresh_log", "rejected_records", "airlines", "routes",
    "airport_reference", "saved_searches",
    "flight_status_observations",
}

# Databases whose schema has already been created in this process.
_SCHEMA_READY: set = set()


# ---------------------------------------------------------------------------
# Connections, schema creation and migration
# ---------------------------------------------------------------------------


def _migrate(conn: sqlite3.Connection) -> None:
    """Upgrade a database created by an earlier version (in place, atomic)."""
    flight_cols = [r[1] for r in conn.execute("PRAGMA table_info(flights)")]
    log_cols = [r[1] for r in conn.execute("PRAGMA table_info(refresh_log)")]
    needs_flights = bool(flight_cols) and "first_seen_at" not in flight_cols
    if not needs_flights and not (log_cols and "records_rejected" not in log_cols):
        return

    conn.isolation_level = None  # manual transaction control for DDL
    conn.execute("BEGIN IMMEDIATE")
    try:
        if needs_flights:
            conn.execute("ALTER TABLE flights RENAME TO flights_v1")
            conn.execute(_FLIGHTS_DDL)
            shared = [c for c in flight_cols if c in FLIGHT_COLUMNS]
            cols = ", ".join(shared)
            now = utc_now_iso()
            conn.execute(
                f"INSERT INTO flights ({cols}, first_seen_at, updated_at) "
                f"SELECT {cols}, COALESCE(retrieved_at, '{now}'), "
                f"COALESCE(retrieved_at, '{now}') FROM flights_v1 ORDER BY id"
            )
            conn.execute("DROP TABLE flights_v1")
            # NOTE: timestamps stored by schema v1 carry the API's spurious
            # '+00:00' (see timeutils.py). They are copied unchanged; rebuild
            # from the raw archive (`run_pipeline.py --replay-raw --rebuild`)
            # to obtain correctly localised values.
        if log_cols and "records_rejected" not in log_cols:
            for ddl in (
                "ALTER TABLE refresh_log ADD COLUMN records_rejected INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE refresh_log ADD COLUMN records_inserted INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE refresh_log ADD COLUMN records_updated INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE refresh_log ADD COLUMN duration_s REAL",
            ):
                conn.execute(ddl)
        conn.execute("COMMIT")
        logger.info("Database migrated to schema version %d", SCHEMA_VERSION)
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.isolation_level = ""


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """v2 -> v3: add the pipeline / data_origin columns to refresh_log."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(refresh_log)")]
    if cols and "pipeline" not in cols:
        conn.execute("ALTER TABLE refresh_log ADD COLUMN pipeline TEXT NOT NULL DEFAULT 'flights'")
    if cols and "data_origin" not in cols:
        conn.execute("ALTER TABLE refresh_log ADD COLUMN data_origin TEXT NOT NULL DEFAULT 'live_api'")


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """v3 -> v4: the fare feature was removed.

    Drops the ``fare_alerts`` and ``fare_observations`` tables and rebuilds
    ``saved_searches`` without its fare columns (target price, last minimum
    price, currency). Saved routes and dates are kept; flights, airports and the
    ETL run history are untouched. Old ``fares`` pipeline log rows are renamed
    to ``flight_search`` so the monitor never shows a removed pipeline.
    """
    conn.execute("DROP TABLE IF EXISTS fare_alerts")
    conn.execute("DROP TABLE IF EXISTS fare_observations")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(saved_searches)")]
    if cols and ("target_price" in cols or "currency" in cols):
        conn.execute("ALTER TABLE saved_searches RENAME TO saved_searches_old")
        conn.executescript(
            """CREATE TABLE saved_searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                origin_iata TEXT NOT NULL,
                destination_iata TEXT NOT NULL,
                departure_date TEXT NOT NULL,
                return_date TEXT,
                adults INTEGER NOT NULL DEFAULT 1,
                cabin TEXT,
                created_at TEXT NOT NULL
            );""")
        conn.execute(
            "INSERT INTO saved_searches (id, name, origin_iata, destination_iata, departure_date, return_date, "
            "adults, cabin, created_at) SELECT id, name, origin_iata, destination_iata, departure_date, "
            "return_date, adults, cabin, created_at FROM saved_searches_old")
        conn.execute("DROP TABLE saved_searches_old")
    log_cols = [r[1] for r in conn.execute("PRAGMA table_info(refresh_log)")]
    if "pipeline" in log_cols:
        conn.execute("UPDATE refresh_log SET pipeline = 'flight_search' WHERE pipeline = 'fares'")


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a connection (creating / migrating the schema on first use).

    The caller owns the connection and must close it - prefer the
    :func:`connect` context manager, which does so automatically.
    """
    path = Path(db_path) if db_path else config.DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path.resolve())
    if not path.exists():
        _SCHEMA_READY.discard(key)  # file was removed - rebuild the schema
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if key not in _SCHEMA_READY:
            _migrate(conn)
            _migrate_v3(conn)
            _migrate_v4(conn)
            conn.executescript(_SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            _SCHEMA_READY.add(key)
        return conn
    except sqlite3.Error as exc:
        raise DatabaseError(f"Cannot open database {path}: {exc}")


@contextmanager
def connect(db_path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """Yield a connection that commits on success, rolls back on error and
    is always closed (``with sqlite3.connect()`` alone never closes it,
    which leaked a file handle per query)."""
    conn = get_connection(db_path)
    try:
        with conn:  # transaction: commit / rollback
            yield conn
    finally:
        conn.close()


def initialise_database(db_path: Optional[Path] = None) -> dict:
    """Create (or migrate) the database and return its table overview."""
    from . import reference  # lazy: loads the airport reference table once
    with connect(db_path) as conn:
        reference.ensure_loaded(conn)
        return {
            "path": str(Path(db_path) if db_path else config.DATABASE_PATH),
            "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
            "tables": [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name")],
        }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _serializable(value):
    """Convert pandas/NaT values into SQLite-friendly scalars."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    if isinstance(value, bool):
        return int(value)
    return value


@dataclass
class LoadResult:
    """What one load did to the database."""

    inserted: int = 0
    updated: int = 0
    airports: int = 0
    run_id: Optional[int] = None

    @property
    def written(self) -> int:
        return self.inserted + self.updated


def _upsert_flights(conn: sqlite3.Connection, df: pd.DataFrame) -> tuple:
    """Upsert flight rows inside an open transaction -> (inserted, updated)."""
    if df.empty:
        return 0, 0
    columns = [c for c in FLIGHT_COLUMNS if c in df.columns]
    now = utc_now_iso()
    all_cols = columns + ["first_seen_at", "updated_at"]
    placeholders = ", ".join("?" for _ in all_cols)
    update_cols = [c for c in columns if c not in UNIQUE_KEY]
    set_clause = ", ".join(f"{c} = excluded.{c}" for c in update_cols + ["updated_at"])
    sql = (
        f"INSERT INTO flights ({', '.join(all_cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT({', '.join(UNIQUE_KEY)}) DO UPDATE SET {set_clause}"
    )
    rows = []
    for row in df[columns].itertuples(index=False, name=None):
        values = [_serializable(v) for v in row]
        for idx, col in enumerate(columns):
            # SQLite treats NULLs as distinct inside UNIQUE constraints, so the
            # natural-key columns use '' for "missing" to keep dedup reliable.
            if col in UNIQUE_KEY and values[idx] is None:
                values[idx] = ""
        rows.append(tuple(values) + (now, now))
    before = conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
    conn.executemany(sql, rows)
    after = conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
    inserted = after - before
    return inserted, len(rows) - inserted


def rebuild_airports(conn: sqlite3.Connection) -> int:
    """Recompute the ``airports`` table from ALL stored flights.

    Counting from the database (rather than from the latest batch) keeps the
    airport tallies consistent with the flights table after any number of
    pipeline runs.
    """
    conn.execute("DELETE FROM airports")
    conn.execute(
        """
        INSERT INTO airports (iata, icao, airport_name, timezone,
                              departures, arrivals, sightings)
        SELECT iata, MAX(icao), MAX(name), MAX(tz), SUM(d), SUM(a), SUM(d) + SUM(a)
        FROM (
            SELECT dep_iata AS iata, dep_icao AS icao, dep_airport AS name,
                   dep_timezone AS tz, 1 AS d, 0 AS a
            FROM flights WHERE dep_iata <> ''
            UNION ALL
            SELECT arr_iata, arr_icao, arr_airport, arr_timezone, 0, 1
            FROM flights WHERE arr_iata <> ''
        )
        GROUP BY iata
        ORDER BY SUM(d) + SUM(a) DESC
        """
    )
    return int(conn.execute("SELECT COUNT(*) FROM airports").fetchone()[0])


def rebuild_airlines(conn: sqlite3.Connection) -> int:
    """Recompute ``airlines`` from stored flights (airlines with an IATA code)."""
    conn.execute("DELETE FROM airlines")
    conn.execute(
        """
        INSERT INTO airlines (iata, name, icao, flights, routes)
        SELECT airline_iata, MAX(airline_name), MAX(airline_icao), COUNT(*),
               COUNT(DISTINCT dep_iata || '-' || arr_iata)
        FROM flights
        WHERE airline_iata IS NOT NULL AND airline_iata <> ''
        GROUP BY airline_iata
        ORDER BY COUNT(*) DESC
        """
    )
    return int(conn.execute("SELECT COUNT(*) FROM airlines").fetchone()[0])


def rebuild_routes(conn: sqlite3.Connection) -> int:
    """Recompute ``routes`` (origin -> destination) from stored flights."""
    conn.execute("DELETE FROM routes")
    conn.execute(
        """
        INSERT INTO routes (origin_iata, destination_iata, flights, airlines)
        SELECT dep_iata, arr_iata, COUNT(*), COUNT(DISTINCT airline_iata)
        FROM flights
        WHERE dep_iata <> '' AND arr_iata <> ''
        GROUP BY dep_iata, arr_iata
        ORDER BY COUNT(*) DESC
        """
    )
    return int(conn.execute("SELECT COUNT(*) FROM routes").fetchone()[0])


def rebuild_derived_tables(db_path: Optional[Path] = None) -> dict:
    """Recompute airports, airlines and routes from the stored flights (one transaction).

    Flights and the run history are not touched. Used after a schema migration
    and available as ``run_pipeline.py --rebuild-derived``.
    """
    try:
        with connect(db_path) as conn:
            return {"airports": rebuild_airports(conn), "airlines": rebuild_airlines(conn), "routes": rebuild_routes(conn)}
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to rebuild derived tables: {exc}")


def _insert_log(conn, source, fetched, valid, stored, status, message,
                rejected=0, inserted=0, updated=0, duration_s=None,
                pipeline="flights", data_origin="live_api") -> int:
    cur = conn.execute(
        """INSERT INTO refresh_log
           (refreshed_at, source, records_fetched, records_valid,
            records_stored, status, message, records_rejected,
            records_inserted, records_updated, duration_s, pipeline, data_origin)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (utc_now_iso(), source, fetched, valid, stored, status, message,
         rejected, inserted, updated, duration_s, pipeline, data_origin),
    )
    return int(cur.lastrowid)


def _insert_rejected(conn, run_id: int, rejected: Sequence) -> None:
    if not rejected:
        return
    now = utc_now_iso()
    rows = [
        (
            run_id, rec.stage, rec.index, rec.identifier,
            ", ".join(sorted({e["field"] for e in rec.errors})),
            " | ".join(e["message"] for e in rec.errors),
            json.dumps(rec.raw, default=str, ensure_ascii=False)
            if rec.raw is not None else None,
            now,
        )
        for rec in rejected
    ]
    conn.executemany(
        """INSERT INTO rejected_records
           (run_id, stage, record_index, identifier, error_fields,
            error_messages, raw_json, rejected_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )


def load_batch(
    flights_df: pd.DataFrame,
    *,
    source: str,
    fetched: int,
    valid: int,
    rejected: Sequence = (),
    status: str = "success",
    message: str = "",
    duration_s: Optional[float] = None,
    db_path: Optional[Path] = None,
) -> LoadResult:
    """Store one pipeline batch atomically.

    Flights are upserted, the airports table is rebuilt, the run is logged and
    every rejected record is archived - all inside a single transaction. If
    any step fails SQLite rolls everything back, so the database never holds a
    half-loaded batch.
    """
    try:
        with connect(db_path) as conn:
            inserted, updated = _upsert_flights(conn, flights_df)
            airports = rebuild_airports(conn)
            rebuild_airlines(conn)
            rebuild_routes(conn)
            run_id = _insert_log(
                conn, source, fetched, valid, inserted + updated, status,
                message, len(rejected), inserted, updated, duration_s,
            )
            _insert_rejected(conn, run_id, rejected)
        return LoadResult(inserted, updated, airports, run_id)
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to load batch (rolled back): {exc}")


def insert_flights(df: pd.DataFrame, db_path: Optional[Path] = None) -> int:
    """Upsert flight rows; returns the number of rows written (new + refreshed)."""
    if df.empty:
        return 0
    try:
        with connect(db_path) as conn:
            inserted, updated = _upsert_flights(conn, df)
        return inserted + updated
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to insert flights: {exc}")


def insert_airports(df: pd.DataFrame, db_path: Optional[Path] = None) -> int:
    """Upsert airport rows from a DataFrame (used by tests / manual loads)."""
    if df.empty:
        return 0
    sql = """
        INSERT INTO airports (iata, icao, airport_name, timezone,
                              departures, arrivals, sightings)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(iata) DO UPDATE SET
            icao = COALESCE(excluded.icao, airports.icao),
            airport_name = COALESCE(excluded.airport_name, airports.airport_name),
            timezone = COALESCE(excluded.timezone, airports.timezone),
            departures = excluded.departures,
            arrivals = excluded.arrivals,
            sightings = excluded.sightings
    """
    rows = [
        (
            _serializable(r.iata), _serializable(r.icao),
            _serializable(r.airport_name), _serializable(r.timezone),
            int(r.departures), int(r.arrivals), int(r.sightings),
        )
        for r in df.itertuples(index=False)
        if pd.notna(r.iata)
    ]
    try:
        with connect(db_path) as conn:
            conn.executemany(sql, rows)
        return len(rows)
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to insert airports: {exc}")


def log_refresh(
    source: str,
    fetched: int,
    valid: int,
    stored: int,
    status: str,
    message: str = "",
    db_path: Optional[Path] = None,
    *,
    rejected: int = 0,
    inserted: int = 0,
    updated: int = 0,
    duration_s: Optional[float] = None,
    pipeline: str = "flights",
    data_origin: str = "live_api",
) -> int:
    """Append one row to ``refresh_log`` and return its id."""
    with connect(db_path) as conn:
        return _insert_log(conn, source, fetched, valid, stored, status,
                           message, rejected, inserted, updated, duration_s,
                           pipeline, data_origin)


def last_refresh(db_path: Optional[Path] = None) -> Optional[dict]:
    """Most recent refresh-log entry, or None."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM refresh_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def last_successful_refresh(db_path: Optional[Path] = None) -> Optional[dict]:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM refresh_log WHERE status IN ('success', 'partial') "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def _query(sql: str, params: tuple = (), db_path: Optional[Path] = None) -> pd.DataFrame:
    try:
        with connect(db_path) as conn:
            return pd.read_sql_query(sql, conn, params=params)
    except sqlite3.Error as exc:
        raise DatabaseError(f"Query failed: {exc}")


def fetch_flights(
    status: Optional[str] = None,
    airline: Optional[str] = None,
    dep_iata: Optional[str] = None,
    arr_iata: Optional[str] = None,
    search: Optional[str] = None,
    search_fields: Optional[List[str]] = None,
    delayed_only: bool = False,
    limit: int = 5000,
    db_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Retrieve flights with optional server-side filters."""
    clauses, params = [], []
    if status:
        clauses.append("flight_status = ?")
        params.append(status.lower())
    if airline:
        clauses.append("(airline_name LIKE ? OR airline_iata LIKE ?)")
        params += [f"%{airline}%", f"%{airline}%"]
    if dep_iata:
        clauses.append("dep_iata = ?")
        params.append(dep_iata.upper())
    if arr_iata:
        clauses.append("arr_iata = ?")
        params.append(arr_iata.upper())
    if delayed_only:
        clauses.append("COALESCE(max_delay_min, 0) > 0")
    if search:
        fields = search_fields or [
            "flight_iata", "flight_number", "airline_name",
            "dep_airport", "dep_iata", "arr_airport", "arr_iata", "route",
        ]
        safe = [f for f in fields if f in FLIGHT_COLUMNS]
        if safe:
            clauses.append("(" + " OR ".join(f"{f} LIKE ?" for f in safe) + ")")
            params += [f"%{search}%"] * len(safe)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(int(limit))
    return _query(
        f"SELECT * FROM flights {where} ORDER BY flight_date DESC, id DESC "
        f"LIMIT ?",
        tuple(params),
        db_path,
    )


def fetch_airports(db_path: Optional[Path] = None) -> pd.DataFrame:
    return _query(
        "SELECT * FROM airports ORDER BY sightings DESC", (), db_path
    )


def count_rows(table: str, db_path: Optional[Path] = None) -> int:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Unsupported table {table}")
    with connect(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def distinct_values(column: str, db_path: Optional[Path] = None) -> List[str]:
    if column not in FLIGHT_COLUMNS:
        return []
    rows = _query(
        f"SELECT DISTINCT {column} AS v FROM flights "
        f"WHERE {column} IS NOT NULL ORDER BY v",
        (),
        db_path,
    )
    return rows["v"].tolist()


def database_info(db_path: Optional[Path] = None) -> dict:
    path = Path(db_path) if db_path else config.DATABASE_PATH
    info = {
        "path": str(path),
        "exists": path.exists(),
        "size_kb": round(path.stat().st_size / 1024, 1) if path.exists() else 0,
        "flights": 0,
        "airports": 0,
        "refreshes": 0,
        "rejected": 0,
        "last_refresh": None,
        "last_success": None,
    }
    if path.exists():
        info["flights"] = count_rows("flights", path)
        info["airports"] = count_rows("airports", path)
        info["refreshes"] = count_rows("refresh_log", path)
        info["rejected"] = count_rows("rejected_records", path)
        last = last_refresh(path)
        last_ok = last_successful_refresh(path)
        info["last_refresh"] = last["refreshed_at"] if last else None
        info["last_refresh_status"] = last["status"] if last else None
        info["last_success"] = last_ok["refreshed_at"] if last_ok else None
    return info


def export_table(
    table: str,
    fmt: str = "csv",
    out_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> Path:
    """Export a table to CSV or JSON under ``data/processed/`` by default."""
    from .utils import timestamp_for_filename

    df = fetch_flights(db_path=db_path) if table == "flights" else fetch_airports(db_path)
    out_dir = Path(out_dir) if out_dir else config.DATA_PROCESSED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = fmt.lower()
    if fmt == "csv":
        path = out_dir / f"{table}_export_{timestamp_for_filename()}.csv"
        df.to_csv(path, index=False)
    elif fmt == "json":
        path = out_dir / f"{table}_export_{timestamp_for_filename()}.json"
        path.write_text(
            df.to_json(orient="records", indent=2, force_ascii=False),
            encoding="utf-8",
        )
    else:
        raise ValueError("fmt must be 'csv' or 'json'")
    return path


def clear_flights(db_path: Optional[Path] = None) -> None:
    """Remove all stored flight/airport rows (used by tests / resets)."""
    with connect(db_path) as conn:
        conn.execute("DELETE FROM flights")
        conn.execute("DELETE FROM airports")


def export_summary_json(summary: dict, name: str) -> Path:
    """Save an analytics summary dict under ``data/processed/``."""
    from .utils import save_json, timestamp_for_filename

    path = config.DATA_PROCESSED_DIR / f"{name}_{timestamp_for_filename()}.json"
    return save_json(summary, path)


# ---------------------------------------------------------------------------
# Verification helpers (used by the pipeline's final "verify" step and tests)
# ---------------------------------------------------------------------------


def fetch_rejected(run_id: Optional[int] = None,
                   db_path: Optional[Path] = None) -> pd.DataFrame:
    """Rejected-record audit trail (optionally for one pipeline run)."""
    sql = ("SELECT id, run_id, stage, record_index, identifier, error_fields, "
           "error_messages, rejected_at FROM rejected_records")
    params: tuple = ()
    if run_id is not None:
        sql += " WHERE run_id = ?"
        params = (run_id,)
    return _query(sql + " ORDER BY id", params, db_path)


def fetch_run_history(db_path: Optional[Path] = None) -> pd.DataFrame:
    """The full ``refresh_log`` (one row per pipeline run)."""
    return _query("SELECT * FROM refresh_log ORDER BY id", (), db_path)


def verify_database(db_path: Optional[Path] = None) -> dict:
    """Run integrity checks against the stored data using real SQL queries."""
    with connect(db_path) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_violations = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        flights = conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
        duplicate_keys = conn.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM flights "
            "GROUP BY flight_date, flight_iata, dep_iata, arr_iata "
            "HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        missing_key = conn.execute(
            "SELECT COUNT(*) FROM flights WHERE flight_iata = '' "
            "OR (dep_iata = '' AND arr_iata = '')"
        ).fetchone()[0]
        bad_status = conn.execute(
            "SELECT COUNT(*) FROM flights WHERE flight_status NOT IN "
            "('scheduled','active','landed','cancelled','incident','diverted')"
        ).fetchone()[0]
        negative_delay = conn.execute(
            "SELECT COUNT(*) FROM flights WHERE max_delay_min < 0"
        ).fetchone()[0]
        airport_sightings = conn.execute(
            "SELECT COALESCE(SUM(sightings), 0) FROM airports"
        ).fetchone()[0]
        airport_expected = conn.execute(
            "SELECT (SELECT COUNT(*) FROM flights WHERE dep_iata <> '') + "
            "(SELECT COUNT(*) FROM flights WHERE arr_iata <> '')"
        ).fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    ok = (integrity == "ok" and fk_violations == 0 and duplicate_keys == 0
          and missing_key == 0 and bad_status == 0 and negative_delay == 0
          and airport_sightings == airport_expected)
    return {
        "schema_version": version,
        "integrity_check": integrity,
        "foreign_key_violations": fk_violations,
        "flights": flights,
        "duplicate_natural_keys": duplicate_keys,
        "rows_missing_identity": missing_key,
        "invalid_status_rows": bad_status,
        "negative_delay_rows": negative_delay,
        "airport_sightings": airport_sightings,
        "airport_sightings_expected": airport_expected,
        "all_checks_passed": bool(ok),
    }


def schema_description(db_path: Optional[Path] = None) -> dict:
    """Column definitions per table (for documentation / the report)."""
    out = {}
    with connect(db_path) as conn:
        for table in sorted(_ALLOWED_TABLES):
            out[table] = [
                {"name": r[1], "type": r[2], "notnull": bool(r[3]),
                 "primary_key": bool(r[5])}
                for r in conn.execute(f"PRAGMA table_info({table})")
            ]
    return out
