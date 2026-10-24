"""Shared helper functions, logging and application error types."""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import config

# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class AppError(Exception):
    """Base class for application-level errors shown to the user."""


class APIError(AppError):
    """Raised when the remote API request fails or returns an error payload."""


class AuthenticationError(APIError):
    """Raised when the API rejects the configured credentials."""


class RateLimitError(APIError):
    """Raised when the API reports that the usage quota is exhausted."""


class ValidationFailedError(AppError):
    """Raised when no records survive Pydantic validation."""


class DatabaseError(AppError):
    """Raised for SQLite-level failures."""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOGGER_NAME = "flight_airport_analytics"


def get_logger() -> logging.Logger:
    """Return a configured application logger (console + rotating file)."""
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_file = config.LOG_DIR / "application.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    console.setLevel(logging.WARNING)
    logger.addHandler(console)
    return logger


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    """Current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def timestamp_for_filename() -> str:
    """Compact timestamp safe for use in file names."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_str(value: Any, default: str = "-") -> str:
    """Convert a value to display text, using ``default`` for blanks/None."""
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def format_number(value: Any) -> str:
    """Format integers with thousands separators for display."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return safe_str(value)


def save_json(payload: Any, path: Path) -> Path:
    """Write JSON to ``path`` (UTF-8, indented) and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
    return path


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def truncate(text: Optional[str], width: int = 40) -> str:
    text = safe_str(text)
    return text if len(text) <= width else text[: width - 1] + "…"
