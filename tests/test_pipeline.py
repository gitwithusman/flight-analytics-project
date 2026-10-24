"""End-to-end tests of the ETL pipeline (no network, no API key needed)."""

import copy
import json
import sqlite3

import pytest

from src import api_client, config, database, pipeline
from src.utils import APIError


@pytest.fixture()
def raw_file(tmp_path, sample_raw_records):
    path = tmp_path / "flights_raw_20261009_101516.json"
    payload = {"pagination": {"limit": 100, "offset": 0, "count": 3, "total": 3},
               "data": sample_raw_records}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _bad_payload(tmp_path, records):
    bad = copy.deepcopy(records)
    bad[0]["flight_status"] = "exploded"                      # bad vocabulary
    bad[1]["departure"]["delay"] = -5                          # negative delay
    bad[2]["flight"] = {"number": None, "iata": None, "icao": None}  # no identity
    extra = copy.deepcopy(records[0])
    extra["flight_date"] = "09/10/2026"                       # not ISO
    path = tmp_path / "flights_raw_20261010_000000.json"
    path.write_text(json.dumps({"data": bad + [extra]}), encoding="utf-8")
    return path


def test_pipeline_loads_valid_records(raw_file, tmp_db):
    report = pipeline.run_pipeline(raw_file=raw_file, db_path=tmp_db, save_artifacts=False)
    assert report.success and report.status == "success"
    assert (report.extracted, report.accepted, report.rejected_total) == (3, 3, 0)
    assert (report.inserted, report.updated) == (3, 0)
    assert report.verification["all_checks_passed"]
    assert database.count_rows("flights", tmp_db) == 3


def test_rerun_is_idempotent(raw_file, tmp_db):
    pipeline.run_pipeline(raw_file=raw_file, db_path=tmp_db, save_artifacts=False)
    ids_before = database.fetch_flights(db_path=tmp_db).sort_values("flight_iata")["id"].tolist()
    again = pipeline.run_pipeline(raw_file=raw_file, db_path=tmp_db, save_artifacts=False)
    assert (again.inserted, again.updated) == (0, 3)
    assert database.count_rows("flights", tmp_db) == 3
    ids_after = database.fetch_flights(db_path=tmp_db).sort_values("flight_iata")["id"].tolist()
    assert ids_before == ids_after            # true upsert: primary keys survive
    assert database.verify_database(tmp_db)["duplicate_natural_keys"] == 0


def test_rejected_records_are_reported_and_persisted(tmp_path, sample_raw_records, tmp_db):
    path = _bad_payload(tmp_path, sample_raw_records)
    report = pipeline.run_pipeline(raw_file=path, db_path=tmp_db, save_artifacts=False)
    assert report.status == "partial"
    assert report.extracted == 4 and report.accepted == 0 and report.rejected_extract == 4
    fields = report.rejection_breakdown
    assert "flight_status" in fields and "departure.delay" in fields and "flight_date" in fields
    audit = database.fetch_rejected(db_path=tmp_db)
    assert len(audit) == 4 and set(audit["stage"]) == {"extract"}
    assert audit["run_id"].nunique() == 1
    assert database.count_rows("flights", tmp_db) == 0


def test_mixed_batch_keeps_good_rows(tmp_path, sample_raw_records, tmp_db):
    mixed = copy.deepcopy(sample_raw_records)
    mixed[1]["flight_status"] = "nonsense"
    path = tmp_path / "mixed.json"
    path.write_text(json.dumps({"data": mixed}), encoding="utf-8")
    report = pipeline.run_pipeline(raw_file=path, db_path=tmp_db, save_artifacts=False)
    assert (report.accepted, report.rejected_total, report.inserted) == (2, 1, 2)


def test_in_batch_duplicates_are_removed(tmp_path, sample_raw_records, tmp_db):
    doubled = sample_raw_records + [copy.deepcopy(sample_raw_records[0])]
    path = tmp_path / "dup.json"
    path.write_text(json.dumps({"data": doubled}), encoding="utf-8")
    report = pipeline.run_pipeline(raw_file=path, db_path=tmp_db, save_artifacts=False)
    assert report.duplicates_removed == 1 and report.inserted == 3


def test_empty_response_is_handled(tmp_path, tmp_db):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"data": []}), encoding="utf-8")
    report = pipeline.run_pipeline(raw_file=path, db_path=tmp_db, save_artifacts=False)
    assert report.success and report.status == "empty" and report.extracted == 0
    assert database.last_refresh(tmp_db)["status"] == "empty"


def test_malformed_raw_file_raises_and_logs_failure(tmp_path, tmp_db):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(APIError):
        pipeline.run_pipeline(raw_file=path, db_path=tmp_db, save_artifacts=False)
    assert database.last_refresh(tmp_db)["status"] == "failed"


def test_missing_api_key_fails_cleanly_and_is_logged(monkeypatch, tmp_db):
    monkeypatch.setattr(config, "AVIATIONSTACK_API_KEY", "")
    with pytest.raises(Exception) as err:
        pipeline.run_pipeline(db_path=tmp_db, save_artifacts=False)
    assert "AVIATIONSTACK_API_KEY" in str(err.value)
    assert database.last_refresh(tmp_db)["status"] == "failed"


