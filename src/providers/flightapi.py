"""FlightAPI.io flight-search client (https://api.flightapi.io).

Documentation: https://www.flightapi.io/documentation/oneway-trip-api/ and
``.../round-trip-api/``. The API key is part of the URL **path**::

    /onewaytrip/<key>/<from>/<to>/<date>/<adults>/<children>/<infants>/<cabin>/<currency>
    /roundtrip/<key>/<from>/<to>/<date>/<return>/<adults>/<children>/<infants>/<cabin>/<currency>

Design notes
* The key lives only in ``.env`` / the environment and in the request URL. It is
  masked in every error message (``providers.http.scrub``) and never logged.
* Only the itinerary facts (airline, flight number, times, stops, duration) are
  read from the response. The API's pricing blocks are ignored: the application
  has no fare feature. Each request costs 2 FlightAPI credits.
* The API's URL requires a currency segment; a fixed placeholder is sent and
  nothing derived from it is stored or shown.
* Booking deep links returned by the API are relative, host-unverified paths,
  so no booking link is stored (the app never invents or opens unverified URLs).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from .. import config
from ..timeutils import resolve_timezone
from ..utils import APIError, AuthenticationError, get_logger
from .base import FlightFetchResult, FlightQuery
from .http import get_json

logger = get_logger()
SOURCE = "flightapi"
CABIN_PARAM = {"economy": "Economy", "premium_economy": "Premium_Economy",
               "business": "Business", "first": "First"}
HTTP_HINTS = {
    402: "FlightAPI reports no credits left on this key. Top up or check your plan at the FlightAPI dashboard.",
    404: "FlightAPI could not find this endpoint or route. Check the airport codes and dates.",
    410: "FlightAPI has no flights for this route and date.",
}
FIX_KEY_HELP = ("To fix: open Settings > FlightAPI, click 'Get API key' to open your FlightAPI dashboard, "
                "copy the key, paste it and press Save API Key.")
URL_CURRENCY = "USD"   # required URL segment of the API; prices are never read
_AUTH_WORDS = ("api key", "api_key", "apikey", "unauthor", "invalid key", "authenticat", "forbidden")


def build_url(key: str, q: FlightQuery, base_url: Optional[str] = None) -> str:
    """The request URL for one search. Contains the key - never log it."""
    base = (base_url or config.FLIGHTAPI_BASE_URL).rstrip("/")
    parts = [quote(str(key), safe="")]
    parts += [q.origin, q.destination, q.departure_date.isoformat()]
    if q.return_date:
        parts.append(q.return_date.isoformat())
    parts += ["1", "0", "0", CABIN_PARAM.get(q.cabin, "Economy"), URL_CURRENCY]
    return f"{base}/{'roundtrip' if q.return_date else 'onewaytrip'}/" + "/".join(parts)


def _by_id(items: Any) -> Dict[Any, dict]:
    return {i.get("id"): i for i in items or [] if isinstance(i, dict) and i.get("id") is not None}


def _code(entity: Optional[dict], *names: str, pattern_len: int) -> Optional[str]:
    for name in names:
        value = (entity or {}).get(name)
        if isinstance(value, str) and len(value.strip()) == pattern_len and value.strip().isalnum():
            return value.strip().upper()
    return None


def _iso(value: Any, tz) -> Optional[str]:
    """Local wall-clock text -> ISO string (UTC when the airport timezone is known)."""
    if not value or not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
    if tz is not None:
        return moment.replace(tzinfo=tz).astimezone(timezone.utc).isoformat()
    return moment.isoformat()


def _error_text(payload: dict) -> Optional[str]:
    for field in ("message", "error", "detail"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_response(payload: Any, q: FlightQuery, retrieved_at: datetime) -> FlightFetchResult:
    """Normalise a FlightAPI one-way / round-trip payload (raises APIError if malformed)."""
    if not isinstance(payload, dict):
        raise APIError("FlightAPI returned an unexpected response structure.")
    if "itineraries" not in payload:
        text = _error_text(payload)
        if text:
            if any(w in text.lower() for w in _AUTH_WORDS):
                raise AuthenticationError(f"FlightAPI rejected the API key: {text}")
            raise APIError(f"FlightAPI error: {text}")
        raise APIError("FlightAPI returned an unexpected response (no 'itineraries' field).")
    itineraries = payload.get("itineraries") or []
    if not isinstance(itineraries, list):
        raise APIError("FlightAPI returned 'itineraries' in an unexpected format.")

    legs, segments = _by_id(payload.get("legs")), _by_id(payload.get("segments"))
    carriers, places = _by_id(payload.get("carriers")), _by_id(payload.get("places"))
    tz_missing = False
    offers: List[dict] = []
    for itin in itineraries:
        if not isinstance(itin, dict):
            continue
        leg_list = [legs.get(i) for i in itin.get("leg_ids") or []]
        if not leg_list or not isinstance(leg_list[0], dict):
            continue
        out = leg_list[0]
        out_segments = [segments.get(i) or {} for i in out.get("segment_ids") or []]
        carrier = carriers.get(out_segments[0].get("marketing_carrier_id")) if out_segments else None
        carrier_code = _code(carrier, "display_code", "iata", "alt_id", "code", pattern_len=2)
        number = str(out_segments[0].get("marketing_flight_number") or "").strip() if out_segments else ""
        o_place, d_place = places.get(out.get("origin_place_id")), places.get(out.get("destination_place_id"))
        o_tz = resolve_timezone((o_place or {}).get("timezone"))
        r_tz = resolve_timezone((places.get(leg_list[1].get("origin_place_id")) or {}).get("timezone")) \
            if len(leg_list) > 1 and isinstance(leg_list[1], dict) else None
        tz_missing = tz_missing or o_tz is None
        stops = out.get("stop_count")
        offers.append({
            "origin_iata": _code(o_place, "display_code", "iata", "code", pattern_len=3) or q.origin,
            "destination_iata": _code(d_place, "display_code", "iata", "code", pattern_len=3) or q.destination,
            "departure_at": _iso(out.get("departure"), o_tz),
            "return_at": _iso(leg_list[1].get("departure"), r_tz) if len(leg_list) > 1 and isinstance(leg_list[1], dict) else None,
            "airline_iata": carrier_code,
            "flight_number": f"{carrier_code}{number}" if carrier_code and number else (number or None),
            "stops": stops if isinstance(stops, int) else None,
            "duration_min": out.get("duration") if isinstance(out.get("duration"), int) else None,
            "cabin": q.cabin,
            "booking_url": None,
            "source": SOURCE,
            "data_origin": "live_api",
        })
    offers.sort(key=lambda o: (o["departure_at"] or "", o["flight_number"] or ""))
    notes = ["Flight options come from FlightAPI.io; confirm schedules and availability with the airline or agent "
             "before booking.",
             "Baggage is not provided by this data source; no booking link is stored."]
    if tz_missing:
        notes.append("FlightAPI gives airport-local times without a timezone, so times are shown as supplied and are "
                     "not converted to UTC.")
    if not offers:
        notes.append("FlightAPI returned no flights for this route and date.")
    if q.direct_only:
        offers = [o for o in offers if o["stops"] == 0]
    return FlightFetchResult(options=offers[:q.max_results], source=SOURCE, data_origin="live_api",
                             retrieved_at=retrieved_at, notes=notes, raw_count=len(itineraries))


class FlightApiProvider:
    """Fetch flight options for a validated :class:`FlightQuery`."""

    name = "FlightAPI.io"
    data_origin = "live_api"

    def __init__(self, key: Optional[str] = None, base_url: Optional[str] = None):
        self._key = key if key is not None else config.FLIGHTAPI_API_KEY
        self._base = (base_url or config.FLIGHTAPI_BASE_URL).rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def search(self, q: FlightQuery) -> FlightFetchResult:
        if not self.configured:
            raise AuthenticationError(
                "No FlightAPI key is configured. Open Settings > FlightAPI, click 'Get API key' to copy it from "
                "your FlightAPI dashboard, paste it and press Save API Key.")
        try:
            payload = get_json(build_url(self._key, q, self._base), provider="FlightAPI",
                               status_hints=HTTP_HINTS, retries=min(config.MAX_RETRIES, 1))
            result = parse_response(payload, q, datetime.now(timezone.utc))
        except AuthenticationError as exc:
            raise AuthenticationError(f"{exc} {FIX_KEY_HELP}") from None
        result.raw = payload
        return result


def test_connection() -> str:
    """One small request to verify the key (Settings > Test FlightAPI connection)."""
    from datetime import date, timedelta
    from .base import validate_query
    if not config.flightapi_configured():
        raise AuthenticationError("No FlightAPI key is configured. Paste it in Settings > FlightAPI and press Save API Key.")
    q = validate_query(FlightQuery("LHR", "JFK", date.today() + timedelta(days=45), max_results=1))
    res = FlightApiProvider().search(q)
    return (f"FlightAPI key accepted. The test query LHR-JFK returned {res.raw_count} itinerary(ies) "
            "(this test uses 2 FlightAPI credits).")
