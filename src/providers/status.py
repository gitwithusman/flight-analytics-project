"""Live flight status (AviationStack ``/v1/flights?flight_iata=``).

Only a successful API response is labelled ``live_api``. If no key is set the
provider raises ``AuthenticationError``; the UI then offers the stored
snapshots, which are labelled HISTORICAL with their retrieval time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pandas as pd

from .. import api_client, config
from ..models import validate_batch
from ..timeutils import wall_clock_to_utc
from ..utils import AuthenticationError, get_logger

logger = get_logger()
SOURCE = "aviationstack"

STATUS_COLUMNS = ["observed_at", "source", "data_origin", "flight_iata", "flight_date", "airline_name",
                  "dep_iata", "arr_iata", "dep_scheduled", "dep_estimated", "dep_actual",
                  "arr_scheduled", "arr_estimated", "arr_actual", "status",
                  "dep_delay_min", "arr_delay_min", "api_updated"]


def _utc(ts, tz):
    moment = wall_clock_to_utc(ts, tz)
    return moment.isoformat() if moment else None


def records_to_status(raw_records: List[dict], observed_at: datetime) -> pd.DataFrame:
    """Validate raw records and map them to status observation rows.

    Times are converted from the API's airport-local wall-clock to UTC (see
    ``timeutils``). Records that fail validation are skipped (and logged).
    """
    report = validate_batch(raw_records)
    rows = []
    for rec in report.accepted:
        d, a = rec.departure, rec.arrival
        code = rec.flight.iata or rec.flight.icao or rec.flight.number
        rows.append({
            "observed_at": observed_at.isoformat(timespec="seconds"), "source": SOURCE,
            "data_origin": "live_api", "flight_iata": code, "flight_date": rec.flight_date,
            "airline_name": rec.airline.name, "dep_iata": d.iata, "arr_iata": a.iata,
            "dep_scheduled": _utc(d.scheduled, d.timezone), "dep_estimated": _utc(d.estimated, d.timezone),
            "dep_actual": _utc(d.actual, d.timezone), "arr_scheduled": _utc(a.scheduled, a.timezone),
            "arr_estimated": _utc(a.estimated, a.timezone), "arr_actual": _utc(a.actual, a.timezone),
            "status": rec.flight_status, "dep_delay_min": d.delay, "arr_delay_min": a.delay,
            "api_updated": rec.live.updated if rec.live else None,
        })
    if report.rejected_count:
        logger.info("Status lookup: %d record(s) rejected by validation", report.rejected_count)
    return pd.DataFrame(rows, columns=STATUS_COLUMNS)


def lookup_live_status(flight_iata: str, limit: int = 10) -> pd.DataFrame:
    """Query the API for one flight number (e.g. ``PK301``)."""
    code = (flight_iata or "").strip().upper()
    if not (3 <= len(code) <= 7 and code.isalnum()):
        raise ValueError("Enter a flight number such as PK301 (airline code + number).")
    if not config.api_key_configured():
        raise AuthenticationError("No AviationStack API key is configured (Settings > API configuration).")
    payload = api_client.fetch_flights(limit=limit, flight_iata=code, save_raw=False)
    return records_to_status(payload.get("data") or [], datetime.now(timezone.utc))


def test_connection() -> str:
    """One small request to verify the AviationStack key."""
    if not config.api_key_configured():
        raise AuthenticationError("No AviationStack API key is configured.")
    payload = api_client.fetch_flights(limit=1, save_raw=False)
    return f"AviationStack key accepted; the API answered with {len(payload.get('data') or [])} record(s)."
