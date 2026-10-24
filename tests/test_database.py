"""Tests for the SQLite layer (src/database.py) using a temp database."""

import pandas as pd

from src import database
from src.data_processor import derive_airports


def test_insert_and_retrieve_flights(flights_df, tmp_db):
    stored = database.insert_flights(flights_df, tmp_db)
    assert stored == 3
    assert database.count_rows("flights", tmp_db) == 3
    back = database.fetch_flights(db_path=tmp_db)
    assert len(back) == 3
    assert set(back["flight_iata"]) == {"EA100", "MC220", "EA777"}


def test_refresh_does_not_duplicate(flights_df, tmp_db):
    database.insert_flights(flights_df, tmp_db)
    database.insert_flights(flights_df, tmp_db)  # second refresh, same rows
    assert database.count_rows("flights", tmp_db) == 3


def test_filters(flights_df, tmp_db):
    database.insert_flights(flights_df, tmp_db)
    delayed = database.fetch_flights(delayed_only=True, db_path=tmp_db)
    assert set(delayed["flight_iata"]) == {"EA100", "EA777"}
    cancelled = database.fetch_flights(status="cancelled", db_path=tmp_db)
    assert len(cancelled) == 1
    route = database.fetch_flights(dep_iata="jfk", db_path=tmp_db)
    assert len(route) == 2
    found = database.fetch_flights(search="miami", db_path=tmp_db)
    assert len(found) == 1


def test_airports_roundtrip(flights_df, tmp_db):
    airports = derive_airports(flights_df)
    assert database.insert_airports(airports, tmp_db) == 4
    back = database.fetch_airports(tmp_db)
    assert len(back) == 4
    assert back.iloc[0]["sightings"] >= back.iloc[-1]["sightings"]


def test_refresh_log_and_info(tmp_db):
    database.log_refresh("test", 10, 9, 9, "success", "ok", tmp_db)
    info = database.database_info(tmp_db)
    assert info["exists"]
    assert info["refreshes"] == 1
    assert info["last_success"] is not None


def test_export_csv(flights_df, tmp_db, tmp_path):
    database.insert_flights(flights_df, tmp_db)
    path = database.export_table("flights", "csv", tmp_path, tmp_db)
    assert path.exists()
    assert len(pd.read_csv(path)) == 3


def test_export_json(flights_df, tmp_db, tmp_path):
    database.insert_flights(flights_df, tmp_db)
    path = database.export_table("flights", "json", tmp_path, tmp_db)
    assert path.exists()
    import json
    assert len(json.loads(path.read_text())) == 3


def test_empty_insert_is_safe(tmp_db):
    assert database.insert_flights(pd.DataFrame(), tmp_db) == 0
    assert database.insert_airports(pd.DataFrame(), tmp_db) == 0
