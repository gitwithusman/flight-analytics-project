"""Reusable building blocks shared by all pages."""

from __future__ import annotations

from typing import Callable, List, Optional

import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtCore import QEasingCurve, QPoint, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QLayout, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from src import config, palette as P, visualizations

from . import icons
from .aviation import SkyBackground
from .perf import render_queue
from .theme import RADIUS, SECTION_STYLE, SP_LG, SP_MD, SP_SM, SP_XL, repolish


class FlowLayout(QLayout):
    """Left-to-right layout that wraps onto new lines when the width runs out (buttons, chips)."""

    def __init__(self, parent=None, spacing: int = SP_SM + 2):
        super().__init__(parent)
        self._items = []
        self._space = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, dry=False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, dry):
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = area.x(), area.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            if x + hint.width() > area.right() + 1 and line_h > 0:
                x, y, line_h = area.x(), y + line_h + self._space, 0
            if not dry:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._space
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class FlowRow(QWidget):
    """A QWidget wrapping a FlowLayout; drop-in for a QHBoxLayout of buttons (addStretch is a no-op)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._flow = FlowLayout(self)

    def addWidget(self, widget, *_args, **_kw):  # noqa: N802
        self._flow.addWidget(widget)

    def addStretch(self, *_args):  # noqa: N802
        pass


class Card(QFrame):
    """Raised white surface. Soft shadow and an accent border fade in while the pointer is over it."""

    def __init__(self, parent=None, margins=(SP_LG, SP_MD + 2, SP_LG, SP_LG),
                 spacing: int = SP_MD, accent: str = P.COBALT):
        super().__init__(parent)
        self.setObjectName("card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._accent = accent
        self._hover = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_hover)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(*margins)
        self.body.setSpacing(spacing)

    def set_accent(self, color: str) -> None:
        self._accent = color
        self.update()

    def _set_hover(self, value) -> None:
        self._hover = float(value)
        self.update()

    def _animate_to(self, target: float) -> None:
        if config.REDUCE_MOTION:
            self._set_hover(target)
            return
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(target)
        self._anim.start()

    def enterEvent(self, event):  # noqa: N802
        self._animate_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._animate_to(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = QRectF(self.rect()).adjusted(1.5, 1.0, -1.5, -4.0)
        p.setPen(Qt.PenStyle.NoPen)
        for i, alpha in enumerate((7, 9, 12)):                       # layered soft shadow
            grow = 3 - i
            sh = QColor(11, 37, 69, int(alpha + 12 * self._hover))
            p.setBrush(sh)
            p.drawRoundedRect(base.adjusted(-grow + 1, 2 + (3 - grow) * 0.5, grow - 1, grow + 1.5), RADIUS + 3, RADIUS + 3)
        p.setBrush(QColor(255, 255, 255, 247))
        border = QColor(P.BORDER)
        acc = QColor(self._accent)
        mix = lambda a, b: int(a + (b - a) * self._hover)              # noqa: E731
        border = QColor(mix(border.red(), acc.red()), mix(border.green(), acc.green()), mix(border.blue(), acc.blue()))
        p.setPen(QPen(border, 1.0 + 0.6 * self._hover))
        p.drawRoundedRect(base, RADIUS + 2, RADIUS + 2)

    def add_title(self, text: str, note: str = "") -> QLabel:
        title = QLabel(text)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        self.body.addWidget(title)
        if note:
            sub = QLabel(note)
            sub.setObjectName("cardNote")
            sub.setWordWrap(True)
            self.body.addWidget(sub)
        return title


class ActionTile(Card):
    """Clickable tile: coloured icon chip, title and caption (keyboard accessible)."""

    clicked = Signal()

    def __init__(self, title: str, caption: str, icon_name: str, accent: str, parent=None):
        super().__init__(parent, margins=(SP_LG, SP_MD, SP_LG, SP_MD), spacing=2, accent=accent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title)
        self.setToolTip(caption)
        row = QHBoxLayout()
        row.setSpacing(SP_MD)
        chip = QLabel()
        chip.setFixedSize(40, 40)
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setPixmap(icons.pixmap(icon_name, "#FFFFFF", 22))
        chip.setStyleSheet(f"background: {accent}; border-radius: 12px;")
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(title)
        t.setObjectName("tileTitle")
        c = QLabel(caption)
        c.setObjectName("cardNote")
        c.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(c)
        row.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(col, 1)
        self.body.addLayout(row)
        for w in (chip, t, c):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event):  # noqa: N802
        self._animate_to(1.0)
        super().focusInEvent(event)

    def focusOutEvent(self, event):  # noqa: N802
        self._animate_to(0.0)
        super().focusOutEvent(event)


class HeroBanner(SkyBackground):
    """Page header: an animated aviation scene in the section's colours with the page title on top."""

    HEIGHT, COMPACT_HEIGHT = 150, 104

    def __init__(self, parent=None):
        super().__init__("noon", planes=3, clouds=6, airport=True, seed=5, parent=parent)
        self._accent = P.COBALT
        self.setObjectName("hero")
        self.setFixedHeight(self.HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SP_XL, SP_MD, SP_XL, 30)
        lay.setSpacing(SP_LG)
        self.chip = QLabel()
        self.chip.setFixedSize(56, 56)
        self.chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = QLabel("")
        self.title.setObjectName("heroTitle")
        self.title.setWordWrap(True)
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("heroSubtitle")
        self.subtitle.setWordWrap(True)
        col.addStretch(1)
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        col.addStretch(1)
        lay.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(col, 1)
        self._compact = False

    def set_content(self, title: str, subtitle: str, accent: str, scene: str, icon_name: str) -> None:
        self._accent = accent
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.chip.setPixmap(icons.pixmap(icon_name, "#FFFFFF", 28))
        self.chip.setStyleSheet(f"background: {accent}; border-radius: 16px; border: 2px solid rgba(255,255,255,120);")
        self.set_scene(scene)

    def set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        self.setFixedHeight(self.COMPACT_HEIGHT if compact else self.HEIGHT)
        self.subtitle.setVisible(not compact)
        self.title.setStyleSheet("font-size: 21px;" if compact else "")
        self.chip.setFixedSize(*( (40, 40) if compact else (56, 56) ))
        m = self.layout().contentsMargins()
        self.layout().setContentsMargins(SP_LG if compact else SP_XL, m.top(), SP_LG if compact else SP_XL, 22 if compact else 30)

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        w, h = self.width(), self.height()
        g = QLinearGradient(0, 0, w * 0.7, 0)                          # keeps white text readable on any scene
        g.setColorAt(0, QColor(8, 20, 42, 200))
        g.setColorAt(1, QColor(8, 20, 42, 0))
        p.fillRect(QRectF(0, 0, w, h), g)
        p.fillRect(QRectF(0, h - 4, w, 4), QColor(self._accent))


