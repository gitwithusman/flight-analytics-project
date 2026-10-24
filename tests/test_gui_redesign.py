"""Redesign tests: responsive layout (desktop / tablet / phone), drawer, animation switch, section styling."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget  # noqa: E402

from src import config  # noqa: E402
from src.gui import aviation  # noqa: E402
from src.gui.perf import render_queue  # noqa: E402
from src.gui.main_window import COMPACT_BELOW, MOBILE_BELOW, MainWindow  # noqa: E402
from src.gui.theme import SECTION_STYLE, build_stylesheet  # noqa: E402
from src.gui.widgets import ActionTile, FlowLayout, HeroBanner  # noqa: E402


@pytest.fixture(scope="session")
def app():
    application = QApplication.instance() or QApplication([])
    application.setStyleSheet(build_stylesheet())
    return application


@pytest.fixture()
def win(app, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(config, "REDUCE_MOTION", True)       # deterministic: no running timers / fades
    render_queue.clear()                                      # jobs left over from earlier windows
    w = MainWindow()
    w.resize(1360, 840)
    w.show()
    yield w
    w.close()
    render_queue.clear()


def pump(ms=80):
    end = time.time() + ms / 1000
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def test_every_page_has_a_distinct_section_style(win):
    assert set(win.pages) <= set(SECTION_STYLE)
    accents = {SECTION_STYLE[k][0] for k in win.pages}
    assert len(accents) >= 10                                  # sections are visually distinguishable
    for key, page in win.pages.items():
        assert isinstance(page.hero, HeroBanner) and page.hero.title.text() == page.title
        assert page.hero._accent == SECTION_STYLE[key][0]


@pytest.mark.parametrize("width,mode", [(1360, "desktop"), (900, "tablet"), (380, "mobile")])
def test_layout_mode_and_no_horizontal_scrolling(win, width, mode):
    win.resize(width, 800)
    pump(120)
    assert win._mode == mode
    for key, page in win.pages.items():
        win.navigate(key)
        pump(60)
        scrolls = page.findChildren(QScrollArea)
        if scrolls:
            assert scrolls[0].horizontalScrollBar().maximum() == 0, f"{key} scrolls sideways at {width}px"


def test_breakpoints_are_consistent(win):
    assert MOBILE_BELOW < COMPACT_BELOW
    win.resize(COMPACT_BELOW + 5, 700)
    pump(80)
    assert win._mode == "desktop" and not win._compact
    win.resize(COMPACT_BELOW - 5, 700)
    pump(80)
    assert win._mode == "tablet" and win._compact and win.sidebar.width() == 64
    win.resize(MOBILE_BELOW - 5, 700)
    pump(80)
    assert win._mode == "mobile" and win.menu_btn.isVisible() and not win.sidebar.isVisible()
    win.resize(1360, 840)
    pump(80)
    assert win._mode == "desktop" and win.sidebar.isVisible() and not win.menu_btn.isVisible()
    assert win.nav_buttons["overview"].text() == "Home Dashboard"


def test_mobile_drawer_opens_navigates_and_closes(win):
    win.resize(390, 800)
    pump(100)
    assert not win.sidebar.isVisible()
    win.menu_btn.click()
    pump(60)
    assert win._drawer_open and win.sidebar.isVisible() and win.scrim.isVisible()
    win.nav_buttons["airlines"].click()
    pump(80)
    assert win._current_key() == "airlines" and not win._drawer_open and not win.sidebar.isVisible()
    win.menu_btn.click()
    pump(60)
    win.scrim.pressed.emit()
    pump(40)
    assert not win._drawer_open and not win.scrim.isVisible()


def test_hero_goes_compact_on_narrow_pages(win):
    win.resize(1360, 840)
    pump(100)
    win.navigate("search")
    pump(60)
    tall = win.pages["search"].hero.height()
    win.resize(380, 800)
    pump(100)
    assert win.pages["search"].hero.height() < tall and not win.pages["search"].hero.subtitle.isVisible()


def test_quick_action_tiles_navigate(win):
    win.navigate("overview")
    pump(60)
    tiles = win.pages["overview"].findChildren(ActionTile)
    assert len(tiles) == 8
    targets = {t.accessibleName() for t in tiles}
    assert "Search flights" in targets and not [t for t in targets if "fare" in t.lower()]
    first = next(t for t in tiles if t.accessibleName() == "Search flights")
    first.clicked.emit()
    assert win._current_key() == "search"


def test_animation_switch_stops_timers(win, monkeypatch):
    sky = win.canvas
    assert not sky._timer.isActive()                           # REDUCE_MOTION is on in this fixture
    monkeypatch.setattr(config, "REDUCE_MOTION", False)
    sky.set_animated(True)
    assert sky._timer.isActive()
    t0 = sky._t
    pump(150)
    assert sky._t > t0                                         # the sky is actually moving
    monkeypatch.setattr(config, "REDUCE_MOTION", True)
    sky.set_animated(True)
    assert not sky._timer.isActive()


@pytest.mark.parametrize("scene", sorted(aviation.SCENES))
def test_every_scene_renders_with_planes_and_airport(app, scene):
    sky = aviation.SkyBackground(scene, planes=3, airport=True)
    sky.resize(640, 160)
    img = sky.grab().toImage()
    assert not img.isNull() and img.width() >= 640
    colours = {img.pixel(x, y) for x in range(0, 640, 40) for y in range(0, 160, 20)}
    assert len(colours) > 12                                   # not a flat fill


def test_background_photo_override_is_used(app, tmp_path, monkeypatch):
    from PySide6.QtGui import QColor, QImage
    (tmp_path / "backgrounds").mkdir()
    img = QImage(64, 36, QImage.Format.Format_RGB32)
    img.fill(QColor("#FF00FF"))
    img.save(str(tmp_path / "backgrounds" / "noon.png"))
    monkeypatch.setattr(config, "ASSETS_DIR", tmp_path)
    sky = aviation.SkyBackground("noon", planes=0, clouds=0, airport=False)
    sky.resize(200, 100)
    assert sky._load_photo() is not None


def test_flow_layout_wraps(app):
    host = QWidget()
    lay = FlowLayout(host)
    from PySide6.QtWidgets import QPushButton
    for i in range(6):
        lay.addWidget(QPushButton(f"Button number {i}"))
    wide = lay.heightForWidth(1000)
    narrow = lay.heightForWidth(180)
    assert narrow > wide                                       # narrower -> more lines
