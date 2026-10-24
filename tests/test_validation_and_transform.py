"""Pydantic rules, timezone handling and pandas transformation decisions."""

import copy

import pandas as pd
import pytest

from src import data_processor, models, timeutils


def _rec(sample, **patch):
    rec = copy.deepcopy(sample[0])
    for key, value in patch.items():
        rec[key] = value
    return rec


@pytest.mark.parametrize("mutate,field", [
    (lambda r: r["departure"].update(iata="JFKX"), "departure.iata"),
    (lambda r: r["departure"].update(icao="KJ"), "departure.icao"),
    (lambda r: r["airline"].update(iata="EAX"), "airline.iata"),
    (lambda r: r["departure"].update(delay=-1), "departure.delay"),
    (lambda r: r["departure"].update(delay=99999), "departure.delay"),
    (lambda r: r["departure"].update(scheduled="yesterday"), "departure.scheduled"),
    (lambda r: r["live"].update(latitude=123), "live.latitude"),
    (lambda r: r.update(flight_status="exploded"), "flight_status"),
    (lambda r: r.update(flight_date="09-10-2026"), "flight_date"),
])
def test_each_rule_rejects_with_a_field_level_reason(sample_raw_records, mutate, field):
    rec = _rec(sample_raw_records)
    mutate(rec)
    report = models.validate_batch([rec])
    assert report.rejected_count == 1
    assert field in {e["field"] for e in report.rejected[0].errors}


def test_unidentifiable_and_arrival_before_departure_are_rejected(sample_raw_records):
    no_id = _rec(sample_raw_records, flight={"number": None, "iata": None, "icao": None})
    no_airport = _rec(sample_raw_records)
    no_airport["departure"]["iata"] = no_airport["arrival"]["iata"] = None
    time_travel = _rec(sample_raw_records)
    time_travel["arrival"]["scheduled"] = "2026-10-09T09:00:00+00:00"
    report = models.validate_batch([no_id, no_airport, time_travel])
    assert report.rejected_count == 3 and report.accepted_count == 0
    assert report.acceptance_rate == 0.0


def test_consistency_rule_is_timezone_aware(sample_raw_records):
    """Wall-clock arrival 'earlier' than departure is fine when it crosses zones
    (depart Tokyo 23:00, arrive Honolulu 11:00 same date)."""
    rec = _rec(sample_raw_records)
    rec["departure"].update(timezone="Asia/Tokyo", scheduled="2026-10-09T23:00:00+00:00")
    rec["arrival"].update(timezone="Pacific/Honolulu", scheduled="2026-10-09T11:00:00+00:00")
    assert models.validate_batch([rec]).accepted_count == 1


def test_codes_are_normalised_and_blank_becomes_none(sample_raw_records):
    rec = _rec(sample_raw_records)
    rec["departure"]["iata"] = " jfk "
    rec["departure"]["terminal"] = "  "
    out = models.FlightRecord.model_validate(rec)
    assert out.departure.iata == "JFK"


def test_non_dict_records_do_not_crash():
    report = models.validate_batch([None, "text", 5, {}])
    assert report.rejected_count == 4 and report.accepted_count == 0


def test_error_breakdown_counts_rules(sample_raw_records):
    a = _rec(sample_raw_records, flight_status="x")
    b = _rec(sample_raw_records, flight_status="y")
    assert models.validate_batch([a, b]).error_breakdown() == {"flight_status": 2}


def test_second_gate_rejects_inconsistent_rows():
    ok = {"flight_date": "2026-10-09", "flight_status": "active", "dep_iata": "JFK",
          "arr_iata": "LAX", "is_delayed": False}
    bad_flag = dict(ok, is_delayed=True, max_delay_min=None)
    bad_dur = dict(ok, scheduled_duration_min=-4)
    bad_hour = dict(ok, dep_local_hour=27)
    positions, rejected = models.validate_rows([ok, bad_flag, bad_dur, bad_hour])
    assert positions == [0] and len(rejected) == 3
    assert {r.stage for r in rejected} == {"transform"}


