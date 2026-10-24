"""Headless GUI tests (Qt 'offscreen' platform).

They exercise the real widgets: page loading, empty states, threading,
sorting, the refresh workflow, validation and shutdown behaviour.
"""

import os
import threading

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QThread, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src import api_client, config, database, service  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.gui.tables import PandasTableModel, SortProxy  # noqa: E402
from src.gui.theme import build_stylesheet  # noqa: E402


@pytest.fixture(scope="session")
def app():
    application = QApplication.instance() or QApplication([])
    application.setStyleSheet(build_stylesheet())
    return application


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated database / .env so tests never touch real user data."""
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    for name in ("DATA_RAW_DIR", "DATA_PROCESSED_DIR", "VISUALIZATIONS_DIR",
                 "REPORTS_DIR", "EDA_DIR", "EDA_FIGURES_DIR"):
        folder = tmp_path / name.lower()
        folder.mkdir()
        monkeypatch.setattr(config, name, folder)  # never write into project data
    monkeypatch.setattr(config, "AVIATIONSTACK_API_KEY", "test-key-123456")
    monkeypatch.setattr(config, "ENABLE_WEATHER_LOOKUP", False)
    return tmp_path


@pytest.fixture()
def filled_db(env, sample_raw_records, monkeypatch):
    """Populate the temp database through the real service pipeline."""
    monkeypatch.setattr(api_client, "fetch_flights",
                        lambda **kw: {"data": sample_raw_records})
    result = service.refresh_data()
    assert result.success and result.stored > 0
    return database.fetch_flights()


@pytest.fixture()
def window(app, env):
    win = MainWindow()
    win.show()
    yield win
    win.close()


def wait_until(cond, timeout_ms=4000):
    waited = 0
    while not cond() and waited < timeout_ms:
        QTest.qWait(20)
        waited += 20
    assert cond(), "condition not met in time"


def test_every_page_loads_on_empty_database(window):
    for key in window.pages:
        window.navigate(key)
        assert window.stack.currentWidget() is window.pages[key]
    window.navigate("overview")
    assert window.pages["overview"].empty_state.isVisible()


def test_every_page_loads_with_data(app, env, filled_db):
    win = MainWindow()
    win.show()
    for key in win.pages:
        win.navigate(key)
        QTest.qWait(10)
    win.navigate("overview")
    assert not win.pages["overview"].empty_state.isVisible()
    assert win.pages["overview"].card_flights.value.text() == str(len(filled_db))
    win.close()


def test_task_callbacks_run_on_gui_thread(window):
    seen = {}
    window.tasks.submit(lambda: threading.get_ident(),
                        on_done=lambda tid: seen.update(
                            worker=tid, callback=threading.get_ident(),
                            gui=QThread.currentThread() == QApplication.instance().thread()))
    wait_until(lambda: "callback" in seen)
    assert seen["gui"] and seen["callback"] == threading.main_thread().ident
    assert seen["worker"] != seen["callback"]


def test_stale_callback_is_skipped_when_owner_is_deleted(window):
    from PySide6.QtWidgets import QLabel
    label = QLabel()
    called = []
    window.tasks.submit(lambda: QTest.qWait(1) or 1, owner=label,
                        on_done=lambda _r: called.append(1))
    import shiboken6
    shiboken6.delete(label)  # destroy the C++ widget immediately (deterministic)
    assert not shiboken6.isValid(label)
    wait_until(lambda: not window.tasks.busy())
    assert called == []


def test_numeric_columns_sort_numerically(app):
    model = PandasTableModel()
    model.set_frame(pd.DataFrame({"max_delay_min": [100.0, 15.0, 9.0, None, 250.0]}))
    proxy = SortProxy()
    proxy.setSourceModel(model)
    proxy.sort(0, Qt.SortOrder.AscendingOrder)
    asc = [proxy.index(r, 0).data() for r in range(proxy.rowCount())]
    assert asc == ["9", "15", "100", "250", "\u2013"]  # blank stays last
    proxy.sort(0, Qt.SortOrder.DescendingOrder)
    desc = [proxy.index(r, 0).data() for r in range(proxy.rowCount())]
    assert desc == ["250", "100", "15", "9", "\u2013"]


def test_explorer_filters(app, env, filled_db):
    win = MainWindow()
    win.show()
    win.navigate("explorer")
    page = win.pages["explorer"]
    assert page.table.model().rowCount() == len(filled_db)
    page.set_global_search("midwest")
    assert page.table.model().rowCount() == 1
    page._clear()
    page.delayed.setChecked(True)
    assert 0 < page.table.model().rowCount() < len(filled_db)
    page._clear()
    idx = page.status.findData("cancelled")
    page.status.setCurrentIndex(idx)
    assert page.table.model().rowCount() == 1
    win.close()


def _fake_result(**kw):
    base = dict(success=True, message="Stored 3 flight records.", fetched=3,
                valid=3, stored=3, airports_stored=2)
    base.update(kw)
    return service.RefreshResult(**base)


def test_refresh_success_updates_ui(window, monkeypatch):
    monkeypatch.setattr(service, "refresh_data", lambda **kw: _fake_result())
    window.start_refresh()
    assert not window.refresh_btn.isEnabled() and window.busy_bar.isVisible()
    wait_until(lambda: not window._refreshing)
    assert window.refresh_btn.isEnabled() and not window.busy_bar.isVisible()
    assert window.banner.property("kind") == "success"
    assert "Stored 3" in window.pages["data"].retrieve_status.text()


def test_refresh_failure_shows_persistent_error(window, monkeypatch):
    def boom(**kw):
        raise RuntimeError("API returned HTTP 403.")
    monkeypatch.setattr(service, "refresh_data", boom)
    window.start_refresh()
    wait_until(lambda: not window._refreshing)
    assert window.banner.property("kind") == "error"
    assert window.banner.isVisible()            # really on screen, not just styled
    assert "403" in window.banner._text.text()
    window.banner._close.click()
    assert not window.banner.isVisible()
    assert window.refresh_btn.isEnabled()


def test_second_refresh_while_busy_is_ignored(window, monkeypatch):
    calls = []

    def slow(**kw):
        calls.append(1)
        QThread.msleep(150)
        return _fake_result()
    monkeypatch.setattr(service, "refresh_data", slow)
    window.start_refresh()
    window.start_refresh()
    window.start_refresh()
    wait_until(lambda: not window._refreshing)
    assert calls == [1]


def test_refresh_without_key_opens_settings(window, monkeypatch):
    monkeypatch.setattr(config, "AVIATIONSTACK_API_KEY", "")
    window.start_refresh()
    assert window._current_key() == "settings"
    assert window.banner.property("kind") == "warning" and window.banner.isVisible()


def test_settings_validation_and_saving(window, env):
    window.navigate("settings")
    page = window.pages["settings"]
    page.weather_lat.setText("123")
    page.weather_lon.setText("10")
    page._save()
    assert window.banner.property("kind") == "warning"
    assert not config.ENV_FILE.exists()          # nothing written on invalid input
    page.weather_lat.setText("31.5204")
    page.weather_lon.setText("74.3587")
    page.weather_label.setText("Gate #5")
    page._save()
    assert window.banner.property("kind") == "success"
    assert config.WEATHER_LATITUDE == "31.5204" and config.WEATHER_LABEL == "Gate #5"
    # coordinates can be cleared again (the old spin boxes could not)
    page.weather_lat.setText("")
    page.weather_lon.setText("")
    page._save()
    assert config.WEATHER_LATITUDE == "" and config.WEATHER_LONGITUDE == ""


def test_data_page_rejects_bad_iata(window, monkeypatch):
    started = []
    monkeypatch.setattr(window, "start_refresh", lambda **kw: started.append(kw))
    page = window.pages["data"]
    page.f_dep.setText("12")
    page._retrieve()
    assert started == [] and window.banner.property("kind") == "warning"
    page.f_dep.setText("lhr")
    page._retrieve()
    assert started and started[0]["dep_iata"] == "LHR"


def test_layout_is_responsive(window):
    window.resize(1360, 840)
    QTest.qWait(30)
    assert not window._compact
    wide_cols = window.pages["overview"].findChildren(type(window.pages["overview"].row))[0].columns()
    window.resize(880, 600)
    QTest.qWait(30)
    assert window._compact and window.sidebar.width() == 64
    assert all(b.text() == "" for b in window.nav_buttons.values())
    window.resize(1360, 840)
    QTest.qWait(30)
    assert not window._compact
    assert window.nav_buttons["overview"].text() == "Home Dashboard"
    assert wide_cols >= 1


def test_close_waits_for_running_task(app, env, monkeypatch):
    done = []

    def slow(**kw):
        QThread.msleep(200)
        done.append(1)
        return _fake_result()
    monkeypatch.setattr(service, "refresh_data", slow)
    win = MainWindow()
    win.show()
    win.start_refresh()
    win.close()
    assert done == [1]  # close() did not tear the window down mid-task


def test_weather_page_rows_survive_rapid_navigation(app, env, filled_db, monkeypatch):
    """Rows are rebuilt on every visit; late answers for deleted rows must not crash."""
    def fake_weather(latitude, longitude):
        QThread.msleep(60)
        return {"temperature_c": 21.4, "wind_speed_kmh": 12.0, "weather_code": 0}
    monkeypatch.setattr(api_client, "fetch_weather", fake_weather)
    win = MainWindow()
    win.show()
    for _ in range(4):                      # revisit before earlier lookups finish
        win.navigate("weather")
        win.navigate("overview")
    win.navigate("weather")
    page = win.pages["weather"]
    assert page.wx_container.count() >= 1
    wait_until(lambda: not win.tasks.busy())
    texts = [w.findChildren(type(page.loc_detail))[-1].text()
             for w in (page.wx_container.itemAt(i).widget() for i in range(page.wx_container.count()))]
    assert all("21" in t for t in texts), texts
    win.close()
