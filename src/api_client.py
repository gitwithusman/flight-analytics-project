"""HTTP client for the AviationStack API (and optional Open-Meteo weather).

AviationStack docs: https://aviationstack.com/documentation
Free plan supports the real-time ``/v1/flights`` endpoint with ``access_key``
authentication. Lookup endpoints such as ``/v1/airports`` require a paid plan,
so the application derives airport records from flight data instead.

Open-Meteo (https://open-meteo.com) is a free, key-less weather API used only
for informational lookups at airport coordinates; it is never used to claim a
delay was caused by weather.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import threading

import requests

from . import config
from .cache import TTLCache
from .utils import (
    APIError,
    AuthenticationError,
    RateLimitError,
    get_logger,
    timestamp_for_filename,
)

logger = get_logger()

# Flight statuses the API accepts for server-side filtering.
FILTERABLE_STATUSES = (
    "scheduled",
    "active",
    "landed",
    "cancelled",
    "incident",
    "diverted",
)


def _handle_error_payload(payload: dict) -> None:
    """Raise a specific exception for AviationStack ``{"error": ...}`` bodies."""
    error = payload.get("error") if isinstance(payload, dict) else None
    if not error:
        return
    if not isinstance(error, dict):  # some gateways return a bare string
        error = {"message": str(error)}
    code = str(error.get("code", "unknown_error"))
    message = str(error.get("message", "Unknown API error"))
    logger.warning("AviationStack error %s: %s", code, message)
    if code in {
        "missing_access_key",
        "invalid_access_key",
        "not_authenticated",
        "invalid_api_key",
        "101",
    }:
        raise AuthenticationError(
            f"API authentication failed ({code}). Check AVIATIONSTACK_API_KEY in .env."
        )
    if code in {"usage_limit_reached", "rate_limit_reached", "104"} or "limit" in code:
        raise RateLimitError(
            f"API usage limit reached ({code}). Free plan allows ~100 requests/month."
        )
    if code in {
        "function_access_restricted",
        "https_access_restricted",
        "not_found",
    }:
        raise APIError(f"Endpoint not available on this plan ({code}): {message}")
    raise APIError(f"AviationStack error {code}: {message}")


# HTTP statuses that indicate a temporary server-side problem worth retrying.
_RETRYABLE_STATUS = {500, 502, 503, 504}


def _redact(text: str) -> str:
    """Remove the access key from any text that might be logged or displayed.

    ``requests`` exception messages can contain the full URL including
    ``?access_key=...``; the secret must never reach logs or the GUI.
    """
    text = re.sub(r"(access_key=)[^&\s'\")]+", r"\1***", str(text))
    key = config.AVIATIONSTACK_API_KEY
    return text.replace(key, "***") if key else text


def _sleep_before_retry(attempt: int) -> None:
    """Exponential back-off: base * 2**attempt seconds."""
    time.sleep(config.RETRY_BACKOFF_SECONDS * (2 ** attempt))


def _request(endpoint: str, params: Optional[Dict[str, Any]] = None) -> dict:
    """Perform a GET request against the AviationStack API.

    Transient failures (timeout, connection error, HTTP 5xx) are retried up to
    ``config.MAX_RETRIES`` times with exponential back-off. Credential and
    quota errors fail immediately - retrying them would only burn quota.
    """
    if not config.api_key_configured():
        raise AuthenticationError(
            "No AVIATIONSTACK_API_KEY configured. Copy .env.example to .env "
            "and add your key from https://aviationstack.com"
        )

    url = f"{config.AVIATIONSTACK_BASE_URL}/{endpoint.lstrip('/')}"
    query = {"access_key": config.AVIATIONSTACK_API_KEY}
    query.update({k: v for k, v in (params or {}).items() if v not in (None, "")})

    response = None
    last_problem = ""
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=query,
                                    timeout=(min(5, config.REQUEST_TIMEOUT), config.REQUEST_TIMEOUT))
        except requests.exceptions.Timeout:
            last_problem = f"request timed out after {config.REQUEST_TIMEOUT}s"
        except requests.exceptions.ConnectionError:
            last_problem = "could not reach aviationstack.com - check your connection"
        except requests.exceptions.RequestException as exc:
            raise APIError(f"HTTP request failed: {_redact(exc)}")
        else:
            if response.status_code not in _RETRYABLE_STATUS:
                break
            last_problem = f"server error HTTP {response.status_code}"
        if attempt < config.MAX_RETRIES:
            logger.warning("Transient API problem (%s); retry %d of %d",
                           last_problem, attempt + 1, config.MAX_RETRIES)
            _sleep_before_retry(attempt)
        else:
            raise APIError(
                f"API request failed after {config.MAX_RETRIES + 1} attempts: "
                f"{last_problem}."
            )

    # AviationStack explains failures in a JSON body even on 4xx responses
    # (e.g. 403 with {"error": {"code": ..., "message": ...}}). Read it first
    # so the user sees the real reason instead of a bare status code.
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        payload = None
    _handle_error_payload(payload)

    if response.status_code == 401:
        raise AuthenticationError("API returned 401 - the access key is invalid.")
    if response.status_code == 429:
        raise RateLimitError("API returned 429 - rate limit reached, try later.")
    if response.status_code >= 400:
        raise APIError(f"API returned HTTP {response.status_code}.")
    if payload is None:
        body = getattr(response, "content", b"") or getattr(response, "text", "")
        if not body:
            raise APIError("API returned an empty response body.")
        raise APIError("API response was not valid JSON.")
    return _check_payload_structure(payload)


def _check_payload_structure(payload: Any) -> dict:
    """Make sure a decoded body looks like a ``/v1/flights`` response."""
    if not isinstance(payload, dict) or "data" not in payload:
        raise APIError("Unexpected API response structure (missing 'data').")
    if payload["data"] is None:
        payload["data"] = []
    if not isinstance(payload["data"], list):
        raise APIError("Unexpected API response structure ('data' is not a list).")
    return payload


def fetch_flights(
    limit: int = config.DEFAULT_RECORD_LIMIT,
    offset: int = 0,
    flight_status: Optional[str] = None,
    dep_iata: Optional[str] = None,
    arr_iata: Optional[str] = None,
    airline_name: Optional[str] = None,
    flight_number: Optional[str] = None,
    save_raw: bool = True,
    flight_iata: Optional[str] = None,
) -> dict:
    """Retrieve flight records from ``/v1/flights``.

    Returns the raw decoded payload. ``save_raw`` stores a copy under
    ``data/raw/`` before any transformation takes place.
    """
    params: Dict[str, Any] = {
        "limit": min(max(1, int(limit)), config.MAX_RECORD_LIMIT),
        "offset": max(0, int(offset)),
    }
    if flight_status and flight_status.lower() in FILTERABLE_STATUSES:
        params["flight_status"] = flight_status.lower()
    if dep_iata:
        params["dep_iata"] = dep_iata.strip().upper()
    if arr_iata:
        params["arr_iata"] = arr_iata.strip().upper()
    if airline_name:
        params["airline_name"] = airline_name.strip()
    if flight_number:
        params["flight_number"] = flight_number.strip()
    if flight_iata:
        params["flight_iata"] = flight_iata.strip().upper()

    logger.info("Requesting flights (limit=%s offset=%s)", params["limit"], offset)
    payload = _request("flights", params)

    if save_raw:
        from .utils import save_json

        path = config.DATA_RAW_DIR / f"flights_raw_{timestamp_for_filename()}.json"
        save_json(payload, path)
        logger.info("Raw response saved to %s", path)
    return payload


def fetch_flights_paged(
    total: int = config.DEFAULT_RECORD_LIMIT,
    page_size: int = 100,
    max_pages: int = 5,
    **filters: Any,
) -> dict:
    """Fetch up to ``total`` records using ``offset`` pagination.

    Each page is one API request (the free plan allows roughly 100 per month),
    so ``max_pages`` caps the quota used. Stops early on a short or empty page.
    """
    page_size = max(1, min(int(page_size), config.MAX_RECORD_LIMIT))
    records: List[dict] = []
    pagination: dict = {}
    pages = 0
    while len(records) < total and pages < max_pages:
        payload = fetch_flights(
            limit=min(page_size, total - len(records)),
            offset=len(records),
            **filters,
        )
        pages += 1
        pagination = payload.get("pagination") or pagination
        batch = payload.get("data") or []
        records.extend(batch)
        if len(batch) < page_size:  # last page reached
            break
    return {"pagination": pagination, "data": records, "pages_requested": pages}


def load_raw_payload(path) -> dict:
    """Load an archived raw API response (``data/raw/*.json``) for replay.

    Lets the Transform and Load stages be re-run on real, previously
    downloaded data without spending API quota.
    """
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise APIError(f"Raw file not found: {path}")
    except (OSError, json.JSONDecodeError) as exc:
        raise APIError(f"Raw file {path.name} is not readable JSON: {exc}")
    return _check_payload_structure(payload)


def fetch_airports_endpoint(limit: int = 100) -> dict:
    """Try the ``/v1/airports`` lookup endpoint.

    AviationStack restricts this endpoint to paid plans; when unavailable the
    raised APIError is handled by the caller, which falls back to airports
    derived from flight records.
    """
    return _request("airports", {"limit": min(max(1, int(limit)), 1000)})


_WEATHER_CACHE = TTLCache(default_ttl=600.0)       # successful answers are reused for 10 minutes
_WEATHER_FAILED_TTL = 60.0                         # after a failure, do not hammer the service for a minute
_WEATHER_LOCK = threading.Lock()


def fetch_weather(latitude: float, longitude: float) -> Optional[dict]:
    """Fetch current weather from Open-Meteo for display purposes.

    Returns ``None`` on any failure - weather is informational only and must
    never block the rest of the application. Answers are cached (10 minutes,
    failures 1 minute) so opening pages and refreshing the status bar do not
    repeat identical requests.
    """
    if not config.ENABLE_WEATHER_LOOKUP:
        return None
    key = (round(float(latitude), 3), round(float(longitude), 3))
    with _WEATHER_LOCK:                              # concurrent callers share one request
        if _WEATHER_CACHE.has(key):
            return _WEATHER_CACHE.get(key)
        result = _fetch_weather_uncached(latitude, longitude)
        _WEATHER_CACHE.set(key, result, ttl=None if result is not None else _WEATHER_FAILED_TTL)
        return result


def _fetch_weather_uncached(latitude: float, longitude: float) -> Optional[dict]:
    try:
        response = requests.get(
            f"{config.OPENMETEO_BASE_URL}/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,weather_code,wind_speed_10m",
            },
            timeout=(min(4, config.REQUEST_TIMEOUT), min(10, config.REQUEST_TIMEOUT)),
        )
        if response.status_code != 200:
            return None
        current = response.json().get("current") or {}
        return {
            "temperature_c": current.get("temperature_2m"),
            "weather_code": current.get("weather_code"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
        }
    except (requests.exceptions.RequestException, ValueError):
        return None


# WMO weather interpretation codes (subset relevant to flight disruption).
WMO_SEVERE_CODES = {45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75,
                    77, 80, 81, 82, 85, 86, 95, 96, 99}


def weather_summary(weather: Optional[dict]) -> str:
    """Human-readable one-line weather description."""
    if not weather:
        return "Weather unavailable"
    temp = weather.get("temperature_c")
    wind = weather.get("wind_speed_kmh")
    parts = []
    if temp is not None:
        parts.append(f"{temp:.0f}°C")
    if wind is not None:
        parts.append(f"wind {wind:.0f} km/h")
    code = weather.get("weather_code")
    if code in WMO_SEVERE_CODES:
        parts.append("adverse conditions reported")
    return ", ".join(parts) if parts else "Weather unavailable"
