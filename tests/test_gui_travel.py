"""Headless GUI tests for the travel / operations screens (Qt 'offscreen'; no network, no API keys)."""

import os
import time
from datetime import date, timedelta

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QDate, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from src import api_client, config, database, database_travel, flight_search, service  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.gui.theme import build_stylesheet  # noqa: E402
from src.providers import weather as wxm  # noqa: E402
from src.utils import AuthenticationError  # noqa: E402

TODAY = date.today()


@pytest.fixture(scope="session")
def app():
    application = QApplication.instance() or QApplication([])
    application.setStyleSheet(build_stylesheet())
    return application


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    for name in ("DATA_RAW_DIR", "DATA_PROCESSED_DIR", "VISUALIZATIONS_DIR", "REPORTS_DIR", "EDA_DIR", "EDA_FIGURES_DIR", "EXPORTS_DIR"):
        folder = tmp_path / name.lower()
        folder.mkdir()
        monkeypatch.setattr(config, name, folder)
    monkeypatch.setattr(config, "AVIATIONSTACK_API_KEY", "")
    monkeypatch.setattr(config, "FLIGHTAPI_API_KEY", "")
    monkeypatch.setattr(config, "SEARCH_FORCE_DEMO", False)
    monkeypatch.setattr(config, "ENABLE_WEATHER_LOOKUP", False)
    return tmp_path


@pytest.fixture()
def filled(env, sample_raw_records, monkeypatch):
    monkeypatch.setattr(config, "AVIATIONSTACK_API_KEY", "test-key-123456")
    monkeypatch.setattr(api_client, "fetch_flights", lambda **kw: {"data": sample_raw_records})
    assert service.refresh_data().success
    monkeypatch.setattr(config, "AVIATIONSTACK_API_KEY", "")


@pytest.fixture()
def win(app, env):
    w = MainWindow()
    w.resize(1360, 840)
    w.show()
    yield w
    w.close()


