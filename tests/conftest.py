"""Shared pytest fixtures - a realistic AviationStack-style payload."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def sample_raw_records():
    """Records shaped exactly like the /v1/flights 'data' array."""
    return [
        {
            "flight_date": "2026-10-09",
            "flight_status": "active",
            "departure": {
                "airport": "John F Kennedy International",
                "timezone": "America/New_York",
                "iata": "JFK",
                "icao": "KJFK",
                "terminal": "4",
                "gate": "B22",
                "delay": 15,
                "scheduled": "2026-10-09T13:00:00+00:00",
                "estimated": "2026-10-09T13:15:00+00:00",
                "actual": "2026-10-09T13:14:00+00:00",
                "estimated_runway": None,
                "actual_runway": None,
            },
            "arrival": {
                "airport": "Los Angeles International",
                "timezone": "America/Los_Angeles",
                "iata": "LAX",
                "icao": "KLAX",
                "terminal": "6",
                "gate": "64",
                "baggage": "3",
                "delay": None,
                "scheduled": "2026-10-09T16:30:00+00:00",
                "estimated": "2026-10-09T16:45:00+00:00",
                "actual": None,
            },
            "airline": {"name": "Example Air", "iata": "EA", "icao": "EXA"},
            "flight": {"number": "100", "iata": "EA100", "icao": "EXA100",
                       "codeshared": None},
            "aircraft": {"registration": "N123EX", "iata": "B789",
                         "icao": "B789", "icao24": "A12345"},
            "live": {"updated": "2026-10-09T15:00:00+00:00",
                     "latitude": 39.5, "longitude": -98.3,
                     "altitude": 11000.0, "direction": 270.0,
                     "speed_horizontal": 850.0, "speed_vertical": 0.0,
                     "is_ground": False},
        },
        {
            "flight_date": "2026-10-09",
            "flight_status": "cancelled",
            "departure": {
                "airport": "Chicago O'Hare International",
                "timezone": "America/Chicago",
                "iata": "ORD",
                "icao": "KORD",
                "delay": None,
                "scheduled": "2026-10-09T12:00:00+00:00",
            },
            "arrival": {
                "airport": "Los Angeles International",
                "timezone": "America/Los_Angeles",
                "iata": "LAX",
                "icao": "KLAX",
                "delay": None,
                "scheduled": "2026-10-09T14:00:00+00:00",
            },
            "airline": {"name": "Midwest Connect", "iata": "MC", "icao": "MWC"},
            "flight": {"number": "220", "iata": "MC220", "icao": "MWC220",
                       "codeshared": {"airline_name": "Partner Air",
                                      "flight_number": "88"}},
            "aircraft": None,
            "live": None,
        },
        {
            "flight_date": "2026-10-09",
            "flight_status": "landed",
            "departure": {
                "airport": "John F Kennedy International",
                "timezone": "America/New_York",
                "iata": "JFK",
                "icao": "KJFK",
                "delay": 45,
                "scheduled": "2026-10-09T08:00:00+00:00",
            },
            "arrival": {
                "airport": "Miami International",
                "timezone": "America/New_York",
                "iata": "MIA",
                "icao": "KMIA",
                "delay": 20,
                "scheduled": "2026-10-09T11:00:00+00:00",
            },
            "airline": {"name": "Example Air", "iata": "EA", "icao": "EXA"},
            "flight": {"number": "777", "iata": "EA777", "icao": "EXA777",
                       "codeshared": None},
            "aircraft": None,
            "live": None,
        },
    ]


@pytest.fixture()
def valid_records(sample_raw_records):
    from src.models import validate_flight_records

    valid, errors = validate_flight_records(sample_raw_records)
    assert not errors
    return valid


@pytest.fixture()
def flights_df(valid_records):
    from src.data_processor import records_to_dataframe

    return records_to_dataframe(valid_records)


@pytest.fixture()
def tmp_db(tmp_path):
    return tmp_path / "test_flight_airport.db"


@pytest.fixture(autouse=True)
def _clear_response_caches():
    """Caches are per-process; every test starts without answers cached by an earlier test."""
    from src import api_client
    from src.providers import weather

    api_client._WEATHER_CACHE.clear()
    weather._RESULT_CACHE.clear()
    yield
