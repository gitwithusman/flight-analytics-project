"""Pydantic validation models for the flight ETL pipeline.

Two validation gates are defined here:

1. **Extract gate** - :class:`FlightRecord` validates every raw record of the
   AviationStack ``/v1/flights`` response (field types, code formats, ranges,
   status vocabulary, timestamp formats and cross-field consistency).
2. **Transform gate** - :class:`FlightRow` validates every *flattened* row that
   pandas produced, immediately before it is loaded into SQLite.

Fields that the API commonly returns as ``null`` are Optional. Records that
break a rule are never silently repaired: they are collected in a
:class:`ValidationReport` (field-level errors + the offending raw payload) so
the pipeline can count, persist and display exactly what was rejected and why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .timeutils import parse_wall_clock, wall_clock_to_utc

# Code formats observed in (and documented for) the AviationStack payload.
_IATA_AIRPORT = re.compile(r"^[A-Z0-9]{3}$")
_ICAO_AIRPORT = re.compile(r"^[A-Z0-9]{4}$")
_IATA_AIRLINE = re.compile(r"^[A-Z0-9]{2}$")
# Largest delay (minutes) accepted as plausible: 48 hours.
MAX_PLAUSIBLE_DELAY_MIN = 2880

# Statuses documented by AviationStack.
VALID_FLIGHT_STATUSES = {
    "scheduled",
    "active",
    "landed",
    "cancelled",
    "incident",
    "diverted",
}


def _validate_iso_timestamp(value: Optional[str]) -> Optional[str]:
    """Return ``value`` unchanged if it is a valid ISO-8601 timestamp."""
    if value is None or value == "":
        return None
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"timestamp {value!r} is not ISO-8601")
    return value


class AirportPointInfo(BaseModel):
    """Departure or arrival block inside a flight record."""

    model_config = ConfigDict(extra="ignore")

    airport: Optional[str] = Field(default=None, max_length=200)
    timezone: Optional[str] = Field(default=None, max_length=60)
    iata: Optional[str] = None   # format enforced by _check_iata (3 chars)
    icao: Optional[str] = None   # format enforced by _check_icao (4 chars)
    terminal: Optional[str] = Field(default=None, max_length=10)
    gate: Optional[str] = Field(default=None, max_length=10)
    baggage: Optional[str] = Field(default=None, max_length=10)
    delay: Optional[float] = Field(default=None, ge=0, le=MAX_PLAUSIBLE_DELAY_MIN)
    scheduled: Optional[str] = None
    estimated: Optional[str] = None
    actual: Optional[str] = None
    estimated_runway: Optional[str] = None
    actual_runway: Optional[str] = None

    @field_validator("iata", "icao", mode="before")
    @classmethod
    def _upper_code(cls, value: Any) -> Any:
        """Normalise codes (trim + upper-case); blank strings become None."""
        if isinstance(value, str):
            value = value.strip().upper()
            return value or None
        return value

    @field_validator("iata")
    @classmethod
    def _check_iata(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _IATA_AIRPORT.match(value):
            raise ValueError(f"airport IATA code {value!r} must be 3 letters/digits")
        return value

    @field_validator("icao")
    @classmethod
    def _check_icao(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _ICAO_AIRPORT.match(value):
            raise ValueError(f"airport ICAO code {value!r} must be 4 letters/digits")
        return value

    @field_validator(
        "scheduled", "estimated", "actual", "estimated_runway", "actual_runway"
    )
    @classmethod
    def _check_timestamp(cls, value: Optional[str]) -> Optional[str]:
        """Timestamps must be ISO-8601 (kept as text; pandas parses them later)."""
        return _validate_iso_timestamp(value)


class AirlineInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = Field(default=None, max_length=120)
    iata: Optional[str] = Field(default=None, max_length=4)
    icao: Optional[str] = Field(default=None, max_length=4)

    @field_validator("iata", "icao", mode="before")
    @classmethod
    def _upper_code(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip().upper()
            return value or None
        return value

    @field_validator("iata")
    @classmethod
    def _check_airline_iata(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _IATA_AIRLINE.match(value):
            raise ValueError(f"airline IATA code {value!r} must be 2 letters/digits")
        return value


class FlightInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    number: Optional[str] = Field(default=None, max_length=10)
    iata: Optional[str] = Field(default=None, max_length=8)
    icao: Optional[str] = Field(default=None, max_length=8)
    codeshared: Optional[dict] = None


class AircraftInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    registration: Optional[str] = Field(default=None, max_length=20)
    iata: Optional[str] = Field(default=None, max_length=10)
    icao: Optional[str] = Field(default=None, max_length=10)
    icao24: Optional[str] = Field(default=None, max_length=10)


class LiveInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    updated: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    altitude: Optional[float] = None
    direction: Optional[float] = Field(default=None, ge=0, le=360)
    speed_horizontal: Optional[float] = Field(default=None, ge=0)
    speed_vertical: Optional[float] = None
    is_ground: Optional[bool] = None


class FlightRecord(BaseModel):
    """One validated flight entry from the AviationStack ``data`` array."""

    model_config = ConfigDict(extra="ignore")

    flight_date: str = Field(min_length=8, max_length=12)
    flight_status: str
    departure: AirportPointInfo
    arrival: AirportPointInfo
    airline: AirlineInfo = Field(default_factory=AirlineInfo)
    flight: FlightInfo = Field(default_factory=FlightInfo)
    aircraft: Optional[AircraftInfo] = None
    live: Optional[LiveInfo] = None

    @field_validator("flight_status")
    @classmethod
    def _check_status(cls, value: str) -> str:
        status = (value or "").strip().lower()
        if status not in VALID_FLIGHT_STATUSES:
            raise ValueError(f"unrecognised flight status {value!r}")
        return status

    @field_validator("flight_date")
    @classmethod
    def _check_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value.strip()[:10])
        except ValueError:
            raise ValueError(f"flight_date {value!r} is not ISO formatted")
        return value.strip()[:10]

    @model_validator(mode="after")
    def _check_consistency(self) -> "FlightRecord":
        """Cross-field rules that no single field can express."""
        # 1. The record must be identifiable (it feeds the natural key).
        if not (self.flight.iata or self.flight.icao or self.flight.number):
            raise ValueError(
                "flight has no IATA code, ICAO code or number - cannot be identified"
            )
        # 2. It must say where it goes or comes from.
        if not (self.departure.iata or self.arrival.iata):
            raise ValueError("neither departure nor arrival airport code is present")
        # 3. Scheduled arrival cannot precede scheduled departure. The API's
        #    "+00:00" suffix is not a real offset (see timeutils), so both
        #    times are first placed on the UTC axis with each airport's own
        #    timezone. The rule is skipped when a timezone cannot be resolved.
        dep = wall_clock_to_utc(self.departure.scheduled, self.departure.timezone)
        arr = wall_clock_to_utc(self.arrival.scheduled, self.arrival.timezone)
        if dep is not None and arr is not None:
            if arr < dep:
                raise ValueError("scheduled arrival is earlier than scheduled departure")
        else:
            # A timezone is missing: compare the raw wall-clock values but allow
            # the largest possible offset difference (UTC-12 .. UTC+14 = 26 h),
            # so only impossible orderings are rejected.
            d_raw = parse_wall_clock(self.departure.scheduled)
            a_raw = parse_wall_clock(self.arrival.scheduled)
            if d_raw and a_raw and a_raw < d_raw - timedelta(hours=26):
                raise ValueError(
                    "scheduled arrival is earlier than scheduled departure "
                    "(even allowing for any timezone difference)")
        return self


class PaginationInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    limit: int = 0
    offset: int = 0
    count: int = 0
    total: int = 0


class FlightsResponse(BaseModel):
    """Top-level ``/v1/flights`` payload."""

    model_config = ConfigDict(extra="ignore")

    pagination: PaginationInfo = Field(default_factory=PaginationInfo)
    data: List[FlightRecord] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 2 model: the flattened row that pandas hands to the loader
# ---------------------------------------------------------------------------


class FlightRow(BaseModel):
    """Validates one *transformed* row just before it is loaded into SQLite.

    This is the second Pydantic gate. It guards the invariants the database
    relies on, so a transformation bug can never write a malformed row.
    """

    model_config = ConfigDict(extra="ignore")

    flight_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    flight_status: str
    flight_iata: Optional[str] = Field(default=None, max_length=12)
    dep_iata: Optional[str] = Field(default=None, pattern=r"^[A-Z0-9]{3}$")
    arr_iata: Optional[str] = Field(default=None, pattern=r"^[A-Z0-9]{3}$")
    dep_delay_min: Optional[float] = Field(default=None, ge=0, le=MAX_PLAUSIBLE_DELAY_MIN)
    arr_delay_min: Optional[float] = Field(default=None, ge=0, le=MAX_PLAUSIBLE_DELAY_MIN)
    max_delay_min: Optional[float] = Field(default=None, ge=0, le=MAX_PLAUSIBLE_DELAY_MIN)
    scheduled_duration_min: Optional[float] = Field(default=None, gt=0, le=24 * 60)
    dep_local_hour: Optional[int] = Field(default=None, ge=0, le=23)
    live_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    live_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    live_speed_kmh: Optional[float] = Field(default=None, ge=0, le=1500)
    is_delayed: bool = False
    route: Optional[str] = None

    @field_validator("flight_status")
    @classmethod
    def _status(cls, value: str) -> str:
        if value not in VALID_FLIGHT_STATUSES:
            raise ValueError(f"unrecognised flight status {value!r}")
        return value

    @model_validator(mode="after")
    def _delay_flag_matches_delay(self) -> "FlightRow":
        if self.is_delayed and not (self.max_delay_min and self.max_delay_min > 0):
            raise ValueError("is_delayed is True but no positive delay is recorded")
        return self


# ---------------------------------------------------------------------------
# Validation reporting
# ---------------------------------------------------------------------------


@dataclass
class RejectedRecord:
    """One record that failed validation, with every reason it failed."""

    index: int
    identifier: str
    stage: str  # "extract" (raw API record) or "transform" (flattened row)
    errors: List[Dict[str, str]]
    raw: Any = None

    def summary(self) -> str:
        reasons = "; ".join(f"{e['field']}: {e['message']}" for e in self.errors[:3])
        more = f" (+{len(self.errors) - 3} more)" if len(self.errors) > 3 else ""
        return f"[{self.stage}] record {self.index} ({self.identifier}): {reasons}{more}"


@dataclass
class ValidationReport:
    """Accepted / rejected outcome of validating one batch."""

    total: int = 0
    accepted: List[FlightRecord] = field(default_factory=list)
    rejected: List[RejectedRecord] = field(default_factory=list)

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

    @property
    def acceptance_rate(self) -> float:
        return round(100 * self.accepted_count / self.total, 1) if self.total else 0.0

    def error_breakdown(self) -> Dict[str, int]:
        """How many rejections each field/rule caused (most common first)."""
        counts: Dict[str, int] = {}
        for rec in self.rejected:
            for err in rec.errors:
                counts[err["field"]] = counts.get(err["field"], 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def messages(self) -> List[str]:
        return [rec.summary() for rec in self.rejected]


def _flatten_errors(exc: ValidationError) -> List[Dict[str, str]]:
    """Convert a Pydantic error into readable ``field`` / ``message`` pairs."""
    out = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ())) or "record"
        message = str(err.get("msg", "invalid value"))
        if message.startswith("Value error, "):
            message = message[len("Value error, "):]
        out.append({"field": loc, "message": message, "type": str(err.get("type", ""))})
    return out


def _identify(raw: Any, index: int) -> str:
    """Best-effort human label for a raw record (never raises)."""
    if isinstance(raw, dict):
        flight = raw.get("flight")
        if isinstance(flight, dict):
            label = flight.get("iata") or flight.get("icao") or flight.get("number")
            if label:
                return str(label)
    return f"row {index}"


def validate_batch(raw_records: List[Any]) -> ValidationReport:
    """Validate raw API records and return a full :class:`ValidationReport`."""
    report = ValidationReport(total=len(raw_records))
    for index, raw in enumerate(raw_records):
        try:
            report.accepted.append(FlightRecord.model_validate(raw))
        except ValidationError as exc:
            report.rejected.append(
                RejectedRecord(index, _identify(raw, index), "extract",
                               _flatten_errors(exc), raw)
            )
    return report


def validate_rows(rows: List[Dict[str, Any]]) -> Tuple[List[int], List[RejectedRecord]]:
    """Validate flattened rows (stage 2). Returns ``(ok_positions, rejected)``."""
    ok: List[int] = []
    rejected: List[RejectedRecord] = []
    for pos, row in enumerate(rows):
        try:
            FlightRow.model_validate(row)
            ok.append(pos)
        except ValidationError as exc:
            label = row.get("flight_iata") or f"row {pos}"
            rejected.append(
                RejectedRecord(pos, str(label), "transform", _flatten_errors(exc), row)
            )
    return ok, rejected


def validate_flight_records(
    raw_records: List[dict],
) -> Tuple[List[FlightRecord], List[str]]:
    """Backwards-compatible wrapper: ``(valid_records, error_messages)``."""
    report = validate_batch(raw_records)
    return report.accepted, report.messages()
