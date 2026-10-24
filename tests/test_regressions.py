"""Regression tests for bugs found while reviewing the project."""

import gc
import os

import pandas as pd
import pytest

from src import analytics, api_client, config, database


# --- .env handling ----------------------------------------------------------
def test_env_file_with_bom_is_read(tmp_path, monkeypatch):
    """Windows editors add a UTF-8 BOM; the first key used to be unreadable."""
    env = tmp_path / ".env"
    env.write_bytes(b"\xef\xbb\xbfAVIATIONSTACK_API_KEY=abcdef123456\r\nWEATHER_LABEL=Home\r\n")
    monkeypatch.setattr(config, "ENV_FILE", env)
    monkeypatch.delenv("AVIATIONSTACK_API_KEY", raising=False)
    config.reload_environment()
    try:
        assert config.api_key_configured()
        assert config.WEATHER_LABEL == "Home"
    finally:
        monkeypatch.delenv("AVIATIONSTACK_API_KEY", raising=False)
        monkeypatch.delenv("WEATHER_LABEL", raising=False)


def test_update_env_file_roundtrip(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_bytes(b"\xef\xbb\xbf# comment\nKEEP=1\nWEATHER_LABEL=old\n")
    monkeypatch.setattr(config, "ENV_FILE", env)
    config.update_env_file({"WEATHER_LABEL": "Gate #5", "WEATHER_LATITUDE": None, "NEW_KEY": "x"})
    raw = env.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")          # rewritten without BOM
    text = raw.decode()
    assert "# comment" in text and "KEEP=1" in text      # untouched lines survive
    assert 'WEATHER_LABEL="Gate #5"' in text             # '#' would start a comment unquoted
    assert "WEATHER_LATITUDE=\n" in text and "NEW_KEY=x" in text
    for monkey_key in ("WEATHER_LABEL", "WEATHER_LATITUDE", "NEW_KEY", "KEEP"):
        os.environ.pop(monkey_key, None)


def test_update_env_file_rejects_line_breaks(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    with pytest.raises(ValueError):
        config.update_env_file({"AVIATIONSTACK_API_KEY": "abc\nINJECTED=1"})


def test_bad_numeric_env_values_do_not_crash(monkeypatch):
    monkeypatch.setenv("REQUEST_TIMEOUT", "20s")
    assert config._env_int("REQUEST_TIMEOUT", 20) == 20


# --- API error bodies -------------------------------------------------------
class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_http_error_surfaces_the_api_message(monkeypatch):
    monkeypatch.setattr(config, "AVIATIONSTACK_API_KEY", "k" * 16)
    body = {"error": {"code": "function_access_restricted",
                      "message": "Your plan does not allow this."}}
    monkeypatch.setattr(api_client.requests, "get", lambda *a, **k: _Resp(403, body))
    with pytest.raises(Exception) as err:
        api_client.fetch_flights(limit=5)
    assert "plan" in str(err.value).lower() or "restricted" in str(err.value).lower()
    assert "HTTP 403" not in str(err.value)


def test_non_dict_error_payload_is_handled(monkeypatch):
    monkeypatch.setattr(config, "AVIATIONSTACK_API_KEY", "k" * 16)
    monkeypatch.setattr(api_client.requests, "get",
                        lambda *a, **k: _Resp(200, {"error": "gateway down"}))
    with pytest.raises(Exception) as err:
        api_client.fetch_flights(limit=5)
    assert "gateway down" in str(err.value)


# --- database ----------------------------------------------------------------
def test_database_connections_are_closed(tmp_path):
    path = tmp_path / "x.db"
    gc.disable()
    try:
        for _ in range(30):
            database.count_rows("flights", path)
        open_handles = [fd for fd in os.listdir("/proc/self/fd")
                        if os.path.islink(f"/proc/self/fd/{fd}")
                        and "x.db" in os.readlink(f"/proc/self/fd/{fd}")]
    except FileNotFoundError:
        pytest.skip("needs /proc")
    finally:
        gc.enable()
    assert open_handles == []


def test_schema_is_rebuilt_if_database_file_is_deleted(tmp_path):
    path = tmp_path / "y.db"
    assert database.count_rows("flights", path) == 0
    path.unlink()
    assert database.count_rows("flights", path) == 0   # no 'no such table'


# --- analytics -----------------------------------------------------------------
def test_condition_counts_match_row_classifier():
    df = pd.DataFrame({
        "flight_status": ["scheduled", "active", "landed", "cancelled", "incident",
                          "diverted", "scheduled", "", "landed"],
        "max_delay_min": [None, 25, None, None, None, 0, 10, None, 5],
        "weather_confirmed": [False] * 8 + [True],
    })
    counts = analytics.condition_counts(df)
    expected = {}
    for _, row in df.iterrows():
        label = analytics.classify_condition(row)["label"]
        base = next((c for c in counts if label.startswith(c)), None)
        if base is None:
            base = "Incident/Diverted" if label in {"Incident", "Diverted"} else "Status Unknown"
        expected[base] = expected.get(base, 0) + 1
    assert {k: v for k, v in counts.items() if v} == expected
    assert sum(counts.values()) == len(df)
