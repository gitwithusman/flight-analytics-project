"""Performance regression tests: lazy pages, reload guards, deferred rendering, caches, vectorised analytics."""

import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src import airline_analytics, api_client, config, etl_monitor, reference  # noqa: E402
from src.cache import TTLCache  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.gui.perf import RenderQueue, render_queue  # noqa: E402
from src.gui.tables import PandasTableModel  # noqa: E402
from src.gui.theme import build_stylesheet  # noqa: E402
from src.providers import http, weather  # noqa: E402


@pytest.fixture(scope="session")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(build_stylesheet())
    return a


@pytest.fixture()
def win(app, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(config, "REDUCE_MOTION", True)
    render_queue.clear()
    w = MainWindow()
    w.resize(1360, 840)
    w.show()
    yield w
    w.close()
    render_queue.clear()


def pump(ms=60):
    end = time.time() + ms / 1000
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.003)


def settle(limit=8.0):
    end = time.time() + limit
    while render_queue.busy and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.003)


# ------------------------------------------------------------------ lazy pages and reload guards
def test_only_the_home_page_is_built_at_start_and_others_on_demand(win):
    built = [k for k, _ in win.pages.built()]
    assert built == ["overview"] and len(win.pages) == 14 and "map" in win.pages
    win.navigate("airlines")
    assert "airlines" in [k for k, _ in win.pages.built()]
    assert set(win.pages.keys()) == {"overview", "search", "delays", "airport_analytics", "airlines", "map", "weather",
                                      "flight_analytics", "explorer", "etl", "reports", "data", "settings", "about"}


def test_pages_are_prebuilt_while_idle(win):
    win._prebuild_pages()
    for _ in range(40):
        pump(40)
        if len(win.pages.built()) == 14:
            break
    assert len(win.pages.built()) == 14


@pytest.mark.parametrize("key", ["delays", "airport_analytics", "airlines", "map", "flight_analytics", "reports"])
def test_revisiting_an_unchanged_page_does_not_rebuild_it(win, key, monkeypatch):
    win.navigate(key)
    settle()
    page = win.pages[key]
    calls = []
    original = page.reload
    monkeypatch.setattr(page, "reload", lambda *a, **k: (calls.append(1), original(*a, **k))[1])
    win.navigate("about")
    win.navigate(key)
    pump(30)
    assert calls == []                                    # guarded: nothing is recomputed on a revisit
    win.store.invalidate()                                # data changed (e.g. a refresh finished)
    win.navigate("about")
    win.navigate(key)
    assert calls == [1]                                   # ... and rebuilt exactly once after a change
    settle()


def test_revisit_is_fast(win):
    for key in ("delays", "airlines", "map", "airport_analytics"):
        win.navigate(key)
        settle()
    start = time.perf_counter()
    for key in ("delays", "airlines", "map", "airport_analytics") * 3:
        win.navigate("about")
        win.navigate(key)
        QApplication.processEvents()
    per_switch = (time.perf_counter() - start) / 24
    assert per_switch < 0.25, f"switching took {per_switch * 1000:.0f} ms on average"   # was 150-300 ms each


def test_volatile_pages_always_reload_and_etl_follows_run_history(win, monkeypatch):
    for key in ("search", "settings", "weather", "data"):
        assert win.pages[key].volatile
    etl = win.pages["etl"]
    win.navigate("etl")
    settle()
    seen = []
    original = etl.reload
    monkeypatch.setattr(etl, "reload", lambda *a, **k: (seen.append(1), original(*a, **k))[1])
    win.navigate("about")
    win.navigate("etl")
    assert seen == []
    win.store.bump_runs()                                  # a flight search was logged
    win.navigate("about")
    win.navigate("etl")
    assert seen == [1]


# ------------------------------------------------------------------ render queue and deferred charts
def test_render_queue_keeps_latest_job_per_key_and_survives_errors(app):
    q = RenderQueue()
    ran = []
    q.submit("a", lambda: ran.append("a1"))
    q.submit("b", lambda: (_ for _ in ()).throw(ValueError("boom")))
    q.submit("a", lambda: ran.append("a2"))                # replaces the first 'a'
    q.submit("c", lambda: ran.append("c"))
    assert q.busy
    end = time.time() + 3
    while q.busy and time.time() < end:
        QApplication.processEvents()
    assert ran == ["a2", "c"] and not q.busy


def test_render_queue_flush_and_cancel(app):
    q = RenderQueue()
    ran = []
    q.submit(1, lambda: ran.append(1))
    q.submit(2, lambda: ran.append(2))
    q.cancel(1)
    q.flush()
    assert ran == [2] and not q.busy


