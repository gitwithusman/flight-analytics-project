"""Main window: navigation, header, status bar and the refresh workflow."""

from __future__ import annotations

import threading

import sys
from typing import Dict, Optional

import pandas as pd
from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from src import (
    APP_NAME, __version__, analytics, api_client, config, palette as P, service,
)
from src.utils import get_logger

from . import icons
from .aviation import SkyBackground
from .perf import render_queue
from .pages import (
    AboutPage, DataManagementPage, FlightAnalyticsPage, FlightExplorerPage, OverviewPage, SettingsPage,
)
from .pages_map import RouteMapPage
from .pages_ops import (
    AirlinePerformancePage, AirportDashboardPage, DestinationWeatherPage, EtlMonitorPage, FlightStatusPage, ReportsPage,
)
from .pages_travel import FlightSearchPage
from .store import DataStore
from .theme import SP_LG, SP_MD, SP_SM, SP_XL, build_stylesheet, repolish
from .widgets import Banner, ElidedLabel, make_shrinkable
from .workers import TaskRunner

logger = get_logger()

SIDEBAR_WIDE, SIDEBAR_COMPACT = 232, 64
COMPACT_BELOW = 1020        # window width that switches to the icon-only sidebar (tablet)
MOBILE_BELOW = 700          # below this the sidebar becomes a slide-in drawer (phone)
HIDE_UPDATED_BELOW = 1180   # window width below which "Updated ..." is hidden


class FlightStatusBar(QFrame):
    """Bottom strip: flight-condition chips, optional weather, last message."""

    CATEGORIES = ["On Time", "Delayed", "Cancelled", "Incident/Diverted",
                  "Weather Alert", "Weather Delay", "Landed", "Status Unknown"]
    ALWAYS = ("On Time", "Delayed", "Cancelled")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(SP_LG, 7, SP_LG, 7)
        self._row.setSpacing(SP_SM)
        self._lead = QLabel("FLIGHT CONDITIONS")
        self._lead.setObjectName("kpiLabel")
        self._row.addWidget(self._lead)
        self._chips: Dict[str, QLabel] = {}
        self._wanted: Dict[str, bool] = {}
        for cat in self.CATEGORIES:
            chip = QLabel(f"{cat}: 0")
            chip.setObjectName("chip")
            color = analytics.STATUS_BAR_COLORS.get(cat, P.TEXT_MUTED)
            chip.setStyleSheet(f"color: {color};")
            chip.hide()
            self._chips[cat] = chip
            self._row.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
        self.weather_chip = QLabel("")
        self.weather_chip.setObjectName("chip")
        self.weather_chip.setStyleSheet(f"color: {P.COBALT_DARK};")
        self.weather_chip.hide()
        self._row.addWidget(self.weather_chip)
        self._row.addStretch(1)
        self.message = ElidedLabel("Ready")
        self.message.setObjectName("statusMsg")
        self.message.setMinimumWidth(0)
        self.message.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._row.addWidget(self.message, 3)
        self._weather_wanted = False

    def update_conditions(self, df: pd.DataFrame) -> None:
        counts = analytics.condition_counts(df)
        has_data = not df.empty
        for cat, chip in self._chips.items():
            n = counts.get(cat, 0)
            chip.setText(f"{cat}: {n}")
            self._wanted[cat] = has_data and (cat in self.ALWAYS or n > 0)
        self._lead.setToolTip("Condition of every stored flight: " + ", ".join(
            f"{c} {counts.get(c, 0)}" for c in self.CATEGORIES))
        self._fit()

    def set_weather(self, text: Optional[str]) -> None:
        self.weather_chip.setText(text or "")
        self.weather_chip.setToolTip(text or "")
        self._weather_wanted = bool(text)
        self._fit()

    def set_message(self, text: str) -> None:
        self.message.setText(text)

    def _fit(self) -> None:
        """Show as many chips as fit, keeping room for the message."""
        budget = self.width() - 2 * SP_LG - self._lead.sizeHint().width() - 220
        for cat, chip in self._chips.items():
            if not self._wanted.get(cat):
                chip.hide()
                continue
            need = chip.sizeHint().width() + SP_SM
            chip.setVisible(budget >= need)
            budget -= need
        need = self.weather_chip.sizeHint().width() + SP_SM
        self.weather_chip.setVisible(self._weather_wanted and budget >= need)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._fit()