def pump(ms=100):
    end = time.time() + ms / 1000
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def wait(cond, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        pump(50)
        if cond():
            return True
    return False


def texts(widget):
    return " ".join(l.text() for l in widget.findChildren(QLabel))


# --------------------------------------------------------------------------- navigation
def test_required_screens_exist_in_navigation(win):
    labels = set(win._nav_labels.values())
    for needed in ("Home Dashboard", "Flight Search", "Flight Status and Delays", "Airport Analytics",
                   "Airline Performance", "Flight Route Map", "Destination Weather", "ETL Monitoring", "Reports and Export", "Settings and API"):
        assert needed in labels, needed
    assert all(b.isEnabled() for b in win.nav_buttons.values())
    assert not [l for l in labels if "fare" in l.lower()] and not {"compare", "fares"} & set(win.pages)


def test_every_page_loads_on_empty_database(win):
    for key in win.pages:
        win.navigate(key)
        assert win.stack.currentWidget() is win.pages[key]
        pump(30)
    win.navigate("map")
    assert win.pages["map"].empty_state.isVisible()
    win.navigate("airport_analytics")
    assert win.pages["airport_analytics"].empty_state.isVisible()


# --------------------------------------------------------------------------- flight search
def _search(win, o="LHE", d="DXB", days=14):
    win.navigate("search")
    s = win.pages["search"]
    s.origin.set_iata(o)
    s.dest.set_iata(d)
    s.dep_date.setDate(QDate.currentDate().addDays(days))
    s.search_btn.click()
    return s


def test_sample_mode_banner_and_results_are_labelled(win):
    s = _search(win)
    assert wait(lambda: not s._options.empty)
    assert "SAMPLE DATA MODE" in texts(win.pages["search"])
    assert s.origin_badge.text() == "SAMPLE DATA" and len(s._shown) > 0
    s.table.selectRow(0)
    pump(100)
    assert "SAMPLE DATA - not a real flight" in s.detail_text.text() and not s.book_btn.isEnabled()
    assert "Fare" not in s.detail_text.text() and "price" not in s.detail_text.text().lower()
    assert "Baggage:" in s.detail_text.text() and "Duration:" in s.detail_text.text()


@pytest.mark.parametrize("o,d,days,msg", [("", "DXB", 5, "Origin airport is required"), ("LHE", "LHE", 5, "different"),
                                           ("LHE", "ZZZ", 5, "not in the airport reference"), ("LH", "DXB", 5, "is not recognised"), ("Lahore", "DXB", 5, "is not recognised")])
def test_search_validation_messages(win, o, d, days, msg):
    s = _search(win, o, d, days)
    pump(100)
    assert s.form_msg.isVisible() and msg in s.form_msg.text() and s._options.empty


def test_search_filters_and_sorting(win):
    s = _search(win)
    assert wait(lambda: not s._options.empty)
    assert not [i for i in range(s.f_sort.count()) if "price" in s.f_sort.itemText(i).lower()]
    n = len(s._shown)
    s.f_stops.setCurrentIndex(1)
    pump(80)
    assert len(s._shown) <= n and (s._shown["stops"] == 0).all()
    s.f_stops.setCurrentIndex(0)
    s.f_sort.setCurrentIndex(1)
    pump(80)
    assert s._shown["duration_min"].is_monotonic_increasing
    s.f_sort.setCurrentIndex(0)
    pump(80)
    assert s._shown["departure_at"].is_monotonic_increasing
    cols = list(s.table.table_model.frame().columns)
    assert "Fare" not in cols and not [c for c in cols if "price" in c.lower() or "fare" in c.lower()]
    assert not hasattr(s, "f_price") and not hasattr(s, "target") and not hasattr(s, "compare_btn")


def test_provider_failure_is_shown_not_raised(win, monkeypatch):
    class Down:
        name, data_origin = "down", "live_api"

        def search(self, q):
            raise AuthenticationError("FlightAPI rejected the credentials (HTTP 401).")
    monkeypatch.setattr(flight_search, "pick_provider", lambda db=None: Down())
    s = _search(win)
    assert wait(lambda: s.search_btn.isEnabled() and s.form_msg.isVisible())
    assert "rejected the credentials" in s.form_msg.text() and s._options.empty
    assert database.last_refresh()["status"] == "failed"


def test_empty_result_message(win, monkeypatch):
    from src.providers.base import FlightFetchResult
    from datetime import datetime, timezone

    class Empty:
        name, data_origin = "e", "live_api"

        def search(self, q):
            return FlightFetchResult([], "flightapi", "live_api", datetime.now(timezone.utc), ["No flights."])
    monkeypatch.setattr(flight_search, "pick_provider", lambda db=None: Empty())
    s = _search(win)
    assert wait(lambda: s.search_btn.isEnabled() and s._query is not None and not s._searching)
    pump(200)
    assert "No flights found" in s.table._empty.text()


def test_save_run_and_delete_saved_search(win):
    s = _search(win)
    assert wait(lambda: not s._options.empty)
    s.saved_name.setText("Dubai trip")
    s._save_search()
    saved = database_travel.list_saved_searches()
    assert len(saved) == 1 and saved.iloc[0]["name"] == "Dubai trip" and s.saved_table.table_model.rowCount() == 1
    s.origin.setText("")
    s.dest.setText("")
    s.saved_table.selectRow(0)
    pump(100)
    s._run_saved()
    assert s.origin.iata() == "LHE" and s.dest.iata() == "DXB"
    assert wait(lambda: not s._searching and not s._options.empty)
    s.saved_table.selectRow(0)
    s._delete_saved()
    assert database_travel.list_saved_searches().empty


def test_saved_search_with_past_date_suggests_a_new_one(win):
    database_travel.save_search("old", "LHE", "DXB", "2020-01-01", None, 1, "economy")
    win.navigate("search")
    s = win.pages["search"]
    s.saved_table.selectRow(0)
    pump(100)
    s._run_saved()
    assert s.dep_date.date() >= QDate.currentDate()
    assert wait(lambda: not s._searching)


def test_search_export_matches_displayed_rows(win, tmp_path):
    s = _search(win)
    assert wait(lambda: not s._options.empty)
    out = s.export.export("csv", str(tmp_path / "flights.csv"))
    got = pd.read_csv(out)
    assert len(got) == len(s._shown) and not [c for c in got.columns if "price" in c or "fare" in c]
    assert s.export.export("excel", str(tmp_path / "f.xlsx"))


def test_export_with_no_rows_warns(win, tmp_path):
    win.navigate("search")
    assert win.pages["search"].export.export("csv", str(tmp_path / "x.csv")) is None and not (tmp_path / "x.csv").exists()


def test_no_fare_text_anywhere_in_the_interface(filled, win):
    import re
    for key in win.pages:
        win.navigate(key)
        pump(40)
        found = re.findall(r"\bfares?\b|\bprice\b|cheapest", texts(win.pages[key]), flags=re.I)
        assert not found, (key, found)


# --------------------------------------------------------------------------- operations pages
def test_airport_dashboard_detail_and_search(filled, win):
    win.navigate("airport_analytics")
    a = win.pages["airport_analytics"]
    assert not a.empty_state.isVisible() and "not worldwide" in a.scope.text()
    a.table.selectRow(0)
    pump(150)
    assert a._sel and "departures" in a.detail_text.text() and a.map_btn.isEnabled()
    a.search.setText("zzzzzz")
    pump(100)
    assert len(a._view) == 0
    a.search.setText("")
    a._sel = "JFK"
    a._show_map()
    assert win._current_key() == "map" and win.pages["map"].f_origin.currentData() == "JFK"


def test_airline_page_flags_small_samples_and_compares(filled, win):
    win.navigate("airlines")
    p = win.pages["airlines"]
    assert "Reporting period" in p.period.text() and p._tbl["small_sample"].all()
    p.rank.setCurrentIndex(1)
    pump(100)
    assert "only airlines with enough data are ranked (0 of" in p.rank_note.text()
    for i in range(2):
        p.pick.item(i).setCheckState(Qt.CheckState.Checked)
    pump(150)
    assert not p.cmp_table.table_model.frame().empty


def test_status_page_filters_and_live_lookup_without_key(filled, win):
    win.navigate("delays")
    st = win.pages["delays"]
    assert st._shown.shape[0] == 3 and "historical snapshots" in st.scope.text()
    st.f_status.setCurrentIndex(st.f_status.findData("cancelled"))
    pump(100)
    assert len(st._shown) == 1 and st.k_cx.findChildren(QLabel)[1].text() == "1" or len(st._shown) == 1
    st.flight_no.setText("PK301")
    st._lookup()
    pump(500)
    assert "API key" in st.live_msg.text() and not st.live_badge.isVisible()


def test_status_live_lookup_with_mocked_api_is_labelled_live(win, filled, monkeypatch, sample_raw_records):
    monkeypatch.setattr(config, "AVIATIONSTACK_API_KEY", "k" * 12)
    monkeypatch.setattr(api_client, "fetch_flights", lambda **kw: {"data": sample_raw_records[:1]})
    win.navigate("delays")
    st = win.pages["delays"]
    st.flight_no.setText("EA100")
    st._lookup()
    assert wait(lambda: st.lookup_btn.isEnabled() and st.live_badge.isVisible())
    assert st.live_badge.text() == "LIVE" and st.live_table.table_model.rowCount() == 1
    assert len(database_travel.fetch_status_observations()) == 1


def test_route_map_interaction(filled, win):
    win.navigate("map")
    m = win.pages["map"]
    pump(300)
    assert not m.empty_state.isVisible() and len(m._view) == 3 and len(m._points) >= 3
    assert "great-circle arcs" in m.map_note.text() and "public domain" in m.map_note.text()
    pt = m._points.iloc[0]
    px, py = m.ax.transData.transform([[pt.lon, pt.lat]])[0]
    assert m.airport_at(px, py) == pt.iata and m.airport_at(px + 80, py + 80) is None
    assert pt.iata in m.tooltip_for(pt.iata)
    m.pick_airport(pt.iata)
    assert m.f_origin.currentData() == pt.iata
    m.table.selectRow(0)
    pump(100)
    assert "Great-circle distance" in m.detail.text() and m._sel == 0
    m.f_min.setValue(5)
    pump(100)
    assert len(m._view) == 0 and "No routes match" in m.table._empty.text()


def test_route_map_uses_only_reference_coordinates(filled, win):
    from src import reference
    win.navigate("map")
    m = win.pages["map"]
    ref = reference.airport_reference().set_index("iata")
    for r in m._view.itertuples():
        assert (r.o_lat, r.o_lon) == (ref.loc[r.origin, "latitude"], ref.loc[r.origin, "longitude"])


def test_etl_monitor_shows_runs_quality_and_scrubs_log(filled, win):
    win.navigate("etl")
    e = win.pages["etl"]
    assert not e._hist.empty and "flights" in set(e._hist["pipeline"]) and "Passed" in texts(e)
    assert "Flights stored: 3" in e.quality_text.text()
    e.refresh_all()
    assert wait(lambda: not win._refreshing)
    pump(200)
    assert "skipped (no AviationStack key)" in e.op_msg.text()


def test_refresh_all_steps_are_independent(filled, win, monkeypatch):
    from src import utils
    monkeypatch.setattr(config, "AVIATIONSTACK_API_KEY", "k" * 12)
    monkeypatch.setattr(service, "refresh_data", lambda **kw: (_ for _ in ()).throw(utils.APIError("network down")))
    win.navigate("etl")
    e = win.pages["etl"]
    e.refresh_all()
    assert wait(lambda: not win._refreshing)
    pump(200)
    assert "flights: FAILED (network down)" in e.op_msg.text() and "fares" not in e.op_msg.text()


def test_busy_state_prevents_overlapping_operations(filled, win):
    win.navigate("etl")
    e = win.pages["etl"]
    win._refreshing = True
    notes = []
    win.notify = lambda m, k="info": notes.append(m)
    e.refresh_all()
    win.pages["search"].origin.set_iata("LHE")
    win.pages["search"].dest.set_iata("DXB")
    win.pages["search"].search()
    win._refreshing = False
    assert len(notes) == 2 and all("running" in n or "wait" in n for n in notes)


def test_reports_preview_equals_export(filled, win, tmp_path):
    win.navigate("reports")
    r = win.pages["reports"]
    for i, name in enumerate(r.DATASETS):
        r.dataset.setCurrentIndex(i)
        pump(60)
        assert len(r._df) == len(r._meta and r._df)
    r.dataset.setCurrentIndex(0)
    pump(100)
    out = r.export.export("csv", str(tmp_path / "flights.csv"))
    assert len(pd.read_csv(out)) == len(r._df) == 3
    r.d_from.setCurrentIndex(1)
    r.d_to.setCurrentIndex(1)
    pump(100)
    assert r._meta["filters"] and all(r._df["flight_date"].astype(str) == r.d_from.currentData())


def test_destination_weather_forecast_unavailable_and_errors(win, monkeypatch):
    win.navigate("weather")
    wp = win.pages["weather"]
    target = TODAY + timedelta(days=3)
    monkeypatch.setattr(wxm, "get_json", lambda url, params=None, **k: {"daily": {
        "time": [target.isoformat()], "weather_code": [61], "temperature_2m_max": [31.0], "temperature_2m_min": [22.0],
        "precipitation_sum": [3.2], "precipitation_probability_max": [60], "wind_speed_10m_max": [20.0]}})
    wp.dest.set_iata("DXB")
    wp.when.setDate(QDate(target.year, target.month, target.day))
    wp.go.click()
    assert wait(lambda: wp.kind_badge.isVisible() and wp.go.isEnabled())
    assert wp.kind_badge.text() == "FORECAST" and "Light rain" in wp.k_cond.findChildren(QLabel)[1].text()
    assert "do not guarantee flight operations" in wp.attr.text() and "Open-Meteo" in wp.attr.text()
    far = TODAY + timedelta(days=40)
    wp.when.setDate(QDate(far.year, far.month, far.day))
    wp.go.click()
    assert wait(lambda: wp.kind_badge.text() == "UNAVAILABLE")
    assert "16 days" in wp.msg.text()
    monkeypatch.setattr(wxm, "get_json", lambda *a, **k: (_ for _ in ()).throw(wxm.APIError("offline")))
    wxm._RESULT_CACHE.clear()          # a repeated lookup would otherwise be answered from the 10-minute cache
    wp.when.setDate(QDate(target.year, target.month, target.day))
    wp.go.click()
    assert wait(lambda: "Weather unavailable" in wp.msg.text())
    wp.dest.setText("nowhere")
    wp.go.click()
    assert "valid IATA code" in wp.msg.text()


# --------------------------------------------------------------------------- settings
def test_settings_saves_token_securely_and_validates(win, env):
    win.navigate("settings")
    s = win.pages["settings"]
    s.search_key_input.setText("short")
    s._save()
    assert not (env / ".env").exists() or "FLIGHTAPI_API_KEY" not in (env / ".env").read_text()
    s.search_key_input.setText("https://api.flightapi.io/dashboard/abc")
    s._save_single_key("FLIGHTAPI_API_KEY", s.search_key_input, "FlightAPI API key")
    assert not (env / ".env").exists() or "FLIGHTAPI_API_KEY" not in (env / ".env").read_text()
    s.search_key_input.setText("tpTOKEN1234567890")
    s.search_demo.setChecked(False)
    s._save()
    text = (env / ".env").read_text()
    assert "FLIGHTAPI_API_KEY=tpTOKEN1234567890" in text and "SEARCH_FORCE_DEMO=0" in text
    assert config.flightapi_configured() and config.search_mode() == "live_api"
    win.navigate("settings")
    assert "tpTO" in s.search_key_status.text() and "tpTOKEN1234567890" not in texts(s)     # masked
    win.navigate("search")
    assert "flightapi" in texts(win.pages["search"]).lower()
    assert "SAMPLE DATA MODE" not in texts(win.pages["search"])
