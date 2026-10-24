"""Reusable widgets for the travel / operations pages.

* ``OriginBadge``  - LIVE / HISTORICAL / SAMPLE chip (never ambiguous)
* ``AirportEdit``  - IATA input with autocomplete from the airport reference data
* ``FigureCard``   - card with an embedded Matplotlib figure and 'Save PNG'
* ``ExportBar``    - CSV / Excel / PDF buttons that export the rows on screen
"""

from __future__ import annotations

import re
from typing import Callable, Dict, Optional

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCompleter, QDateEdit, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from src import config, palette as P, reference, reports, visualizations
from src.providers.base import DATA_ORIGIN_LABELS

from . import icons
from .theme import SP_LG, SP_MD, SP_SM, repolish
from .perf import render_queue
from .widgets import Card, FlowLayout

_BADGE_STYLES = {
    "sample": ("#FFF4D6", "#8A5A00", "#E8C766"),
    "live_api": ("#E4F5EA", "#15703E", "#A8D9BC"),
    "historical": ("#EEF1F5", "#47556A", "#CBD3DF"),
}


class OriginBadge(QLabel):
    """Small coloured chip stating where the data came from."""

    def __init__(self, origin: str = "historical", parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_origin(origin)

    def set_origin(self, origin: str, text: Optional[str] = None) -> None:
        bg, fg, border = _BADGE_STYLES.get(origin, _BADGE_STYLES["historical"])
        self.setText(text or DATA_ORIGIN_LABELS.get(origin, origin.upper()))
        self.setStyleSheet(f"background:{bg}; color:{fg}; border:1px solid {border}; border-radius:9px;"
                           "padding:2px 10px; font-size:11px; font-weight:700;")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


def info_label(text: str, kind: str = "muted", wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("muted" if kind == "muted" else kind)
    lab.setWordWrap(wrap)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


def notice_box(text: str, kind: str = "warning") -> QLabel:
    """Tinted inline notice (warning / info / error / success)."""
    colors = {"warning": ("#FFF4D6", "#7A4F00", "#E8C766"), "info": ("#E7EFFB", "#1B4F9C", "#B8CDEE"),
              "error": ("#FCE8E6", "#9B2C20", "#F1B8B1"), "success": ("#E4F5EA", "#15703E", "#A8D9BC")}
    bg, fg, border = colors[kind]
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(f"background:{bg}; color:{fg}; border:1px solid {border}; border-radius:8px; padding:8px 12px;")
    return lab


class AirportEdit(QLineEdit):
    """Airport input: type a code, city or name; pick from the autocomplete list."""

    _labels: Optional[list] = None   # shared across instances (9k strings, built once)
    _known: Optional[set] = None

    def __init__(self, placeholder: str = "City, airport or IATA code", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setAccessibleName(placeholder)
        self._ensure_labels()
        comp = QCompleter(AirportEdit._labels, self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setMaxVisibleItems(10)
        self.setCompleter(comp)

    @classmethod
    def _ensure_labels(cls) -> None:
        if cls._labels is not None:
            return
        ref = reference.airport_reference()
        large = {"large_airport": 0, "medium_airport": 1}
        ref = ref.assign(_r=ref["airport_type"].map(large).fillna(2)).sort_values(["_r", "iata"])
        cls._labels = [f"{r.iata} \u2013 {r.name}, {r.city or ''} ({r.country or ''})".replace(", (", " (")
                       for r in ref.itertuples(index=False)]
        cls._known = set(ref["iata"])

    @classmethod
    def known_codes(cls) -> set:
        cls._ensure_labels()
        return cls._known or set()

    def iata(self) -> str:
        """The airport code in the field ('' if it cannot be understood)."""
        text = self.text().strip()
        m = re.match(r"^([A-Za-z]{3})(?:\s*[\u2013-]|$)", text)
        return m.group(1).upper() if m else ""

    def set_iata(self, code: str) -> None:
        code = (code or "").upper()
        for lab in (AirportEdit._labels or []):
            if lab.startswith(code + " "):
                self.setText(lab)
                return
        self.setText(code)

    def mark_invalid(self, invalid: bool) -> None:
        self.setProperty("invalid", invalid)
        repolish(self)


def date_edit(days_ahead: int = 14, minimum_today: bool = True) -> QDateEdit:
    d = QDateEdit(QDate.currentDate().addDays(days_ahead))
    d.setCalendarPopup(True)
    d.setDisplayFormat("yyyy-MM-dd")
    if minimum_today:
        d.setMinimumDate(QDate.currentDate())
    return d


def qdate_to_py(d: QDate):
    return d.toPython()


class FigureCard(Card):
    """Card with one Matplotlib figure, redrawn by a callback; 'Save PNG' included."""

    pointClicked = Signal(object)

    def __init__(self, title: str, min_height: int = 260, parent=None):
        super().__init__(parent, margins=(SP_LG, SP_MD, SP_LG, SP_MD), spacing=SP_SM)
        self._draw: Optional[Callable[[Figure], None]] = None
        self._pending: Optional[Callable[[Figure], None]] = None
        self._placeholder: Optional[QLabel] = None
        self._canvas: Optional[FigureCanvasQTAgg] = None
        self._min_h = min_height
        head = QHBoxLayout()
        self._title = QLabel(title)
        self._title.setObjectName("cardTitle")
        self._save = QPushButton("Save PNG")
        self._save.setObjectName("subtle")
        self._save.setIcon(icons.icon("download", P.COBALT_DARK, size=16))
        self._save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save.clicked.connect(self._save_png)
        head.addWidget(self._title, 1)
        head.addWidget(self._save)
        self.body.addLayout(head)
        self._holder = QVBoxLayout()
        self._holder.setContentsMargins(0, 0, 0, 0)
        self.body.addLayout(self._holder, 1)
        self.setMinimumHeight(min_height + 56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    @property
    def canvas(self) -> Optional[FigureCanvasQTAgg]:
        return self._canvas

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def render(self, draw: Callable[[Figure], None], has_data: bool = True) -> None:
        """Queue ``draw(fig)`` for a fresh figure; it is drawn from the event loop, one chart at a time.

        The click that opened the page therefore returns immediately; the previous chart (or a small
        placeholder) stays visible until the new one is ready. Re-rendering before the job ran replaces it.
        """
        self._draw = draw if has_data else None
        self._pending = draw
        self._save.setEnabled(has_data)
        if self._canvas is None and self._placeholder is None:
            self._placeholder = QLabel("Preparing chart\u2026")
            self._placeholder.setObjectName("muted")
            self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._placeholder.setMinimumHeight(self._min_h)
            self._holder.addWidget(self._placeholder)
        render_queue.submit(self, self.render_now)

    def render_now(self) -> None:
        """Draw the pending figure immediately (normally called by the render queue)."""
        if self._pending is None:
            return
        if not self.isVisible():              # on a page the user is not looking at: draw it when it is shown
            return
        draw, self._pending = self._pending, None
        has_data = self._draw is not None
        fig = Figure(figsize=(6.4, 3.6), facecolor=visualizations.SAVE_BG, layout="constrained")
        try:
            draw(fig)
        except Exception as exc:  # a chart bug must never crash the page
            fig = visualizations._empty_figure(f"Chart unavailable: {exc}")
        if self._canvas is not None:
            self._holder.removeWidget(self._canvas)
            self._canvas.hide()
            self._canvas.deleteLater()
        if self._placeholder is not None:
            self._holder.removeWidget(self._placeholder)
            self._placeholder.deleteLater()
            self._placeholder = None
        self._canvas = FigureCanvasQTAgg(fig)
        self._canvas.setMinimumHeight(self._min_h)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._holder.addWidget(self._canvas)
        self._save.setEnabled(has_data)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._pending is not None:
            render_queue.submit(self, self.render_now)

    def empty(self, message: str) -> None:
        def draw(fig: Figure) -> None:
            ax = fig.add_subplot(111)
            ax.axis("off")
            ax.text(0.5, 0.5, message, ha="center", va="center", wrap=True, color=visualizations.MUTED, fontsize=10,
                    transform=ax.transAxes)
        self.render(draw, has_data=False)

    def _save_png(self) -> None:
        if self._canvas is None or self._draw is None:
            return
        notify = getattr(self.window(), "notify", None)
        stem = re.sub(r"\W+", "_", self._title.text()).strip("_").lower() or "chart"
        path, _ = QFileDialog.getSaveFileName(self, "Save chart", str(config.EXPORTS_DIR / f"{stem}.png"), "PNG image (*.png)")
        if not path:
            return
        try:
            self._canvas.figure.savefig(path, dpi=150, facecolor=visualizations.SAVE_BG)
            if notify:
                notify(f"Chart saved to {path}", "success")
        except Exception as exc:
            if notify:
                notify(f"Could not save the chart: {exc}", "error")


class ExportBar(QWidget):
    """CSV / Excel / PDF export of exactly what the page currently shows.

    ``provider()`` must return ``(DataFrame, meta_dict)``; optional ``figures()``
    and ``metrics()`` callables enrich the PDF.
    """

    def __init__(self, provider: Callable[[], tuple], stem: str, figures: Optional[Callable] = None,
                 metrics: Optional[Callable] = None, pdf: bool = True, parent=None):
        super().__init__(parent)
        self._provider, self._stem, self._figures, self._metrics = provider, stem, figures, metrics
        lay = FlowLayout(self, spacing=SP_SM)
        lay.addWidget(QLabel("Export:"))
        self.buttons: Dict[str, QPushButton] = {}
        for kind in (["csv", "excel"] + (["pdf"] if pdf else [])):
            b = QPushButton({"csv": "CSV", "excel": "Excel", "pdf": "PDF report"}[kind])
            b.setObjectName("subtle")
            b.setIcon(icons.icon("download", P.COBALT_DARK, size=16))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=kind: self.export(k))
            lay.addWidget(b)
            self.buttons[kind] = b

    def export(self, kind: str, path: Optional[str] = None) -> Optional[str]:
        notify = getattr(self.window(), "notify", lambda *a, **k: None)
        df, meta = self._provider()
        if df is None or df.empty:
            notify("There is no data to export for the current filters.", "warning")
            return None
        ext = {"csv": "csv", "excel": "xlsx", "pdf": "pdf"}[kind]
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, f"Export {kind.upper()}", str(reports.default_path(self._stem, ext)),
                {"csv": "CSV (*.csv)", "excel": "Excel workbook (*.xlsx)", "pdf": "PDF (*.pdf)"}[kind])
            if not path:
                return None
        try:
            if kind == "csv":
                out = reports.export_csv(df, path, meta)
            elif kind == "excel":
                out = reports.export_excel({"Data": df}, path, meta)
            else:
                figs = self._figures() if self._figures else []
                out = reports.export_pdf(path, meta, self._metrics() if self._metrics else {}, figs, {"Data": df})
        except Exception as exc:
            notify(f"Export failed: {exc}", "error")
            return None
        notify(f"Exported {len(df):,} rows to {out}", "success")
        return str(out)
