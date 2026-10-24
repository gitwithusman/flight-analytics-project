"""Design tokens shared by the desktop GUI, the Matplotlib charts and the
status colours used in analytics.

Keeping the palette in one dependency-free module guarantees that a colour
means the same thing everywhere (tables, chips, charts, saved PNG files).
"""

from __future__ import annotations

# --- Brand -----------------------------------------------------------------
NAVY = "#0B2545"          # sidebar, deepest brand colour
NAVY_SOFT = "#13315C"
COBALT = "#1F5FBF"        # primary actions, links, focus
COBALT_DARK = "#184C99"   # primary hover / pressed
COBALT_TINT = "#E7EFFB"   # selected rows, soft highlights
TEAL = "#0E8F9C"          # secondary accent

# --- Surfaces and lines ----------------------------------------------------
BACKGROUND = "#F3F5F8"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F7F9FC"
BORDER = "#DCE2EA"
BORDER_STRONG = "#C2CBD8"

# --- Text ------------------------------------------------------------------
TEXT = "#1F2937"          # charcoal
TEXT_MUTED = "#566274"    # secondary text (>= 4.5:1 on white and background)
TEXT_ON_DARK = "#F1F5FA"
TEXT_ON_DARK_MUTED = "#AEBBD0"

# --- Semantic states (text colour, tinted background) ----------------------
SUCCESS = "#1B7F4E"
SUCCESS_BG = "#E6F4EC"
WARNING = "#9A5B00"
WARNING_BG = "#FDF1DD"
ERROR = "#B42318"
ERROR_BG = "#FCE8E6"
INFO = COBALT
INFO_BG = COBALT_TINT
NEUTRAL_BG = "#EDF0F4"
WEATHER = "#6B4FA3"
WEATHER_BG = "#F0EBF8"

# --- Chart series ----------------------------------------------------------
SERIES = [COBALT, TEAL, NAVY_SOFT, "#6F86A8", "#C48A1B", "#B8483D"]

STATUS_COLORS = {
    "scheduled": COBALT,
    "active": TEAL,
    "landed": NAVY_SOFT,
    "cancelled": "#B8483D",
    "incident": "#C48A1B",
    "diverted": "#6F86A8",
}