class KpiCard(Card):
    """Metric tile: label, value, supporting note and a colour accent."""

    def __init__(self, label: str, accent: str = P.COBALT, parent=None):
        super().__init__(parent, margins=(0, 0, 0, 0), spacing=0, accent=accent)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.body.addLayout(row)
        bar = QFrame()
        bar.setObjectName("kpiBar")
        bar.setStyleSheet(f"background: {accent};")
        row.addWidget(bar)
        col = QVBoxLayout()
        col.setContentsMargins(SP_LG, SP_MD + 2, SP_LG, SP_MD + 2)
        col.setSpacing(2)
        row.addLayout(col, 1)
        self.label = QLabel(label)
        self.label.setObjectName("kpiLabel")
        self.value = QLabel("\u2013")
        self.value.setObjectName("kpiValue")
        self.note = QLabel("")
        self.note.setObjectName("kpiNote")
        self.note.setWordWrap(True)
        for w in (self.label, self.value, self.note):
            col.addWidget(w)
        self.setMinimumHeight(92)

    def set_value(self, value, note: str = "") -> None:
        self.value.setText(str(value))
        self.note.setText(note)
        self.value.setToolTip(str(value))


class ResponsiveGrid(QWidget):
    """Grid that re-flows its children into fewer/more columns on resize."""

    def __init__(self, min_item_width: int = 240, max_columns: int = 4,
                 spacing: int = SP_MD + 2, parent=None):
        super().__init__(parent)
        self._min_w, self._max_cols, self._spacing = min_item_width, max_columns, spacing
        self._items: List[QWidget] = []
        self._cols = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(spacing)

    def add(self, widget: QWidget) -> QWidget:
        self._items.append(widget)
        self._reflow(force=True)
        return widget

    def columns(self) -> int:
        return self._cols

    def _wanted_columns(self) -> int:
        width = max(self.width(), 1)
        fit = (width + self._spacing) // (self._min_w + self._spacing)
        n = len(self._items) or 1
        cols = max(1, min(self._max_cols, n, int(fit)))
        if cols >= 3:
            # avoid an orphan card on the last row (5 -> 3+2, 4 -> 2+2, 6 -> 3+3)
            options = range(cols, max(cols - 2, 1) - 1, -1)
            cols = min(options, key=lambda c: ((-n) % c, -c))
        return cols

    def _reflow(self, force: bool = False) -> None:
        cols = self._wanted_columns()
        if cols == self._cols and not force:
            return
        self._cols = cols
        for w in self._items:
            self._grid.removeWidget(w)
        for i, w in enumerate(self._items):
            self._grid.addWidget(w, i // cols, i % cols)
        for c in range(self._max_cols + 1):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._reflow()


class ChartCard(Card):
    """Card holding one Matplotlib canvas plus a 'Save PNG' action."""

    def __init__(self, chart_key: str, title: str, min_height: int = 280,
                 parent=None):
        super().__init__(parent, margins=(SP_LG, SP_MD, SP_LG, SP_MD), spacing=SP_SM)
        self.chart_key = chart_key
        self._df: Optional[pd.DataFrame] = None
        self._canvas: Optional[FigureCanvasQTAgg] = None
        self._placeholder: Optional[QLabel] = None
        self._dirty = False
        self._min_h = min_height
        head = QHBoxLayout()
        self._title = QLabel(title)
        self._title.setObjectName("cardTitle")
        self._save = QPushButton("Save PNG")
        self._save.setObjectName("subtle")
        self._save.setIcon(icons.icon("download", P.COBALT_DARK, size=16))
        self._save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save.setToolTip("Save this chart as a PNG image")
        self._save.clicked.connect(self._save_png)
        head.addWidget(self._title, 1)
        head.addWidget(self._save)
        self.body.addLayout(head)
        self._holder = QVBoxLayout()
        self._holder.setContentsMargins(0, 0, 0, 0)
        self.body.addLayout(self._holder, 1)
        self.setMinimumHeight(min_height + 56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def render(self, df: pd.DataFrame) -> None:
        """Queue the chart; it is drawn from the event loop so the click that opened the page returns at once."""
        self._df = df
        self._save.setEnabled(df is not None and not df.empty)
        self._dirty = True
        if self._canvas is None and self._placeholder is None:
            self._placeholder = QLabel("Preparing chart\u2026")
            self._placeholder.setObjectName("muted")
            self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._placeholder.setMinimumHeight(self._min_h)
            self._holder.addWidget(self._placeholder)
        render_queue.submit(self, self.render_now)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._dirty:
            render_queue.submit(self, self.render_now)

    def render_now(self) -> None:
        if not self._dirty or not self.isVisible():   # hidden page: drawn when it is shown (see showEvent)
            return
        self._dirty = False
        df = self._df
        figure = visualizations.build_chart(self.chart_key, df, with_title=False)
        if self._placeholder is not None:
            self._holder.removeWidget(self._placeholder)
            self._placeholder.deleteLater()
            self._placeholder = None
        if self._canvas is not None:
            self._holder.removeWidget(self._canvas)
            self._canvas.hide()
            self._canvas.deleteLater()
        self._canvas = FigureCanvasQTAgg(figure)
        self._canvas.setMinimumHeight(self._min_h)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._holder.addWidget(self._canvas)

    def _save_png(self) -> None:
        if self._df is None:
            return
        main = self.window()
        notify = getattr(main, "notify", None)
        default = str(config.VISUALIZATIONS_DIR / f"{self.chart_key}.png")
        path, _ = QFileDialog.getSaveFileName(self, "Save chart", default, "PNG image (*.png)")
        if not path:
            return
        try:
            fig = visualizations.build_chart(self.chart_key, self._df, with_title=True)
            fig.savefig(path, dpi=150, facecolor=visualizations.SAVE_BG)
            if notify:
                notify(f"Chart saved to {path}", "success")
        except Exception as exc:  # disk full, permission denied, ...
            if notify:
                notify(f"Could not save the chart: {exc}", "error")


class EmptyState(Card):
    """Friendly placeholder shown when there is nothing to display yet."""

    def __init__(self, title: str, body: str, action_text: str = "",
                 action: Optional[Callable] = None, parent=None):
        super().__init__(parent, margins=(64, 32, 64, 32), spacing=SP_MD)
        pic = QLabel()
        pic.setPixmap(icons.pixmap("inbox", P.COBALT, 40))
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = QLabel(title)
        t.setObjectName("emptyTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b = QLabel(body)
        b.setObjectName("emptyBody")
        b.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b.setWordWrap(True)
        for w in (pic, t, b):
            self.body.addWidget(w)
        if action_text and action:
            btn = QPushButton(action_text)
            btn.setObjectName("primary")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda: action())
            self.body.addWidget(btn, alignment=Qt.AlignmentFlag.AlignHCenter)


class Banner(QFrame):
    """Non-blocking, dismissible notification (success / info / warning / error)."""

    visibilityChanged = Signal(bool)

    _ICON = {"success": ("check", P.SUCCESS), "info": ("about", P.COBALT),
             "warning": ("alert", P.WARNING), "error": ("error", P.ERROR)}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SP_MD, SP_SM, SP_SM, SP_SM)
        lay.setSpacing(SP_MD - 2)
        self._icon = QLabel()
        self._text = QLabel()
        self._text.setObjectName("bannerText")
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._close = QPushButton()
        self._close.setObjectName("bannerClose")
        self._close.setIcon(icons.icon("close", P.TEXT_MUTED, size=14))
        self._close.setToolTip("Dismiss")
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close.clicked.connect(self.dismiss)
        lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self._text, 1)
        lay.addWidget(self._close, 0, Qt.AlignmentFlag.AlignTop)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self.hide()

    def dismiss(self) -> None:
        self._timer.stop()
        self.hide()
        self.visibilityChanged.emit(False)

    def show_message(self, text: str, kind: str = "info") -> None:
        name, color = self._ICON.get(kind, self._ICON["info"])
        self._icon.setPixmap(icons.pixmap(name, color, 18))
        self._text.setText(text)
        self.setProperty("kind", kind)
        repolish(self)
        self.show()
        self.visibilityChanged.emit(True)
        self._timer.stop()
        if kind in ("success", "info"):
            self._timer.start(6000)  # errors/warnings stay until dismissed


