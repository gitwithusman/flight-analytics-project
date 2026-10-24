"""Timezone handling for AviationStack timestamps.

Empirical finding (verified on the archived real responses, see the project
report): the ``scheduled`` / ``estimated`` / ``actual`` fields of a flight are
**airport-local wall-clock times that carry a spurious ``+00:00`` offset**.
Evidence: ``live.updated`` (a genuine UTC timestamp) precedes the recorded
departure by 7-9 hours when the suffix is believed, but follows it by 18-48
minutes when the wall-clock value is interpreted in the departure airport's own
timezone - for all 11 flights that carry both values.

Reading the suffix literally therefore corrupts every duration that crosses
timezones (e.g. DOH->CMB appears as 435 min instead of ~285 min). The helpers
below discard the offset, attach the airport's real timezone and convert to
true UTC.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_FIXED_OFFSET = re.compile(r"^(?:UTC|GMT)?\s*([+-])(\d{1,2})(?::?(\d{2}))?$", re.I)


def resolve_timezone(name: Optional[str]) -> Optional[tzinfo]:
    """Return a tzinfo for an IANA name or a fixed offset such as ``"+8"``.

    Returns ``None`` when the value is missing or not understood.
    """
    if name is None:
        return None
    text = str(name).strip()
    if not text:
        return None
    if text.upper() in {"UTC", "GMT", "Z"}:
        return timezone.utc
    match = _FIXED_OFFSET.match(text)
    if match:
        sign = -1 if match.group(1) == "-" else 1
        delta = timedelta(hours=int(match.group(2)), minutes=int(match.group(3) or 0))
        if delta <= timedelta(hours=14):
            return timezone(sign * delta)
        return None
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def parse_wall_clock(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO timestamp and drop whatever offset it carries."""
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def wall_clock_to_utc(value: Optional[str], tz_name: Optional[str]) -> Optional[datetime]:
    """Interpret ``value`` as local time in ``tz_name`` and return aware UTC.

    ``None`` is returned when the timestamp is missing/unparseable or the
    timezone cannot be resolved - the caller decides how to treat that.
    """
    naive = parse_wall_clock(value)
    tz = resolve_timezone(tz_name)
    if naive is None or tz is None:
        return None
    return naive.replace(tzinfo=tz).astimezone(timezone.utc)
