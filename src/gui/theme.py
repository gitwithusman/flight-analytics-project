"""Application stylesheet built from the shared design tokens."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QWidget

from src import palette as P

FONT_STACK = ('"Inter", "Segoe UI Variable Display", "Segoe UI", "SF Pro Display", "Helvetica Neue", '
              '"Noto Sans", "Liberation Sans", Arial, sans-serif')

# Spacing scale (px) - every margin/gap in the GUI comes from this set.
SP_XS, SP_SM, SP_MD, SP_LG, SP_XL = 4, 8, 12, 16, 24
RADIUS = 10

# Per-section identity: (accent colour, hero scene, icon). Every feature area looks distinct.
SECTION_STYLE = {
    "overview": ("#1F5FBF", "noon", "overview"),
    "search": ("#0E8F9C", "dawn", "search"),
    "delays": ("#C48A1B", "dusk", "delays"),
    "airport_analytics": ("#6B4FA3", "night", "airports"),
    "airlines": ("#C2412D", "dusk", "flights"),
    "map": ("#1B7F4E", "noon", "map"),
    "weather": ("#4A7FB5", "storm", "weather"),
    "flight_analytics": ("#2B4C8C", "noon", "flights"),
    "explorer": ("#0E8F9C", "day", "explorer"),
    "etl": ("#4F5BD5", "night", "etl"),
    "reports": ("#B7791F", "dawn", "report"),
    "data": ("#1B7F4E", "night", "data"),
    "settings": ("#566274", "storm", "settings"),
    "about": ("#1F5FBF", "dawn", "about"),
}


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def build_stylesheet() -> str:
    check = Path(__file__).with_name("check.svg").as_posix()
    chevron = Path(__file__).with_name("chevron.svg").as_posix()
    nav_accents = "\n".join(
        f'QPushButton#nav[navkey="{k}"]:checked {{ border-left: 3px solid {v[0]}; }}' for k, v in SECTION_STYLE.items())
    return f"""
* {{
    font-family: {FONT_STACK};
    font-size: 13px;
    color: {P.TEXT};
    outline: none;
}}
QMainWindow, QWidget#appRoot {{ background: {P.NAVY}; }}
QWidget#pageRoot, QWidget#scrollInner, QWidget#scrollViewport,
QStackedWidget#pageStack {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}

/* ---------- sidebar ---------- */
QFrame#sidebar {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #0E2D56, stop:0.55 #0B2545, stop:1 #07162B); border: none; }}
QLabel#brand {{ color: #ffffff; font-size: 17px; font-weight: 700; }}
QLabel#brandSub {{ color: {P.TEXT_ON_DARK_MUTED}; font-size: 12px; }}
QLabel#navSection {{
    color: #8DA0BC; font-size: 11px; font-weight: 600;
    letter-spacing: 1px; padding: 14px 20px 4px 20px;
}}
QPushButton#nav {{
    background: transparent; border: none; border-left: 3px solid transparent;
    border-radius: 0; color: {P.TEXT_ON_DARK_MUTED}; text-align: left;
    padding: 9px 16px 9px 17px; font-weight: 500;
}}
QPushButton#nav:hover {{ background: rgba(255,255,255,20); color: #ffffff; }}
QPushButton#nav:focus {{ background: rgba(255,255,255,26); color: #ffffff; }}
QPushButton#nav:checked {{
    background: rgba(255,255,255,30); color: #ffffff;
    border-left: 3px solid #4FD1DC; font-weight: 600;
}}
{nav_accents}
QFrame#sidebar QLabel#navFoot {{ color: #8DA0BC; font-size: 11px; padding: 0 20px; }}

/* ---------- top bar ---------- */
QFrame#topbar {{ background: rgba(255,255,255,222); border-bottom: 1px solid rgba(194,203,216,160); }}
QLabel#pageTitle {{ font-size: 16px; font-weight: 700; color: {P.TEXT}; }}
QLabel#heroTitle {{ color: #FFFFFF; font-size: 28px; font-weight: 800; background: transparent; }}
QLabel#heroSubtitle {{ color: rgba(255,255,255,225); font-size: 13px; background: transparent; }}
QLabel#tileTitle {{ font-size: 14px; font-weight: 700; color: {P.TEXT}; }}
QLabel#pageSubtitle {{ color: {P.TEXT_MUTED}; font-size: 12px; }}
QLabel#updated {{ color: {P.TEXT_MUTED}; font-size: 12px; }}

/* ---------- cards ---------- */
QLabel#cardTitle {{ font-size: 14px; font-weight: 600; color: {P.TEXT}; }}
QLabel#cardNote, QLabel#muted {{ color: {P.TEXT_MUTED}; font-size: 12px; }}
QLabel#kpiLabel {{ color: {P.TEXT_MUTED}; font-size: 12px; font-weight: 600; }}
QLabel#kpiValue {{ color: {P.TEXT}; font-size: 24px; font-weight: 700; }}
QLabel#kpiNote {{ color: {P.TEXT_MUTED}; font-size: 12px; }}
QFrame#kpiBar {{ border: none; border-radius: 2px; min-width: 4px; max-width: 4px; }}
QLabel#emptyTitle {{ font-size: 16px; font-weight: 600; }}
QLabel#emptyBody {{ color: {P.TEXT_MUTED}; font-size: 13px; }}
QLabel#mono {{ font-family: "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace;
    font-size: 12px; color: {P.TEXT}; }}