class LazyPages(dict):
    """The application's pages, each built the first time it is opened (start-up only builds the home page).

    Behaves like a normal dict for lookups, iteration and ``len``; iterating ``values()`` / ``items()`` builds every
    page, so internal code that must not force construction uses ``built()`` instead.
    """

    def __init__(self, factories, adopt):
        super().__init__()
        self._factories, self._adopt = dict(factories), adopt

    def __getitem__(self, key):
        if not dict.__contains__(self, key):
            if key not in self._factories:
                raise KeyError(key)
            page = self._factories[key]()
            dict.__setitem__(self, key, page)
            self._adopt(key, page)
        return dict.__getitem__(self, key)

    def __contains__(self, key):
        return key in self._factories

    def __iter__(self):
        return iter(self._factories)

    def __len__(self):
        return len(self._factories)

    def keys(self):
        return self._factories.keys()

    def values(self):
        return [self[k] for k in self._factories]

    def items(self):
        return [(k, self[k]) for k in self._factories]

    def get(self, key, default=None):
        return self[key] if key in self._factories else default

    def built(self):
        """(key, page) pairs for pages that already exist (never builds anything)."""
        return [(k, dict.__getitem__(self, k)) for k in self._factories if dict.__contains__(self, k)]


class _Scrim(QFrame):
    """Dimmed overlay behind the mobile navigation drawer; clicking it closes the drawer."""

    pressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: rgba(8, 20, 42, 150);")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide()

    def mousePressEvent(self, event):  # noqa: N802
        self.pressed.emit()