def test_charts_are_drawn_after_the_click_not_inside_it(win):
    win.navigate("flight_analytics")
    page = win.pages["flight_analytics"]
    assert all(c._canvas is None for c in page.charts)    # navigate() returned before any figure was built
    assert render_queue.busy
    settle()
    assert all(c._canvas is not None for c in page.charts) and all(c._placeholder is None for c in page.charts)


def test_charts_on_hidden_pages_wait_until_the_page_is_shown(win):
    win.navigate("flight_analytics")
    page = win.pages["flight_analytics"]
    win.navigate("about")                                  # leave before the queue ran
    settle()
    assert all(c._canvas is None for c in page.charts)     # not drawn for a page nobody is looking at
    win.navigate("flight_analytics")
    settle()
    assert all(c._canvas is not None for c in page.charts)


def test_ui_stays_responsive_while_a_chart_page_fills_in(win):
    win.navigate("delays")
    ticks, last, worst = 0, time.perf_counter(), 0.0
    from PySide6.QtCore import QTimer
    timer = QTimer()
    timer.setInterval(10)

    def tick():
        nonlocal ticks, last, worst
        now = time.perf_counter()
        worst = max(worst, now - last)
        last = now
        ticks += 1
    timer.timeout.connect(tick)
    timer.start()
    settle()
    timer.stop()
    assert ticks > 3 and worst < 0.6, f"event loop was blocked for {worst * 1000:.0f} ms"   # one chart at a time


# ------------------------------------------------------------------ caches
def test_ttl_cache_expiry_size_and_get_or_set():
    c = TTLCache(default_ttl=0.05, max_items=3)
    c.set("a", 1)
    assert c.get("a") == 1 and c.has("a")
    time.sleep(0.07)
    assert c.get("a") is None and not c.has("a")
    calls = []
    assert c.get_or_set("k", lambda: calls.append(1) or "v", ttl=5) == "v"
    assert c.get_or_set("k", lambda: calls.append(1) or "w", ttl=5) == "v" and calls == [1]
    for i in range(10):
        c.set(i, i, ttl=5)
    assert len(c._data) <= 3


