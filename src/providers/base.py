"""Shared types for the provider layer (flight search, flight status, weather)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

# How every search / status row is labelled in the UI and in exports.
DATA_ORIGIN_LABELS: Dict[str, str] = {
    "live_api": "LIVE",
    "historical": "HISTORICAL",
    "sample": "SAMPLE DATA",
}

CABINS = ("economy", "premium_economy", "business", "first")


class FlightQueryError(ValueError):
    """The user's search input is invalid (message is shown to the user)."""


@dataclass
class FlightQuery:
    """A flight search request (route, dates, passengers, cabin)."""

    origin: str
    destination: str
    departure_date: date
    return_date: Optional[date] = None
    adults: int = 1
    cabin: str = "economy"
    direct_only: bool = False
    max_results: int = 30


@dataclass
class FlightFetchResult:
    """Raw-but-normalised flight options returned by a flight-search provider."""

    options: List[dict]
    source: str
    data_origin: str  # 'live_api' | 'sample'
    retrieved_at: datetime
    notes: List[str] = field(default_factory=list)
    raw_count: int = 0
    raw: Any = None   # untouched provider payload (archived for real sources)


def validate_query(q: FlightQuery, today: Optional[date] = None,
                   known_iata: Optional[set] = None) -> FlightQuery:
    """Validate and normalise a search (raises :class:`FlightQueryError`)."""
    today = today or date.today()
    q.origin = (q.origin or "").strip().upper()
    q.destination = (q.destination or "").strip().upper()
    q.cabin = (q.cabin or "economy").strip().lower().replace(" ", "_")
    for label, code in (("Origin", q.origin), ("Destination", q.destination)):
        if not code:
            raise FlightQueryError(f"{label} airport is required.")
        if len(code) != 3 or not code.isalpha():
            raise FlightQueryError(f"{label} must be a 3-letter IATA airport code (e.g. LHE).")
        if known_iata is not None and code not in known_iata:
            raise FlightQueryError(f"{label} code {code} is not in the airport reference data.")
    if q.origin == q.destination:
        raise FlightQueryError("Origin and destination must be different airports.")
    if not isinstance(q.departure_date, date):
        raise FlightQueryError("A valid departure date is required.")
    if q.departure_date < today:
        raise FlightQueryError("The departure date cannot be in the past.")
    if q.departure_date > today + timedelta(days=365):
        raise FlightQueryError("The departure date is more than a year ahead; schedules are not published that far out.")
    if q.return_date is not None:
        if q.return_date < q.departure_date:
            raise FlightQueryError("The return date cannot be before the departure date.")
    if not 1 <= int(q.adults) <= 9:
        raise FlightQueryError("Passengers must be between 1 and 9.")
    q.adults = int(q.adults)
    if q.cabin not in CABINS:
        raise FlightQueryError(f"Cabin class must be one of: {', '.join(CABINS)}.")
    q.max_results = max(1, min(int(q.max_results), 100))
    return q
