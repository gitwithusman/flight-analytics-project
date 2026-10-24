"""Tests for the Pydantic validation layer (src/models.py)."""

import pytest
from pydantic import ValidationError

from src.models import FlightRecord, validate_flight_records


def test_valid_record_passes(sample_raw_records):
    record = FlightRecord.model_validate(sample_raw_records[0])
    assert record.flight_status == "active"
    assert record.departure.iata == "JFK"
    assert record.departure.delay == 15
    assert record.live.latitude == 39.5


def test_unknown_status_is_rejected(sample_raw_records):
    bad = dict(sample_raw_records[0], flight_status="teleported")
    with pytest.raises(ValidationError):
        FlightRecord.model_validate(bad)


def test_bad_date_is_rejected(sample_raw_records):
    bad = dict(sample_raw_records[0], flight_date="not-a-date")
    with pytest.raises(ValidationError):
        FlightRecord.model_validate(bad)


def test_missing_departure_block_rejected(sample_raw_records):
    bad = dict(sample_raw_records[0])
    bad.pop("departure")
    with pytest.raises(ValidationError):
        FlightRecord.model_validate(bad)


def test_negative_delay_rejected(sample_raw_records):
    bad = dict(sample_raw_records[0])
    bad["departure"] = dict(bad["departure"], delay=-5)
    with pytest.raises(ValidationError):
        FlightRecord.model_validate(bad)


def test_invalid_latitude_rejected(sample_raw_records):
    bad = dict(sample_raw_records[0])
    bad["live"] = dict(bad["live"], latitude=999)
    with pytest.raises(ValidationError):
        FlightRecord.model_validate(bad)


def test_optional_sections_may_be_null(sample_raw_records):
    record = FlightRecord.model_validate(sample_raw_records[1])
    assert record.aircraft is None
    assert record.live is None
    assert record.flight.codeshared["airline_name"] == "Partner Air"


def test_batch_validation_separates_good_from_bad(sample_raw_records):
    raw = sample_raw_records + [
        dict(sample_raw_records[0], flight_status="bogus"),
        dict(sample_raw_records[0], flight_date="xx"),
    ]
    valid, errors = validate_flight_records(raw)
    assert len(valid) == 3
    assert len(errors) == 2
    assert all("record" in e for e in errors)


def test_iata_codes_are_normalised(sample_raw_records):
    raw = dict(sample_raw_records[0])
    raw["departure"] = dict(raw["departure"], iata=" jfk ")
    record = FlightRecord.model_validate(raw)
    assert record.departure.iata == "JFK"