def test_load_is_atomic(raw_file, tmp_db, monkeypatch):
    """If any step of the load fails, NOTHING from the batch is stored."""
    def boom(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(database, "_insert_rejected", boom)
    with pytest.raises(Exception):
        pipeline.run_pipeline(raw_file=raw_file, db_path=tmp_db, save_artifacts=False)
    assert database.count_rows("flights", tmp_db) == 0
    assert database.count_rows("airports", tmp_db) == 0


def test_airports_are_rebuilt_from_all_stored_flights(raw_file, tmp_db):
    pipeline.run_pipeline(raw_file=raw_file, db_path=tmp_db, save_artifacts=False)
    pipeline.run_pipeline(raw_file=raw_file, db_path=tmp_db, save_artifacts=False)
    checks = database.verify_database(tmp_db)
    assert checks["airport_sightings"] == checks["airport_sightings_expected"] == 6


def test_replay_rebuild(raw_file, tmp_db):
    pipeline.run_pipeline(raw_file=raw_file, db_path=tmp_db, save_artifacts=False)
    reports = pipeline.replay_raw_files([raw_file], rebuild=True, db_path=tmp_db,
                                        save_artifacts=False)
    assert reports[0].inserted == 3
    assert database.count_rows("refresh_log", tmp_db) == 2     # history kept


def test_artifacts_written(raw_file, tmp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "DATA_PROCESSED_DIR", tmp_path / "proc")
    (tmp_path / "reports").mkdir()
    (tmp_path / "proc").mkdir()
    bad = _bad_payload(tmp_path, json.loads(raw_file.read_text())["data"])
    report = pipeline.run_pipeline(raw_file=bad, db_path=tmp_db)
    assert report.report_file and json.loads(open(report.report_file).read())["rejected_total"] == 4
    assert report.rejected_file and open(report.rejected_file).read().count("\n") == 5


# --- API client resilience ---------------------------------------------------
class _Resp:
    def __init__(self, status=200, payload=None, content=b"x"):
        self.status_code, self._payload, self.content = status, payload, content

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture()
def fast_api(monkeypatch):
    monkeypatch.setattr(config, "AVIATIONSTACK_API_KEY", "SECRETKEY123456")
    monkeypatch.setattr(config, "MAX_RETRIES", 2)
    monkeypatch.setattr(api_client, "_sleep_before_retry", lambda attempt: None)


def test_transient_failures_are_retried(fast_api, monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise api_client.requests.exceptions.Timeout()
        if calls["n"] == 2:
            return _Resp(503, None)
        return _Resp(200, {"data": [], "pagination": {}})
    monkeypatch.setattr(api_client.requests, "get", flaky)
    assert api_client.fetch_flights(limit=1, save_raw=False)["data"] == []
    assert calls["n"] == 3


def test_retries_are_bounded(fast_api, monkeypatch):
    calls = {"n": 0}

    def down(*a, **k):
        calls["n"] += 1
        raise api_client.requests.exceptions.ConnectionError()
    monkeypatch.setattr(api_client.requests, "get", down)
    with pytest.raises(APIError) as err:
        api_client.fetch_flights(limit=1, save_raw=False)
    assert calls["n"] == 3 and "3 attempts" in str(err.value)


def test_auth_error_is_not_retried(fast_api, monkeypatch):
    calls = {"n": 0}

    def bad_key(*a, **k):
        calls["n"] += 1
        return _Resp(401, {"error": {"code": "invalid_access_key", "message": "no"}})
    monkeypatch.setattr(api_client.requests, "get", bad_key)
    with pytest.raises(Exception):
        api_client.fetch_flights(limit=1, save_raw=False)
    assert calls["n"] == 1


def test_empty_body_and_html_are_reported(fast_api, monkeypatch):
    monkeypatch.setattr(api_client.requests, "get", lambda *a, **k: _Resp(200, None, b""))
    with pytest.raises(APIError, match="empty"):
        api_client.fetch_flights(limit=1, save_raw=False)
    monkeypatch.setattr(api_client.requests, "get", lambda *a, **k: _Resp(200, None, b"<html>"))
    with pytest.raises(APIError, match="not valid JSON"):
        api_client.fetch_flights(limit=1, save_raw=False)


def test_null_or_wrong_data_field(fast_api, monkeypatch):
    monkeypatch.setattr(api_client.requests, "get", lambda *a, **k: _Resp(200, {"data": None}))
    assert api_client.fetch_flights(limit=1, save_raw=False)["data"] == []
    monkeypatch.setattr(api_client.requests, "get", lambda *a, **k: _Resp(200, {"data": "oops"}))
    with pytest.raises(APIError):
        api_client.fetch_flights(limit=1, save_raw=False)


def test_api_key_never_appears_in_error_messages(fast_api, monkeypatch):
    def leaky(*a, **k):
        raise api_client.requests.exceptions.InvalidURL(
            "bad url http://x/flights?access_key=SECRETKEY123456&limit=1")
    monkeypatch.setattr(api_client.requests, "get", leaky)
    with pytest.raises(APIError) as err:
        api_client.fetch_flights(limit=1, save_raw=False)
    assert "SECRETKEY123456" not in str(err.value)


def test_pagination_uses_offsets_and_stops_on_short_page(fast_api, monkeypatch):
    seen = []

    def pages(url, params=None, timeout=None):
        seen.append(params["offset"])
        n = 100 if params["offset"] == 0 else 40
        return _Resp(200, {"pagination": {"total": 140}, "data": [{}] * n})
    monkeypatch.setattr(api_client.requests, "get", pages)
    out = api_client.fetch_flights_paged(total=300, page_size=100, max_pages=5,
                                         save_raw=False)   # never write into data/raw/
    assert seen == [0, 100] and len(out["data"]) == 140 and out["pages_requested"] == 2
