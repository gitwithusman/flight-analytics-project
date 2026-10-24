"""Schema v2: constraints, migration from v1, integrity verification."""

import sqlite3

import pytest

from src import database
from src.utils import DatabaseError


def test_schema_constraints_reject_bad_rows(tmp_db):
    database.initialise_database(tmp_db)
    conn = sqlite3.connect(tmp_db)
    now = "2026-10-09"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO flights (flight_date, flight_status, first_seen_at, updated_at) "
                     "VALUES ('2026-10-09', 'exploded', ?, ?)", (now, now))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO flights (flight_date, flight_status, max_delay_min, first_seen_at, "
                     "updated_at) VALUES ('2026-10-09', 'active', -3, ?, ?)", (now, now))
    conn.close()


def test_natural_key_is_unique(tmp_db, flights_df):
    database.insert_flights(flights_df, tmp_db)
    conn = sqlite3.connect(tmp_db)
    row = conn.execute("SELECT flight_date, flight_iata, dep_iata, arr_iata, flight_status, "
                       "first_seen_at, updated_at FROM flights LIMIT 1").fetchone()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO flights (flight_date, flight_iata, dep_iata, arr_iata, "
                     "flight_status, first_seen_at, updated_at) VALUES (?,?,?,?,?,?,?)", row)
    conn.close()


def test_upsert_keeps_first_seen_and_counts(tmp_db, flights_df):
    first = database.load_batch(flights_df, source="t", fetched=3, valid=3, db_path=tmp_db)
    assert (first.inserted, first.updated) == (3, 0)
    before = database.fetch_flights(db_path=tmp_db).set_index("flight_iata")["first_seen_at"]
    second = database.load_batch(flights_df, source="t", fetched=3, valid=3, db_path=tmp_db)
    assert (second.inserted, second.updated) == (0, 3)
    after = database.fetch_flights(db_path=tmp_db).set_index("flight_iata")["first_seen_at"]
    assert before.equals(after.loc[before.index])


def test_foreign_key_links_rejections_to_runs(tmp_db):
    database.initialise_database(tmp_db)
    conn = sqlite3.connect(tmp_db)
    conn.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO rejected_records (run_id, stage, rejected_at) "
                     "VALUES (999, 'extract', 'now')")
    conn.close()


def test_migration_from_v1_keeps_rows_and_history(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE flights (id INTEGER PRIMARY KEY AUTOINCREMENT, flight_date TEXT,
            flight_status TEXT, flight_iata TEXT, dep_iata TEXT, arr_iata TEXT,
            max_delay_min REAL, retrieved_at TEXT,
            UNIQUE(flight_date, flight_iata, dep_iata, arr_iata) ON CONFLICT REPLACE);
        CREATE TABLE airports (id INTEGER PRIMARY KEY AUTOINCREMENT, iata TEXT UNIQUE NOT NULL,
            icao TEXT, airport_name TEXT, timezone TEXT, departures INTEGER DEFAULT 0,
            arrivals INTEGER DEFAULT 0, sightings INTEGER DEFAULT 0);
        CREATE TABLE refresh_log (id INTEGER PRIMARY KEY AUTOINCREMENT, refreshed_at TEXT NOT NULL,
            source TEXT, records_fetched INTEGER, records_valid INTEGER, records_stored INTEGER,
            status TEXT, message TEXT);
        INSERT INTO flights (flight_date, flight_status, flight_iata, dep_iata, arr_iata,
            max_delay_min, retrieved_at) VALUES ('2026-10-09','active','AB1','JFK','LAX',5,'2026-10-09 05:00:00 UTC');
        INSERT INTO refresh_log (refreshed_at, source, status) VALUES ('2026-10-09','x','success');
    """)
    conn.commit()
    conn.close()
    info = database.initialise_database(path)
    assert info["schema_version"] == 4 and "rejected_records" in info["tables"]
    assert {"saved_searches", "airlines", "routes"} <= set(info["tables"]) and not [t for t in info["tables"] if "fare" in t]
    df = database.fetch_flights(db_path=path)
    assert len(df) == 1 and df.loc[0, "first_seen_at"] == "2026-10-09 05:00:00 UTC"
    assert database.count_rows("refresh_log", path) == 1
    # migrated DB accepts new-style upserts
    assert database.last_refresh(path)["records_rejected"] == 0


def test_verify_database_detects_problems(tmp_db, flights_df):
    database.insert_flights(flights_df, tmp_db)
    # stale airport tallies (the defect found in the original database)
    assert database.verify_database(tmp_db)["all_checks_passed"] is False
    with database.connect(tmp_db) as conn:
        database.rebuild_airports(conn)
    assert database.verify_database(tmp_db)["all_checks_passed"] is True


def test_bad_table_name_is_refused(tmp_db):
    with pytest.raises(ValueError):
        database.count_rows("flights; DROP TABLE flights", tmp_db)


def test_rebuild_derived_tables_after_migration(tmp_db, flights_df):
    database.insert_flights(flights_df, tmp_db)                    # flights only - derived tables still empty
    assert database.count_rows("airlines", tmp_db) == 0
    out = database.rebuild_derived_tables(tmp_db)
    assert out["airlines"] >= 1 and out["routes"] == 3 and out["airports"] >= 3
    assert database.count_rows("flights", tmp_db) == 3 and database.verify_database(tmp_db)["all_checks_passed"]