QFrame#rowItem {{ background: transparent; border: none; border-top: 1px solid {P.BORDER}; }}
QPushButton#nav[compact="true"] {{ text-align: center; padding: 11px 0 11px 0; }}
QLabel#formLabel {{ color: {P.TEXT_MUTED}; font-size: 12px; font-weight: 600; }}

/* ---------- notification banner ---------- */
QFrame#banner {{ border-radius: 6px; border: 1px solid {P.BORDER}; background: {P.NEUTRAL_BG}; }}
QFrame#banner[kind="success"] {{ background: {P.SUCCESS_BG}; border-color: #B7DEC9; }}
QFrame#banner[kind="error"]   {{ background: {P.ERROR_BG};   border-color: #F1B9B3; }}
QFrame#banner[kind="warning"] {{ background: {P.WARNING_BG}; border-color: #EBCB93; }}
QFrame#banner[kind="info"]    {{ background: {P.INFO_BG};    border-color: #B9CDEE; }}
QLabel#bannerText {{ font-size: 13px; }}
QPushButton#bannerClose {{ border: none; background: transparent; padding: 2px; border-radius: 4px; min-width: 22px; }}
QPushButton#bannerClose:hover {{ background: rgba(0,0,0,18); }}

/* ---------- inputs ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {P.SURFACE}; border: 1px solid {P.BORDER_STRONG};
    border-radius: 6px; padding: 6px 10px; min-height: 20px;
    selection-background-color: {P.COBALT}; selection-color: #ffffff;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: #9AA8BC; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 2px solid {P.COBALT}; padding: 5px 9px;
}}
QLineEdit[invalid="true"] {{ border: 2px solid {P.ERROR}; padding: 5px 9px; }}
QLineEdit:disabled, QComboBox:disabled {{ background: {P.NEUTRAL_BG}; color: {P.TEXT_MUTED}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {P.SURFACE}; border: 1px solid {P.BORDER_STRONG};
    selection-background-color: {P.COBALT_TINT}; selection-color: {P.TEXT};
    padding: 4px; outline: none;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {P.BORDER_STRONG}; background: {P.SURFACE};
}}
QCheckBox::indicator:checked {{ background: {P.COBALT}; border-color: {P.COBALT}; image: url({check}); }}
QCheckBox:focus {{ color: {P.COBALT_DARK}; }}

/* ---------- buttons ---------- */
QPushButton {{
    background: {P.SURFACE}; border: 1px solid {P.BORDER_STRONG};
    border-radius: 8px; padding: 7px 14px; font-weight: 600; color: {P.TEXT};
}}
QPushButton:hover {{ background: {P.SURFACE_ALT}; border-color: #9AA8BC; }}
QPushButton:pressed {{ background: {P.NEUTRAL_BG}; }}
QPushButton:focus {{ border: 2px solid {P.COBALT}; padding: 6px 13px; }}
QPushButton:disabled {{ color: #8A94A3; background: {P.NEUTRAL_BG}; border-color: {P.BORDER}; }}
QPushButton#primary {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #2D70D8, stop:1 {P.COBALT}); border: 1px solid {P.COBALT_DARK}; color: #ffffff; }}
QPushButton#primary:hover {{ background: {P.COBALT_DARK}; border-color: {P.COBALT_DARK}; }}
QPushButton#primary:focus {{ border: 2px solid {P.NAVY}; padding: 6px 13px; }}
QPushButton#primary:disabled {{ background: #9DB5DD; border-color: #9DB5DD; color: #ffffff; }}
QPushButton#subtle {{ background: transparent; border: 1px solid transparent; color: {P.COBALT_DARK}; padding: 4px 8px; }}
QPushButton#subtle:hover {{ background: {P.COBALT_TINT}; }}

/* ---------- tables ---------- */
QTableView {{
    background: {P.SURFACE}; alternate-background-color: {P.SURFACE_ALT};
    border: 1px solid {P.BORDER}; border-radius: 6px; gridline-color: {P.BORDER};
    selection-background-color: {P.COBALT_TINT}; selection-color: {P.TEXT};
}}
QTableView::item {{ padding: 2px 8px; }}
QTableView:focus {{ border: 1px solid {P.COBALT}; }}
QHeaderView {{ background: {P.SURFACE_ALT}; }}
QHeaderView::section {{
    background: {P.SURFACE_ALT}; color: {P.TEXT_MUTED}; border: none;
    border-bottom: 1px solid {P.BORDER}; border-right: 1px solid {P.BORDER};
    padding: 8px 8px; font-size: 12px; font-weight: 600;
}}
QAbstractScrollArea::corner {{ background: transparent; border: none; }}
QTableCornerButton::section {{ background: {P.SURFACE_ALT}; border: none; }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #C2CBD8; border-radius: 4px; min-height: 32px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: #9AA8BC; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #C2CBD8; border-radius: 4px; min-width: 32px; margin: 2px 0; }}
QScrollBar::handle:horizontal:hover {{ background: #9AA8BC; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- status bar ---------- */
QFrame#statusBar {{ background: rgba(255,255,255,235); border-top: 1px solid rgba(194,203,216,160); }}
QLabel#chip {{ font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 10px;
    border: 1px solid {P.BORDER}; background: {P.NEUTRAL_BG}; }}
QLabel#statusMsg {{ color: {P.TEXT_MUTED}; font-size: 12px; }}

QProgressBar#busy {{ background: transparent; border: none; max-height: 3px; min-height: 3px; }}
QProgressBar#busy::chunk {{ background: {P.COBALT}; }}

QToolTip {{
    background: {P.NAVY}; color: #ffffff; border: none; padding: 5px 8px;
}}
QMessageBox {{ background: {P.SURFACE}; }}
"""
