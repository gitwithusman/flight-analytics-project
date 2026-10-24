"""Render screenshots of every screen (desktop / tablet / phone) and still images of the aviation scenes.

    python main_task/make_screenshots.py            # -> docs/screenshots/*.png, assets/backgrounds/preview_*.png

Runs headless (Qt 'offscreen'). Flight Search is shown with a SAMPLE search so the results table is visible; no network
or API key is used and the project database is not modified (a temporary copy is used).
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QDate, QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src import config  # noqa: E402
from src.gui import aviation  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.gui.theme import build_stylesheet  # noqa: E402

SIZES = {"desktop": (1360, 840), "tablet": (900, 760), "phone": (390, 820)}
FULL_SET = ("overview", "search", "delays", "airport_analytics", "airlines", "map", "weather", "etl", "reports", "settings")


def pump(ms: int) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def main() -> None:
    out = ROOT / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    (ROOT / "assets" / "backgrounds").mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(build_stylesheet())
    tmp = Path(tempfile.mkdtemp())
    work_db = tmp / "screenshots.db"                      # work on a copy: the project database is never modified
    if config.DATABASE_PATH.exists():
        shutil.copy2(config.DATABASE_PATH, work_db)
    config.DATABASE_PATH = work_db
    config.SEARCH_FORCE_DEMO = True                       # screenshots never call a real API
    config.REDUCE_MOTION = True                           # one deterministic frame per image

    for scene in sorted(aviation.SCENES):                 # stills of the built-in scenes
        sky = aviation.SkyBackground(scene, planes=4, clouds=6, airport=True, seed=11)
        sky.resize(1600, 360)
        sky._t = 20.0
        sky.grab().save(str(ROOT / "assets" / "backgrounds" / f"preview_{scene}.png"))

    win = MainWindow()
    win.show()
    for size_name, (w, h) in SIZES.items():
        win.resize(w, h)
        pump(200)
        keys = FULL_SET if size_name == "desktop" else ("overview", "search", "airlines", "map")
        for key in keys:
            win.navigate(key)
            if key == "search":
                page = win.pages["search"]
                page.origin.set_iata("LHE")
                page.dest.set_iata("DXB")
                page.dep_date.setDate(QDate.currentDate().addDays(21))
                page.search()
                pump(900)
                page.table.selectRow(0)
            pump(250)
            win.grab().save(str(out / f"{key}_{size_name}.png"))
    # The delay-analytics part of the Flight Status page sits below the fold: capture it from the full page.
    win.resize(*SIZES["desktop"])
    win.navigate("delays")
    pump(400)
    page = win.pages["delays"]
    inner = page.scroll.widget()
    full = inner.grab()
    y0 = max(0, page.f_airline.mapTo(inner, QPoint(0, 0)).y() - 120)
    full.copy(0, y0, full.width(), min(980, full.height() - y0)).save(str(out / "delays_analytics_desktop.png"))
    win.close()
    print(f"Screenshots written to {out}")


if __name__ == "__main__":
    main()