class PageBase(QWidget):
    """Scrollable page: animated hero banner, then the standard content column."""

    title = "Page"
    subtitle = ""
    scrolls = True
    section: Optional[str] = None
    volatile = False       # True: cheap page that always reflects live settings -> reloaded on every visit
    uses_runs = False      # True: also depends on the ETL run history (not only on stored flights)

    def __init__(self, main):
        super().__init__()
        self.setObjectName("pageRoot")
        self.main = main
        self._loaded_key = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        inner = QWidget()
        inner.setObjectName("scrollInner")
        column = QVBoxLayout(inner)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.hero = HeroBanner()
        column.addWidget(self.hero)
        content = QWidget()
        content.setObjectName("scrollInner")
        self.body = QVBoxLayout(content)
        self._margins = SP_XL
        self.body.setContentsMargins(SP_XL, SP_LG, SP_XL, SP_XL)
        self.body.setSpacing(SP_LG)
        column.addWidget(content, 1)
        self.apply_section(None)
        if self.scrolls:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.viewport().setObjectName("scrollViewport")
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setWidget(inner)
            self.scroll = scroll
            outer.addWidget(scroll)
        else:
            outer.addWidget(inner)

    def apply_section(self, key: Optional[str]) -> None:
        """Colour the hero banner for this section (called by the main window with the navigation key)."""
        self.section = key or self.section
        accent, scene, icon_name = SECTION_STYLE.get(self.section or "", SECTION_STYLE["overview"])
        self.hero.set_content(self.title, self.subtitle, accent, scene, icon_name)
        self._accent = accent

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        w = event.size().width()
        m = SP_SM + 2 if w < 520 else SP_LG if w < 820 else SP_XL
        if m != self._margins:
            self._margins = m
            self.body.setContentsMargins(m, SP_LG if m > SP_SM + 2 else SP_MD, m, m + 4)
        self.hero.set_compact(w < 560)

    def reload(self) -> None:
        """Refresh content from shared state (must be safe with no data)."""

    def data_key(self):
        """What this page's content depends on; it is rebuilt only when this changes (or on a forced reload)."""
        store = self.main.store
        return (store.version, store.runs_version if self.uses_runs else 0)

    def needs_reload(self) -> bool:
        return self._loaded_key != self.data_key()

    def mark_loaded(self) -> None:
        self._loaded_key = self.data_key()

    def invalidate_view(self) -> None:
        """Force the next visit (or reload_if_needed) to rebuild the page."""
        self._loaded_key = None

    def reload_if_needed(self, force: bool = False) -> bool:
        """Rebuild the page only if its data changed since the last build. Returns True when it did."""
        if not (force or self.volatile or self.needs_reload()):
            return False
        self.reload()
        self.mark_loaded()
        return True