class MainWindow(QMainWindow):
    NAV = [
        ("section", None, "TRAVEL"),
        ("overview", "overview", "Home Dashboard"),
        ("search", "search", "Flight Search"),
        ("section", None, "OPERATIONS"),
        ("delays", "delays", "Flight Status and Delays"),
        ("airport_analytics", "airports", "Airport Analytics"),
        ("airlines", "flights", "Airline Performance"),
        ("map", "map", "Flight Route Map"),
        ("weather", "weather", "Destination Weather"),
        ("flight_analytics", "flights", "Flight Analytics"),
        ("explorer", "explorer", "Flight Explorer"),
        ("section", None, "DATA AND SYSTEM"),
        ("etl", "etl", "ETL Monitoring"),
        ("reports", "report", "Reports and Export"),
        ("data", "data", "Data Management"),
        ("settings", "settings", "Settings and API"),
        ("about", "about", "About"),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 840)
        self.setMinimumSize(340, 480)
        self.store = DataStore()
        # Load the database views in ONE short-lived worker thread while the window is being built, so the first
        # visit to a page finds them ready instead of waiting for SQLite on the GUI thread (loads are lock-guarded).
        threading.Thread(target=self.store.warm, name="skylens-warmup", daemon=True).start()
        self.tasks = TaskRunner(self)
        self._refreshing = False
        self.shared: dict = {"options": pd.DataFrame(), "query": None}
        self._compact: Optional[bool] = None
        self._mode: Optional[str] = None
        self._drawer_open = False
        self._fade_anim: Optional[QPropertyAnimation] = None
        self._fade_page: Optional[QWidget] = None
        self._wx_token = 0

        root_widget = QWidget()
        root_widget.setObjectName("appRoot")
        self.root_widget = root_widget
        self.setCentralWidget(root_widget)
        root = QHBoxLayout(root_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._root_layout = root

        self._build_sidebar(root)
        # The content area is a live sky: drifting clouds and airliners behind translucent bars and cards.
        self.canvas = SkyBackground("day", planes=3, clouds=8, airport=False, seed=21)
        column = QVBoxLayout(self.canvas)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        root.addWidget(self.canvas, 1)
        self._build_topbar(column)
        self.scrim = _Scrim(root_widget)
        self.scrim.pressed.connect(self.close_drawer)

        self.busy_bar = QProgressBar()
        self.busy_bar.setObjectName("busy")
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.hide()
        column.addWidget(self.busy_bar)

        banner_wrap = QWidget()
        bl = QVBoxLayout(banner_wrap)
        bl.setContentsMargins(SP_XL, SP_MD, SP_XL, 0)
        self.banner = Banner()
        bl.addWidget(self.banner)
        column.addWidget(banner_wrap)
        banner_wrap.setVisible(False)
        self.banner.visibilityChanged.connect(banner_wrap.setVisible)

        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        column.addWidget(self.stack, 1)
        self.pages = LazyPages({
            "overview": lambda: OverviewPage(self), "search": lambda: FlightSearchPage(self),
            "delays": lambda: FlightStatusPage(self), "airport_analytics": lambda: AirportDashboardPage(self),
            "airlines": lambda: AirlinePerformancePage(self), "map": lambda: RouteMapPage(self),
            "weather": lambda: DestinationWeatherPage(self), "flight_analytics": lambda: FlightAnalyticsPage(self),
            "explorer": lambda: FlightExplorerPage(self), "etl": lambda: EtlMonitorPage(self),
            "reports": lambda: ReportsPage(self), "data": lambda: DataManagementPage(self),
            "settings": lambda: SettingsPage(self), "about": lambda: AboutPage(self),
        }, self._adopt_page)
        self.status_bar = FlightStatusBar()
        column.addWidget(self.status_bar)

        self._install_shortcuts()
        QTimer.singleShot(400, self._prebuild_pages)
        self.navigate("overview")
        self.refresh_status_bar()
        self._apply_layout_mode()

    def _prebuild_pages(self) -> None:
        """Build the remaining pages one at a time while the app is idle, so first visits do not pay for it."""
        order = [k for k in self.pages.keys() if not dict.__contains__(self.pages, k)]
        if not order:
            return
        if render_queue.busy or not self.isVisible():
            QTimer.singleShot(300, self._prebuild_pages)       # the user is busy / window hidden: try again later
            return
        _ = self.pages[order[0]]                                # construct (no data work: reload still waits for a visit)
        QTimer.singleShot(60, self._prebuild_pages)

    def _adopt_page(self, key: str, page) -> None:
        """Called once when a page is first built: style it for its section and add it to the stack."""
        page.apply_section(key)
        make_shrinkable(page)
        self.stack.addWidget(page)
        if self.width() and page.width() != self.stack.width():
            page.resize(self.stack.size())
    # ---- construction helpers ------------------------------------------------
    def _build_sidebar(self, root: QHBoxLayout) -> None:
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sb = QVBoxLayout(self.sidebar)
        sb.setContentsMargins(0, 0, 0, SP_LG)
        sb.setSpacing(0)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(SP_LG + 4, SP_XL - 2, SP_LG, SP_MD)
        brand_row.setSpacing(SP_MD)
        self.logo = QLabel()
        icon_path = config.ASSETS_DIR / "icons" / "app.svg"
        if icon_path.exists():
            self.logo.setPixmap(QIcon(str(icon_path)).pixmap(QSize(32, 32)))
        else:
            self.logo.setPixmap(icons.pixmap("flights", "#FFFFFF", 28))
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.brand = QLabel("SkyLens")
        self.brand.setObjectName("brand")
        self.brand_sub = QLabel("Flight analytics")
        self.brand_sub.setObjectName("brandSub")
        titles.addWidget(self.brand)
        titles.addWidget(self.brand_sub)
        self.brand_titles = QWidget()
        self.brand_titles.setLayout(titles)
        brand_row.addWidget(self.logo)
        brand_row.addWidget(self.brand_titles, 1)
        sb.addLayout(brand_row)
        self._brand_row = brand_row

        nav_host = QWidget()
        nav_host.setObjectName("navHost")
        nav_host.setStyleSheet("#navHost { background: transparent; }")
        nl = QVBoxLayout(nav_host)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(0)
        self.nav_scroll = QScrollArea()
        self.nav_scroll.setWidgetResizable(True)
        self.nav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: 0; } QScrollBar:vertical { width: 6px; background: transparent; } "
            "QScrollBar::handle:vertical { background: rgba(255,255,255,70); border-radius: 3px; min-height: 24px; } "
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }")
        self.nav_scroll.setWidget(nav_host)
        self.nav_buttons: Dict[str, QPushButton] = {}
        self._nav_labels: Dict[str, str] = {}
        self._sections = []
        for key, icon_name, label in self.NAV:
            if key == "section":
                sec = QLabel(label)
                sec.setObjectName("navSection")
                self._sections.append(sec)
                nl.addWidget(sec)
                continue
            btn = QPushButton(label)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.setProperty("navkey", key)
            btn.setIcon(icons.icon(icon_name, P.TEXT_ON_DARK_MUTED, "#FFFFFF", 20))
            btn.setIconSize(QSize(20, 20))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setAccessibleName(label)
            btn.clicked.connect(lambda _=False, k=key: self.navigate(k))
            self.nav_buttons[key] = btn
            self._nav_labels[key] = label
            nl.addWidget(btn)
        nl.addStretch(1)
        sb.addWidget(self.nav_scroll, 1)
        self.foot = QLabel(f"v{__version__}  \u2022  Flight & airport analytics")
        self.foot.setObjectName("navFoot")
        sb.addWidget(self.foot)
        root.addWidget(self.sidebar)

    def _build_topbar(self, column: QVBoxLayout) -> None:
        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        topbar.setFixedHeight(60)
        self.topbar = topbar
        hl = QHBoxLayout(topbar)
        hl.setContentsMargins(SP_LG, 0, SP_LG, 0)
        hl.setSpacing(SP_MD)
        self.menu_btn = QPushButton()
        self.menu_btn.setIcon(icons.icon("menu", P.TEXT, size=20))
        self.menu_btn.setIconSize(QSize(20, 20))
        self.menu_btn.setFixedSize(40, 36)
        self.menu_btn.setToolTip("Open the navigation menu")
        self.menu_btn.setAccessibleName("Open navigation menu")
        self.menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_btn.clicked.connect(self.open_drawer)
        self.menu_btn.hide()
        hl.addWidget(self.menu_btn)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        titles.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.page_title = QLabel("Overview")
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = ElidedLabel("")
        self.page_subtitle.setObjectName("pageSubtitle")
        titles.addWidget(self.page_title)
        self.page_subtitle.hide()          # the hero banner carries the subtitle
        hl.addLayout(titles, 3)

        self.header_search = QLineEdit()
        self.header_search.setPlaceholderText("Search flights (Ctrl+K)")
        self.header_search.setClearButtonEnabled(True)
        self.header_search.setAccessibleName("Search all flights")
        self.header_search.setMinimumWidth(140)
        self.header_search.setMaximumWidth(280)
        self.header_search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header_search.returnPressed.connect(self._header_search)
        hl.addWidget(self.header_search, 2, Qt.AlignmentFlag.AlignVCenter)

        self.api_label = QLabel("")
        self.api_label.setObjectName("chip")
        hl.addWidget(self.api_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.last_updated = QLabel("")
        self.last_updated.setObjectName("updated")
        hl.addWidget(self.last_updated, 0, Qt.AlignmentFlag.AlignVCenter)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("primary")
        self.refresh_btn.setIcon(icons.icon("refresh", "#FFFFFF", size=16))
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setToolTip("Retrieve the latest flights (F5)")
        self.refresh_btn.clicked.connect(lambda: self.start_refresh())
        hl.addWidget(self.refresh_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        column.addWidget(topbar)

    def _install_shortcuts(self) -> None:
        keys = [k for k, _i, _l in self.NAV if k != "section"]
        for i, key in enumerate(keys[:9], start=1):
            sc = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
            sc.activated.connect(lambda k=key: self.navigate(k))
            self.nav_buttons[key].setToolTip(f"{self._nav_labels[key]} (Ctrl+{i})")
        for seq in ("F5", "Ctrl+R"):
            QShortcut(QKeySequence(seq), self).activated.connect(lambda: self.start_refresh())
        QShortcut(QKeySequence("Ctrl+K"), self).activated.connect(self._focus_search)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._focus_search)

    def _focus_search(self) -> None:
        if self._current_key() == "explorer":
            self.pages["explorer"].focus_search()
        else:
            self.header_search.setFocus()
            self.header_search.selectAll()

    # ---- responsive layout -----------------------------------------------------
    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._apply_layout_mode()

    def _apply_layout_mode(self) -> None:
        """Desktop (full sidebar), tablet (icon sidebar) or phone (slide-in drawer) by window width."""
        width = self.width()
        mode = "mobile" if width < MOBILE_BELOW else "tablet" if width < COMPACT_BELOW else "desktop"
        self.last_updated.setVisible(width >= HIDE_UPDATED_BELOW)
        self.header_search.setVisible(width >= 640)
        self.api_label.setVisible(width >= 520)
        self.refresh_btn.setText("" if width < 480 else ("Syncing\u2026" if self._refreshing else "Refresh"))
        self.topbar.setFixedHeight(54 if mode == "mobile" else 60)
        if self._drawer_open:
            self._place_drawer(animated=False)
        if mode == self._mode:
            return
        previous, self._mode = self._mode, mode
        compact = mode == "tablet"
        self._compact = compact
        self.menu_btn.setVisible(mode == "mobile")
        if mode == "mobile":
            self._root_layout.removeWidget(self.sidebar)
            self.sidebar.setParent(self.root_widget)
            self.sidebar.hide()
            self._drawer_open = False
        elif previous == "mobile":
            self.close_drawer(animate=False)
            self._root_layout.insertWidget(0, self.sidebar)
            self.sidebar.show()
        self.sidebar.setFixedWidth(SIDEBAR_COMPACT if compact else SIDEBAR_WIDE)
        self.brand_titles.setVisible(not compact)
        self.foot.setVisible(not compact)
        m = self._brand_row.contentsMargins()
        self._brand_row.setContentsMargins(16 if compact else SP_LG + 4, m.top(), m.right(), m.bottom())
        for sec in self._sections:
            sec.setVisible(not compact)
        for key, btn in self.nav_buttons.items():
            btn.setText("" if compact else self._nav_labels[key])
            btn.setProperty("compact", compact)
            repolish(btn)

    # ---- mobile navigation drawer -----------------------------------------------------
    def _place_drawer(self, animated: bool = True) -> None:
        h = self.root_widget.height()
        self.sidebar.setFixedWidth(SIDEBAR_WIDE)
        self.sidebar.setGeometry(0 if not animated else -SIDEBAR_WIDE, 0, SIDEBAR_WIDE, h)
        self.scrim.setGeometry(self.root_widget.rect())

    def open_drawer(self) -> None:
        if self._mode != "mobile" or self._drawer_open:
            return
        self._drawer_open = True
        self.scrim.show()
        self.scrim.raise_()
        self.sidebar.show()
        self.sidebar.raise_()
        self._place_drawer(animated=not config.REDUCE_MOTION)
        if not config.REDUCE_MOTION:
            anim = QPropertyAnimation(self.sidebar, b"pos", self)
            anim.setDuration(220)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setStartValue(QPoint(-SIDEBAR_WIDE, 0))
            anim.setEndValue(QPoint(0, 0))
            anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def close_drawer(self, animate: bool = True) -> None:
        if not self._drawer_open:
            self.scrim.hide()
            return
        self._drawer_open = False
        self.scrim.hide()
        if self._mode == "mobile":
            self.sidebar.hide()

    # ---- navigation ---------------------------------------------------------------
    def navigate(self, key: str) -> None:
        for k, btn in self.nav_buttons.items():
            btn.setChecked(k == key)
        page = self.pages[key]
        changed = self.stack.currentWidget() is not page
        self.stack.setCurrentWidget(page)
        self.page_title.setText(page.title)
        self.page_subtitle.setText(page.subtitle)
        if self._mode == "mobile":
            self.close_drawer()
        if changed:
            self._fade_in(page)
        try:
            page.reload_if_needed()       # pages whose data did not change are shown as they were left: instant
        except Exception as exc:
            logger.exception("Page %s failed to load", key)
            self.notify(f"Could not load this page: {exc}", "error")

    def apply_motion_setting(self) -> None:
        """Start or stop all animated scenery after the 'Reduce animations' setting changed."""
        on = not config.REDUCE_MOTION
        self.canvas.set_animated(on)
        for _key, page in self.pages.built():
            page.hero.set_animated(on)

    def _fade_in(self, page: QWidget) -> None:
        """Short fade-in when a page is shown (skipped when animations are reduced)."""
        if config.REDUCE_MOTION:
            return
        # Only the (small) hero banner fades: a whole-page opacity effect forces every chart and table of the page
        # to be re-rasterised on each frame, which is what made switching feel heavy.
        if self._fade_anim is not None:
            self._fade_anim.stop()
            if self._fade_page is not None:
                self._fade_page.setGraphicsEffect(None)
        target = page.hero
        effect = QGraphicsOpacityEffect(target)
        effect.setOpacity(0.0)
        target.setGraphicsEffect(effect)
        page = target
        anim = QPropertyAnimation(effect, b"opacity", target)
        anim.setDuration(180)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda p=page: p.setGraphicsEffect(None))
        self._fade_anim, self._fade_page = anim, page
        anim.start()

    def _current_key(self) -> str:
        widget = self.stack.currentWidget()
        for k, p in self.pages.built():
            if p is widget:
                return k
        return "overview"

    def _header_search(self) -> None:
        text = self.header_search.text().strip()
        self.navigate("explorer")
        if text:
            self.pages["explorer"].set_global_search(text)
        self.header_search.clear()

    # ---- refresh workflow ---------------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self._refreshing = busy
        self.refresh_btn.setEnabled(not busy)
        self.refresh_btn.setText("Syncing\u2026" if busy else "Refresh")
        self.busy_bar.setVisible(busy)
        self.pages["data"].set_busy(busy)

    def start_refresh(self, **filters) -> None:
        if self._refreshing:
            return
        if not config.api_key_configured():
            self.notify("No API key configured. Add one in Settings to retrieve data.", "warning")
            self.navigate("settings")
            return
        self._set_busy(True)
        self.status_bar.set_message("Retrieving flights from AviationStack\u2026")
        self.tasks.submit(service.refresh_data, on_done=self._refresh_done,
                          on_error=self._refresh_failed, **filters)

    def _refresh_done(self, result: service.RefreshResult) -> None:
        self._set_busy(False)
        self.store.invalidate()
        self.pages["data"].set_result(result)
        self.status_bar.set_message(result.message)
        if not result.success:
            self.notify(result.message, "error")
        elif result.stored == 0:
            self.notify(f"{result.message} No new records were stored.", "warning")
        else:
            self.notify(result.message, "success")
        self.refresh_status_bar()
        try:
            self.pages[self._current_key()].reload_if_needed()
        except Exception:
            logger.exception("Reload after refresh failed")

    def _refresh_failed(self, message: str) -> None:
        self._set_busy(False)
        self.pages["data"].set_error(message)
        self.status_bar.set_message("Refresh failed")
        self.notify(f"Refresh failed: {message}", "error")

    # ---- header + status bar -------------------------------------------------------
    def _update_api_status(self) -> None:
        ok = config.api_key_configured()
        self.api_label.setText("API key set" if ok else "API key missing")
        self.api_label.setStyleSheet(f"color: {P.SUCCESS if ok else P.ERROR};")
        self.api_label.setToolTip(
            "An API key is configured. The connection itself is checked when data is retrieved."
            if ok else "Open Settings to add your AviationStack API key.")
        try:
            info = self.store.info()
            last = info.get("last_success") or info.get("last_refresh")
        except Exception:
            last = None
        text = f"Updated {last}" if last else "No data retrieved yet"
        self.last_updated.setText(text)
        self.last_updated.setToolTip(text)

    def refresh_status_bar(self) -> None:
        try:
            self.status_bar.update_conditions(self.store.flights())
        except Exception:
            logger.exception("Could not read flights for the status bar")
            self.status_bar.update_conditions(pd.DataFrame())
        self._update_api_status()
        self._wx_token += 1
        token = self._wx_token
        if config.ENABLE_WEATHER_LOOKUP and config.WEATHER_LATITUDE and config.WEATHER_LONGITUDE:
            try:
                lat, lon = float(config.WEATHER_LATITUDE), float(config.WEATHER_LONGITUDE)
            except ValueError:
                self.status_bar.set_weather(None)
                return
            label = config.WEATHER_LABEL

            def _done(weather):
                if token == self._wx_token:  # ignore stale answers
                    self.status_bar.set_weather(
                        f"{label}: {api_client.weather_summary(weather)}" if weather else None)

            self.tasks.submit(api_client.fetch_weather, on_done=_done,
                              on_error=lambda _e: None, owner=self.status_bar,
                              latitude=lat, longitude=lon)
        else:
            self.status_bar.set_weather(None)

    def notify(self, message: str, kind: str = "info") -> None:
        """Show a non-blocking notification (kinds: success/info/warning/error)."""
        if isinstance(kind, bool):  # backwards compatible with notify(msg, error=True)
            kind = "error" if kind else "info"
        self.banner.show_message(message, kind)
        self.status_bar.set_message(message.replace("\u200b", ""))

    def closeEvent(self, event):  # noqa: N802
        # Let in-flight requests finish so no worker thread is destroyed mid-run.
        self.tasks.wait(3000)
        super().closeEvent(event)


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(build_stylesheet())
    icon_path = config.ASSETS_DIR / "icons" / "app.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    return app.exec()