def test_status_bar_weather_is_cached_and_failures_back_off(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_WEATHER_LOOKUP", True)
    hits = []

    class R:
        status_code = 200

        def json(self):
            return {"current": {"temperature_2m": 21.5, "weather_code": 1, "wind_speed_10m": 9.0}}
    monkeypatch.setattr(api_client.requests, "get", lambda *a, **k: (hits.append(k.get("timeout")), R())[1])
    first = api_client.fetch_weather(31.5, 74.3)
    again = api_client.fetch_weather(31.5, 74.3)
    assert first == again and first["temperature_c"] == 21.5 and len(hits) == 1
    assert isinstance(hits[0], tuple) and hits[0][0] <= 5                       # short connect timeout
    api_client.fetch_weather(25.2, 55.3)
    assert len(hits) == 2                                                       # a different place is a new request

    api_client._WEATHER_CACHE.clear()

    def down(*a, **k):
        hits.append("down")
        raise api_client.requests.exceptions.ConnectionError()
    monkeypatch.setattr(api_client.requests, "get", down)
    n = len(hits)
    assert api_client.fetch_weather(10.0, 10.0) is None and api_client.fetch_weather(10.0, 10.0) is None
    assert len(hits) == n + 1                                                   # no hammering a dead network


def test_destination_weather_is_cached_but_errors_are_not(monkeypatch):
    from datetime import date, timedelta
    target = date.today() + timedelta(days=3)
    calls = []

    def fake(url, params=None, **k):
        calls.append(url)
        return {"daily": {"time": [target.isoformat()], "weather_code": [61], "temperature_2m_max": [31.0],
                          "temperature_2m_min": [22.0], "precipitation_sum": [3.2],
                          "precipitation_probability_max": [60], "wind_speed_10m_max": [20.0]}}
    monkeypatch.setattr(weather, "get_json", fake)
    a = weather.get_weather(25.25, 55.36, target, "DXB")
    b = weather.get_weather(25.25, 55.36, target, "DXB")
    assert len(calls) == 1 and a.daily == b.daily and a is not b               # cached copy, not a shared object
    monkeypatch.setattr(weather, "get_json", lambda *a, **k: (_ for _ in ()).throw(weather.APIError("offline")))
    with pytest.raises(weather.APIError):
        weather.get_weather(1.0, 2.0, target, "XXX")
    monkeypatch.setattr(weather, "get_json", fake)
    assert weather.get_weather(1.0, 2.0, target, "XXX").daily                  # the failure was not remembered


def test_airport_reference_is_cached_until_the_database_changes(tmp_db):
    first = reference.airport_reference(tmp_db)
    t = time.perf_counter()
    second = reference.airport_reference(tmp_db)
    cached_ms = (time.perf_counter() - t) * 1000
    assert first.equals(second) and second is not first and cached_ms < 50
    second.loc[0, "iata"] = "ZZZ"                                              # callers may modify their copy
    assert reference.airport_reference(tmp_db).loc[0, "iata"] != "ZZZ"
    import sqlite3
    with sqlite3.connect(tmp_db) as conn:
        conn.execute("UPDATE airport_reference SET name = 'Changed' WHERE iata = (SELECT MIN(iata) FROM airport_reference)")
    assert "Changed" in set(reference.airport_reference(tmp_db)["name"])        # a write invalidates the cache


def test_store_memo_is_computed_once_per_data_version(win):
    calls = []
    first = win.store.memo("x", lambda: calls.append(1) or pd.DataFrame({"a": [1, 2]}))
    second = win.store.memo("x", lambda: calls.append(1) or pd.DataFrame())
    assert calls == [1] and first.equals(second) and first is not second
    first.loc[0, "a"] = 99
    assert win.store.memo("x", lambda: None).loc[0, "a"] == 1
    win.store.invalidate()
    win.store.memo("x", lambda: calls.append(1) or pd.DataFrame({"a": [3]}))
    assert calls == [1, 1]


def test_warm_up_fills_the_store_without_errors(win):
    win.store.warm()
    assert win.store._flights is not None and win.store._info is not None


# ------------------------------------------------------------------ vectorised analytics, table model, log, http
def _old_airline_table(flights):
    """Reference implementation (the per-airline loop used before the optimisation)."""
    f = flights[flights["airline_iata"].notna() & (flights["airline_iata"] != "")].copy()
    f["route"] = f["dep_iata"] + "-" + f["arr_iata"]
    rows = []
    for code, g in f.groupby("airline_iata"):
        d = g["max_delay_min"].dropna()
        rows.append({
            "airline_iata": code, "airline_name": g["airline_name"].dropna().mode().iloc[0] if g["airline_name"].notna().any() else code,
            "flights": len(g), "routes": g["route"].nunique(), "delay_values": len(d),
            "avg_delay_min": round(float(d.mean()), 2) if len(d) else np.nan,
            "delayed_pct": round(100 * float((d > 0).mean()), 1) if len(d) else np.nan,
            "cancelled": int((g["flight_status"] == "cancelled").sum()),
            "cancel_rate_pct": round(100 * float((g["flight_status"] == "cancelled").mean()), 1),
            "first_date": str(g["flight_date"].min())[:10], "last_date": str(g["flight_date"].max())[:10]})
    out = pd.DataFrame(rows)
    out["small_sample"] = (out["flights"] < 10) | (out["delay_values"] < 5)
    return out.sort_values("flights", ascending=False).reset_index(drop=True)


@pytest.mark.parametrize("seed", range(12))
def test_vectorised_airline_table_matches_the_original_loop(seed):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(1, 500))
    df = pd.DataFrame({
        "airline_iata": rng.choice(["AA", "BB", "CC", "DD", "EE", None, ""], n),
        "airline_name": rng.choice(["Alpha", "Beta", "Gamma", "Delta", None], n),
        "dep_iata": rng.choice(["LHE", "DXB", "JFK"], n), "arr_iata": rng.choice(["LHR", "SIN", "DOH"], n),
        "max_delay_min": rng.choice([np.nan, 0, 5, 12, 40.0], n),
        "flight_status": rng.choice(["scheduled", "cancelled", "active"], n),
        "flight_date": rng.choice(["2026-10-01", "2026-10-05", "2026-10-09"], n)})
    old = _old_airline_table(df)
    new = airline_analytics.table(df)
    if old.empty:
        assert new.empty
        return
    assert list(new.columns) == list(old.columns)[:len(new.columns)] or set(new.columns) >= set(old.columns)
    cols = list(old.columns)
    assert new[cols].reset_index(drop=True).astype(str).equals(old[cols].reset_index(drop=True).astype(str))


def test_airline_table_handles_missing_names_and_empty_input():
    df = pd.DataFrame({"airline_iata": ["AA", "AA"], "airline_name": [None, None], "dep_iata": ["A", "B"],
                       "arr_iata": ["C", "D"], "max_delay_min": [np.nan, np.nan], "flight_status": ["active", "active"],
                       "flight_date": ["2026-10-01", "2026-10-02"]})
    t = airline_analytics.table(df)
    assert t.loc[0, "airline_name"] == "AA" and pd.isna(t.loc[0, "avg_delay_min"]) and t.loc[0, "delay_values"] == 0
    assert airline_analytics.table(df.iloc[0:0]).empty


