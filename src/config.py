"""Configuration and environment-variable loading.

All credentials come from environment variables or a ``.env`` file at the
project root. No secret is ever hard-coded in this project.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DATABASE_DIR = PROJECT_ROOT / "database"
DATABASE_PATH = DATABASE_DIR / "flight_airport.db"
VISUALIZATIONS_DIR = PROJECT_ROOT / "visualizations"
ASSETS_DIR = PROJECT_ROOT / "assets"
LOG_DIR = PROJECT_ROOT / "outputs" / "logs"
REPORTS_DIR = PROJECT_ROOT / "outputs" / "reports"
EXPORTS_DIR = PROJECT_ROOT / "outputs" / "exports"
REFERENCE_DIR = PROJECT_ROOT / "data" / "reference"
EDA_DIR = PROJECT_ROOT / "outputs" / "eda"
EDA_FIGURES_DIR = VISUALIZATIONS_DIR / "eda"
NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"
ENV_FILE = PROJECT_ROOT / ".env"

for _directory in (
    DATA_RAW_DIR,
    DATA_PROCESSED_DIR,
    DATABASE_DIR,
    VISUALIZATIONS_DIR,
    LOG_DIR,
    REPORTS_DIR,
    EXPORTS_DIR,
    EDA_DIR,
    EDA_FIGURES_DIR,
):
    _directory.mkdir(parents=True, exist_ok=True)

# ``utf-8-sig`` strips the byte-order mark that Windows editors (Notepad,
# PowerShell redirection) add; without it the first key in the file is read
# as "\ufeffAVIATIONSTACK_API_KEY" and the API key silently looks unset.
_ENV_ENCODING = "utf-8-sig"
load_dotenv(ENV_FILE, encoding=_ENV_ENCODING)


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back on bad values."""
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _env_flag(name: str, default: str = "1") -> bool:
    """Interpret an environment variable as an on/off switch."""
    return os.getenv(name, default).strip().lower() not in {"0", "false", "no", ""}

# ---------------------------------------------------------------------------
# API settings
# ---------------------------------------------------------------------------
# AviationStack - https://aviationstack.com (free tier: /v1/flights endpoint).
AVIATIONSTACK_API_KEY = os.getenv("AVIATIONSTACK_API_KEY", "").strip()
# NOTE: the free AviationStack plan is HTTP-only; paid plans may switch
# this to https:// in .env.
AVIATIONSTACK_BASE_URL = os.getenv(
    "AVIATIONSTACK_BASE_URL", "http://api.aviationstack.com/v1"
).rstrip("/")

# FlightAPI.io - https://api.flightapi.io - the flight-search provider (API key is
# part of the URL path, e.g. https://api.flightapi.io/onewaytrip/<API_KEY>/LHR/JFK/...).
# Where the user obtains the key (a page, not a secret):
FLIGHTAPI_DASHBOARD_URL = "https://api.flightapi.io/dashboard/6ad75eabbbcc751a757be3a9"
FLIGHTAPI_API_KEY = os.getenv("FLIGHTAPI_API_KEY", "").strip()
FLIGHTAPI_BASE_URL = os.getenv(
    "FLIGHTAPI_BASE_URL", "https://api.flightapi.io"
).rstrip("/")

# Open-Meteo - free weather API, no key required. Used only for optional
# informational weather lookups; it is never used to attribute delays.
OPENMETEO_BASE_URL = os.getenv(
    "OPENMETEO_BASE_URL", "https://api.open-meteo.com/v1"
).rstrip("/")
ENABLE_WEATHER_LOOKUP = _env_flag("ENABLE_WEATHER_LOOKUP")
# Optional coordinates of a location the user wants weather context for
# (e.g. a home airport). Open-Meteo is queried only when both are set.
WEATHER_LATITUDE = os.getenv("WEATHER_LATITUDE", "").strip()
WEATHER_LONGITUDE = os.getenv("WEATHER_LONGITUDE", "").strip()
WEATHER_LABEL = os.getenv("WEATHER_LABEL", "Monitored location").strip()

# Turn off the animated background / page transitions (accessibility, slow machines, tests).
REDUCE_MOTION = _env_flag("REDUCE_MOTION", "0")
# Force the labelled SAMPLE-data flight-search provider even when a FlightAPI key is configured.
SEARCH_FORCE_DEMO = _env_flag("SEARCH_FORCE_DEMO", "0")

# Request behaviour
REQUEST_TIMEOUT = _env_int("REQUEST_TIMEOUT", 20)
DEFAULT_RECORD_LIMIT = _env_int("DEFAULT_RECORD_LIMIT", 100)
MAX_RECORD_LIMIT = 1000  # aviationstack caps the "limit" parameter
# Transient failures (timeouts, connection resets, HTTP 5xx) are retried with
# exponential back-off; authentication / quota errors are never retried.
MAX_RETRIES = _env_int("MAX_RETRIES", 3)
RETRY_BACKOFF_SECONDS = _env_int("RETRY_BACKOFF_SECONDS", 2)