class ElidedLabel(QLabel):
    """Single-line label that truncates with an ellipsis instead of forcing
    its container wider (long paths, status messages)."""

    def __init__(self, text: str = "", mode=Qt.TextElideMode.ElideRight, parent=None):
        super().__init__(parent)
        self._mode = mode
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        super().setText(text)
        self.setToolTip(text)
        self.update()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event):  # noqa: N802
        from PySide6.QtGui import QPainter, QPalette
        painter = QPainter(self)
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self._full, self._mode, rect.width())
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.drawText(rect, int(self.alignment()), text)


def soft_path(path) -> str:
    """Let long file paths wrap at separators inside word-wrapped labels."""
    return str(path).replace("/", "/\u200b").replace("\\", "\\\u200b")


def labelled(text: str, widget: QWidget, hint: str = "") -> QWidget:
    """Form field: small caption above its input (and optional helper text)."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    cap = QLabel(text)
    cap.setObjectName("formLabel")
    cap.setBuddy(widget)
    lay.addWidget(cap)
    lay.addWidget(widget)
    if hint:
        h = QLabel(hint)
        h.setObjectName("cardNote")
        h.setWordWrap(True)
        lay.addWidget(h)
    return box


def make_shrinkable(root: QWidget) -> None:
    """Let combo boxes and line edits narrow below their content width so phone layouts never scroll sideways."""
    from PySide6.QtWidgets import QComboBox, QLineEdit
    for box in root.findChildren(QComboBox):
        box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        box.setMinimumContentsLength(6)
    for edit in root.findChildren(QLineEdit):
        edit.setMinimumWidth(min(edit.minimumWidth() or 90, 90))