def test_table_model_sorting_keys_are_cached_and_blanks_sort_last(app):
    m = PandasTableModel()
    df = pd.DataFrame({"n": [3.0, 1.0, np.nan, 2.0], "s": ["b", "A", None, "c"],
                       "flight_status": ["active", "landed", "cancelled", "scheduled"]})
    m.set_frame(df)
    keys = [m.data(m.index(r, 0), PandasTableModel.SORT_ROLE) for r in range(4)]
    assert keys == [3.0, 1.0, None, 2.0]
    assert [m.data(m.index(r, 1), PandasTableModel.SORT_ROLE) for r in range(4)] == ["b", "a", None, "c"]
    assert 0 in m._sort_cache and 1 in m._sort_cache                          # computed once per column, then reused
    from PySide6.QtCore import Qt
    assert m.data(m.index(0, 0), Qt.ItemDataRole.TextAlignmentRole) & int(Qt.AlignmentFlag.AlignRight)
    assert not m.data(m.index(0, 1), Qt.ItemDataRole.TextAlignmentRole) & int(Qt.AlignmentFlag.AlignRight)
    assert m.data(m.index(0, 2), Qt.ItemDataRole.ForegroundRole) is not None  # status colours still work
    m.set_frame(df.iloc[:2])
    assert m._sort_cache == {} and m.rowCount() == 2                         # a new frame resets the caches


def test_large_table_model_builds_quickly(app):
    n = 5000
    df = pd.DataFrame({"a": np.arange(n), "b": ["x"] * n, "c": np.random.default_rng(0).random(n)})
    m = PandasTableModel()
    t = time.perf_counter()
    m.set_frame(df)
    [m.data(m.index(r, 0), PandasTableModel.SORT_ROLE) for r in range(0, n, 7)]
    assert time.perf_counter() - t < 2.0


def test_log_tail_reads_only_the_end_of_a_large_log(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    lines = [f"2026-10-23 line {i} {'x' * 60}" for i in range(60000)]          # ~5 MB
    (tmp_path / "application.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    t = time.perf_counter()
    tail = etl_monitor.log_tail(150)
    assert time.perf_counter() - t < 0.5
    assert len(tail) == 150 and tail[-1].startswith("2026-10-23 line 59999") and tail[0].startswith("2026-10-23 line 59850")
    (tmp_path / "application.log").write_text("only\ntwo\n", encoding="utf-8")
    assert etl_monitor.log_tail(150) == ["only", "two"]


def test_http_calls_use_a_short_connect_timeout_and_still_retry(monkeypatch):
    seen = []

    class Resp:
        status_code = 200
        content = b"{}"

        def json(self):
            return {"ok": 1}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append(timeout)
        if len(seen) == 1:
            raise http.requests.exceptions.Timeout()
        return Resp()
    monkeypatch.setattr(http.requests, "get", fake_get)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    assert http.get_json("https://example.invalid/x", timeout=20, retries=2) == {"ok": 1}
    assert seen == [(5, 20), (5, 20)]


# ------------------------------------------------------------------ animation cost and API key
def test_idle_cpu_with_animation_is_low(win, monkeypatch):
    monkeypatch.setattr(config, "REDUCE_MOTION", False)
    win.canvas.set_animated(True)
    win.pages["airlines"]
    win.navigate("airlines")
    settle()
    pump(300)
    c0, w0 = time.process_time(), time.time()
    pump(1500)
    used = (time.process_time() - c0) / (time.time() - w0)
    assert used < 0.5, f"idle animation used {used * 100:.0f}% of a core"      # was 26-55% before the partial repaint


def test_sky_invalidates_only_small_regions(app):
    from src.gui.aviation import SkyBackground
    sky = SkyBackground("day", planes=3, clouds=8, airport=False)
    sky.resize(1100, 700)
    region = sky._moving_region(12.0)
    covered = sum(r.width() * r.height() for r in region)
    assert 0 < covered < 0.45 * 1100 * 700                                    # a fraction of the page, not all of it


def test_aviationstack_key_is_built_in_and_no_longer_asked_for(win):
    root = Path(config.PROJECT_ROOT)
    assert "AVIATIONSTACK_API_KEY=" in (root / ".env").read_text(encoding="utf-8")
    s = win.pages["settings"]
    for name in ("key_input", "show_key", "save_avs_key"):
        assert not hasattr(s, name)                                            # manual entry fields are gone
    assert hasattr(s, "search_key_input") and hasattr(s, "test_status")        # FlightAPI key + connection tests remain