def api_key_configured() -> bool:
    """Return True when an AviationStack access key is present."""
    return bool(AVIATIONSTACK_API_KEY)


def masked_api_key() -> str:
    """Return the API key masked for display (never shows the full secret)."""
    key = AVIATIONSTACK_API_KEY
    if not key:
        return "(not set)"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


def flightapi_configured() -> bool:
    """True when a FlightAPI.io key is present."""
    return bool(FLIGHTAPI_API_KEY)


def mask_secret(value: str) -> str:
    """Mask any secret for display (first/last 4 characters only)."""
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def secret_values() -> list:
    """Every configured secret - used to scrub logs and error messages."""
    return [v for v in (AVIATIONSTACK_API_KEY, FLIGHTAPI_API_KEY) if v]


def search_mode() -> str:
    """Which flight-search source the app uses right now.

    ``"live_api"`` - FlightAPI key configured and demo not forced.
    ``"sample"``   - no key (or demo forced): clearly labelled sample data.
    """
    return "live_api" if flightapi_configured() and not SEARCH_FORCE_DEMO else "sample"


def reload_environment() -> None:
    """Reload .env values - used after the Settings page updates the file."""
    global AVIATIONSTACK_API_KEY, WEATHER_LATITUDE, WEATHER_LONGITUDE
    global WEATHER_LABEL, ENABLE_WEATHER_LOOKUP
    global SEARCH_FORCE_DEMO, FLIGHTAPI_API_KEY, FLIGHTAPI_BASE_URL, REDUCE_MOTION
    load_dotenv(ENV_FILE, override=True, encoding=_ENV_ENCODING)
    SEARCH_FORCE_DEMO = _env_flag("SEARCH_FORCE_DEMO", "0")
    REDUCE_MOTION = _env_flag("REDUCE_MOTION", "0")
    AVIATIONSTACK_API_KEY = os.getenv("AVIATIONSTACK_API_KEY", "").strip()
    FLIGHTAPI_API_KEY = os.getenv("FLIGHTAPI_API_KEY", "").strip()
    FLIGHTAPI_BASE_URL = os.getenv("FLIGHTAPI_BASE_URL", "https://api.flightapi.io").rstrip("/")
    WEATHER_LATITUDE = os.getenv("WEATHER_LATITUDE", "").strip()
    WEATHER_LONGITUDE = os.getenv("WEATHER_LONGITUDE", "").strip()
    WEATHER_LABEL = os.getenv("WEATHER_LABEL", "Monitored location").strip()
    ENABLE_WEATHER_LOOKUP = _env_flag("ENABLE_WEATHER_LOOKUP")


def _format_env_value(value: object) -> str:
    """Render a value for a .env line, quoting only when necessary."""
    text = "" if value is None else str(value)
    if "\n" in text or "\r" in text:
        raise ValueError("Values stored in .env cannot contain line breaks.")
    if text != text.strip() or any(ch in text for ch in ('#', '"', "'", "=")):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def update_env_file(values: dict) -> None:
    """Create or update ``.env`` with the given key/value pairs.

    Existing keys are replaced in place; unknown keys are appended. Lines
    that are comments or unrelated keys are preserved. A value of ``None``
    clears the key (it is kept in the file with an empty value). The file
    is always written as plain UTF-8 without a byte-order mark.
    """
    lines = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding=_ENV_ENCODING).splitlines()

    remaining = dict(values)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            lines[i] = f"{key}={_format_env_value(remaining.pop(key))}"
    for key, value in remaining.items():
        lines.append(f"{key}={_format_env_value(value)}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def data_source_status() -> dict:
    """Summarise configuration status for display in both front-ends."""
    return {
        "provider": "AviationStack",
        "api_key_configured": api_key_configured(),
        "api_key_display": masked_api_key(),
        "base_url": AVIATIONSTACK_BASE_URL,
        "flightapi_key_configured": flightapi_configured(),
        "flightapi_key_display": mask_secret(FLIGHTAPI_API_KEY),
        "flightapi_base_url": FLIGHTAPI_BASE_URL,
        "weather_provider": "Open-Meteo" if ENABLE_WEATHER_LOOKUP else "disabled",
        "search_provider": "FlightAPI" if flightapi_configured() else "none (sample data)",
        "search_mode": search_mode(),
        "request_timeout": REQUEST_TIMEOUT,
        "default_limit": DEFAULT_RECORD_LIMIT,
        "database_path": str(DATABASE_PATH),
    }