# --- timezone correction -----------------------------------------------------
def test_resolve_timezone_variants():
    assert timeutils.resolve_timezone("Asia/Karachi") is not None
    assert timeutils.resolve_timezone("+8").utcoffset(None).total_seconds() == 8 * 3600
    assert timeutils.resolve_timezone("-05:30").utcoffset(None).total_seconds() == -5.5 * 3600
    assert timeutils.resolve_timezone("Mars/Base") is None
    assert timeutils.resolve_timezone(None) is None and timeutils.resolve_timezone("  ") is None


def test_wall_clock_is_reinterpreted_not_trusted():
    # 13:00 labelled +00:00 at JFK is 13:00 local (EDT, UTC-4) = 17:00 UTC.
    utc = timeutils.wall_clock_to_utc("2026-10-09T13:00:00+00:00", "America/New_York")
    assert utc.hour == 17
    assert timeutils.wall_clock_to_utc("2026-10-09T13:00:00+00:00", None) is None
    assert timeutils.wall_clock_to_utc("garbage", "Asia/Tokyo") is None


def test_duration_is_corrected_for_timezones(flights_df):
    row = flights_df.set_index("flight_iata").loc["EA100"]
    # JFK 13:00 EDT = 17:00 UTC; LAX 16:30 PDT = 23:30 UTC  ->  390 minutes
    # (the naive wall-clock difference would have said 210).
    assert row["scheduled_duration_min"] == pytest.approx(390)
    assert int(row["dep_local_hour"]) == 13


def test_missing_timezone_is_filled_from_same_airport(sample_raw_records):
    recs = copy.deepcopy(sample_raw_records)
    recs[1]["arrival"]["timezone"] = None            # LAX unknown here ...
    valid = models.validate_batch(recs).accepted     # ... but known in record 0
    df, report = data_processor.transform_records(valid)
    assert report.timezones_filled >= 1
    assert df.set_index("flight_iata").loc["MC220", "arr_timezone"] == "America/Los_Angeles"


def test_unresolvable_timezone_leaves_timestamp_null_not_guessed(sample_raw_records):
    recs = copy.deepcopy(sample_raw_records)
    recs[1]["arrival"]["timezone"] = None
    recs[1]["arrival"]["iata"] = "ZZZ"               # not known anywhere else
    valid = models.validate_batch(recs).accepted
    df, report = data_processor.transform_records(valid)
    row = df.set_index("flight_iata").loc["MC220"]
    assert pd.isna(row["arr_scheduled"]) and pd.isna(row["scheduled_duration_min"])
    assert report.timestamps_unlocalised >= 1
    assert int(row["dep_local_hour"]) == 12          # still known without a timezone


def test_transform_report_and_decisions(valid_records):
    df, report = data_processor.transform_records(valid_records)
    assert report.rows_in == 3 and report.rows_out == 3 and report.rows_rejected == 0
    assert report.missing_by_column
    assert len(data_processor.TRANSFORM_DECISIONS) >= 8
    assert df["is_delayed"].dtype == bool
    assert str(df["dep_scheduled"].dtype).startswith("datetime64")
    assert df["max_delay_min"].isna().sum() == 1     # missing delay is NOT imputed as 0


def test_timestamp_semantics_check_function():
    from src import eda
    payload = {"data": [{"flight": {"iata": "XX1"},
                         "departure": {"iata": "HND", "timezone": "Asia/Tokyo",
                                       "actual": "2026-10-09T10:00:00+00:00"},
                         "live": {"updated": "2026-10-09T01:30:00+00:00"}}]}
    row = eda.timestamp_semantics_check([payload]).iloc[0]
    assert row["minutes_after_departure_literal"] == -510
    assert row["minutes_after_departure_wallclock"] == 30


def test_impossible_ordering_is_rejected_even_without_timezones(sample_raw_records):
    rec = _rec(sample_raw_records)
    rec["departure"]["timezone"] = rec["arrival"]["timezone"] = None
    rec["arrival"]["scheduled"] = "2000-01-01T00:00:00+00:00"
    assert models.validate_batch([rec]).rejected_count == 1
    ok = _rec(sample_raw_records)               # 3.5 h apart, no timezones -> fine
    ok["departure"]["timezone"] = ok["arrival"]["timezone"] = None
    assert models.validate_batch([ok]).accepted_count == 1
