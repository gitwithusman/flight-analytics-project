"""Tests for pandas transformation (src/data_processor.py)."""

import pandas as pd

from src.data_processor import (
    FLIGHT_COLUMNS,
    clean_flights,
    derive_airports,
    quality_report,
    records_to_dataframe,
)


def test_records_to_dataframe_shape(flights_df):
    assert len(flights_df) == 3
    assert list(flights_df.columns) == FLIGHT_COLUMNS


def test_flattened_values(flights_df):
    row = flights_df[flights_df["flight_iata"] == "EA100"].iloc[0]
    assert row["dep_iata"] == "JFK"
    assert row["arr_iata"] == "LAX"
    assert row["route"] == "JFK-LAX"
    assert row["dep_delay_min"] == 15
    assert row["is_delayed"]
    assert row["airline_name"] == "Example Air"


def test_derived_delay_columns(flights_df):
    landed = flights_df[flights_df["flight_iata"] == "EA777"].iloc[0]
    assert landed["max_delay_min"] == 45
    cancelled = flights_df[flights_df["flight_iata"] == "MC220"].iloc[0]
    assert pd.isna(cancelled["max_delay_min"])
    assert not cancelled["is_delayed"]


def test_codeshare_flag(flights_df):
    codeshared = flights_df[flights_df["is_codeshared"]]
    assert list(codeshared["flight_iata"]) == ["MC220"]


def test_duplicate_rows_removed(valid_records):
    df = records_to_dataframe(valid_records + [valid_records[0]])
    assert len(df) == 3


def test_scheduled_times_parsed(flights_df):
    assert pd.api.types.is_datetime64_any_dtype(flights_df["dep_scheduled"])


def test_derive_airports_counts(flights_df):
    airports = derive_airports(flights_df)
    by_iata = airports.set_index("iata")
    assert set(by_iata.index) == {"JFK", "LAX", "ORD", "MIA"}
    assert by_iata.loc["JFK", "departures"] == 2
    assert by_iata.loc["LAX", "arrivals"] == 2
    assert by_iata.loc["JFK", "airport_name"] == "John F Kennedy International"


def test_derive_airports_empty():
    airports = derive_airports(pd.DataFrame())
    assert airports.empty
    assert "iata" in airports.columns


def test_quality_report(flights_df):
    report = quality_report(flights_df)
    assert report["rows"] == 3
    assert report["duplicate_rows"] == 0
    assert report["unique_flights"] == 3
    assert report["delay_data_available"]


def test_quality_report_empty():
    report = quality_report(pd.DataFrame())
    assert report["rows"] == 0
    assert not report["delay_data_available"]


def test_clean_flights_handles_none_values():
    df = clean_flights(pd.DataFrame([{
        "flight_date": "2026-10-09", "flight_status": "active",
        "flight_iata": "XX1", "dep_iata": None, "arr_iata": "LAX",
        "dep_delay_min": None, "arr_delay_min": None,
    }]))
    assert len(df) == 1
    assert pd.isna(df.iloc[0]["dep_iata"])
