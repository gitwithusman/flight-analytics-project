"""Pandas transformation and cleaning for validated flight records.

Input:  a list of ``FlightRecord`` Pydantic models (already validated).
Output: tidy DataFrames ready for SQLite loading, analytics and charts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from . import config
from .models import FlightRecord, RejectedRecord, validate_rows
from .timeutils import parse_wall_clock, resolve_timezone, wall_clock_to_utc
from .utils import get_logger, timestamp_for_filename, utc_now_iso

logger = get_logger()

# Column order used for the flights table / processed dataset.
FLIGHT_COLUMNS = [
    "flight_date",
    "flight_status",
    "flight_iata",
    "flight_icao",
    "flight_number",
    "airline_name",
    "airline_iata",
    "airline_icao",
    "dep_airport",
    "dep_iata",
    "dep_icao",
    "dep_terminal",
    "dep_gate",
    "dep_delay_min",
    "dep_scheduled",
    "dep_estimated",
    "dep_actual",
    "dep_timezone",
    "arr_airport",
    "arr_iata",
    "arr_icao",
    "arr_terminal",
    "arr_gate",
    "arr_baggage",
    "arr_delay_min",
    "arr_scheduled",
    "arr_estimated",
    "arr_actual",
    "arr_timezone",
    "aircraft_registration",
    "aircraft_icao24",
    "is_codeshared",
    "live_latitude",
    "live_longitude",
    "live_altitude",
    "live_speed_kmh",
    "live_is_ground",
    "route",
    "is_delayed",
    "max_delay_min",
    "scheduled_duration_min",
    "dep_local_hour",
    "retrieved_at",
]

# Columns that form the natural uniqueness key for a flight record.
UNIQUE_KEY = ["flight_date", "flight_iata", "dep_iata", "arr_iata"]

SEARCHABLE_TEXT_COLUMNS = [
    "flight_iata",
    "flight_number",
    "airline_name",
    "dep_airport",
    "dep_iata",
    "arr_airport",
    "arr_iata",
    "flight_status",
]


# Every cleaning decision taken by the transform stage, with its justification.
# The list is exported into the pipeline report and the project report so the
# written justification always matches the code that runs.
TRANSFORM_DECISIONS = [
    ("Blank / whitespace text", "converted to NULL after trimming",
     "an empty string and a missing value mean the same thing; one representation "
     "keeps missing-value counts honest"),
    ("Airport / airline codes", "trimmed and upper-cased",
     "codes are case-insensitive identifiers; normalising prevents 'jfk' and 'JFK' "
     "from counting as different airports"),
    ("Timestamps", "airport-local wall-clock time converted to true UTC using the "
     "airport's own timezone; unparseable or timezone-less -> NULL",
     "the API labels local times with a spurious '+00:00' (proved with live.updated); "
     "taking the suffix literally corrupts every cross-timezone duration"),
    ("Missing airport timezone", "filled from another record of the same airport "
     "(batch or database); otherwise the timestamp stays NULL",
     "no timezone is ever guessed or invented; unresolved values are reported"),
    ("Malformed timezone such as '+8'", "interpreted as a fixed UTC offset",
     "the value is unambiguous and recoverable"),
    ("Delay minutes", "coerced to numeric; missing values are NOT imputed",
     "a missing delay means 'not reported', not 'on time'; imputing 0 would bias "
     "every delay statistic downwards"),
    ("Negative / implausible delays (> 48 h)", "rejected by Pydantic, not clipped",
     "a bad value signals a source problem; silently repairing it would hide it"),
    ("Duplicate flights (same date + flight + airports)", "keep the last occurrence",
     "later records carry the most recent status/delay for the same flight"),
    ("Flights with no identifier or no airport code", "rejected by Pydantic",
     "they cannot be keyed; storing them under an empty key would merge unrelated flights"),
    ("is_delayed", "True only when a reported delay is > 0",
     "unknown delay is therefore False; the EDA reports delay coverage separately"),
    ("scheduled_duration_min", "derived: scheduled arrival - scheduled departure "
     "(both in true UTC)",
     "gives a numeric measure (block time) for distribution and outlier analysis"),
    ("dep_local_hour", "derived: wall-clock hour of the scheduled departure",
     "time-of-day patterns are about local time, not UTC; needs no timezone lookup"),
]


@dataclass
class TransformReport:
    """Everything the transform stage did to a batch (for logs and reports)."""

    rows_in: int = 0
    rows_out: int = 0
    duplicates_removed: int = 0
    unparseable_timestamps: int = 0
    timezones_filled: int = 0
    timestamps_unlocalised: int = 0
    rows_rejected: int = 0
    missing_by_column: Dict[str, int] = field(default_factory=dict)
    rejected: List[RejectedRecord] = field(default_factory=list)


def build_timezone_lookup(records: List[FlightRecord],
                          known: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Airport IATA -> timezone, learned from the records themselves.

    ``known`` (e.g. from the airports already in the database) is used first;
    nothing external is consulted, so no timezone is ever invented.
    """
    lookup: Dict[str, str] = dict(known or {})
    for rec in records:
        for point in (rec.departure, rec.arrival):
            iata, tz = (point.iata or "").strip(), (point.timezone or "").strip()
            if iata and tz and resolve_timezone(tz) is not None:
                lookup.setdefault(iata, tz)
    return lookup


def _utc_text(value: Optional[str], tz_name: Optional[str]) -> Optional[str]:
    """Wall-clock text -> UTC ISO text (None if it cannot be localised)."""
    moment = wall_clock_to_utc(value, tz_name)
    return moment.isoformat() if moment is not None else None


def _record_to_row(record: FlightRecord, retrieved_at: str,
                   tz_lookup: Optional[Dict[str, str]] = None) -> dict:
    dep = record.departure
    arr = record.arrival
    airline = record.airline
    flight = record.flight
    aircraft = record.aircraft
    live = record.live

    dep_iata = (dep.iata or "").strip() or None
    arr_iata = (arr.iata or "").strip() or None
    dep_delay = dep.delay if dep.delay is not None else None
    arr_delay = arr.delay if arr.delay is not None else None
    delays = [d for d in (dep_delay, arr_delay) if d is not None]

    lookup = tz_lookup or {}
    dep_tz = (dep.timezone or "").strip() or lookup.get(dep_iata or "")
    arr_tz = (arr.timezone or "").strip() or lookup.get(arr_iata or "")
    if dep_tz and resolve_timezone(dep_tz) is None:
        dep_tz = lookup.get(dep_iata or "", dep_tz)
    if arr_tz and resolve_timezone(arr_tz) is None:
        arr_tz = lookup.get(arr_iata or "", arr_tz)
    local_dep = parse_wall_clock(dep.scheduled)

    return {
        "flight_date": record.flight_date,
        "flight_status": record.flight_status,
        "flight_iata": (flight.iata or flight.icao or "").strip() or None,
        "flight_icao": (flight.icao or "").strip() or None,
        "flight_number": (flight.number or "").strip() or None,
        "airline_name": (airline.name or "").strip() or None,
        "airline_iata": (airline.iata or "").strip() or None,
        "airline_icao": (airline.icao or "").strip() or None,
        "dep_airport": (dep.airport or "").strip() or None,
        "dep_iata": dep_iata,
        "dep_icao": (dep.icao or "").strip() or None,
        "dep_terminal": (dep.terminal or "").strip() or None,
        "dep_gate": (dep.gate or "").strip() or None,
        "dep_delay_min": dep_delay,
        "dep_scheduled": _utc_text(dep.scheduled, dep_tz),
        "dep_estimated": _utc_text(dep.estimated, dep_tz),
        "dep_actual": _utc_text(dep.actual, dep_tz),
        "dep_timezone": dep_tz or None,
        "arr_airport": (arr.airport or "").strip() or None,
        "arr_iata": arr_iata,
        "arr_icao": (arr.icao or "").strip() or None,
        "arr_terminal": (arr.terminal or "").strip() or None,
        "arr_gate": (arr.gate or "").strip() or None,
        "arr_baggage": (arr.baggage or "").strip() or None,
        "arr_delay_min": arr_delay,
        "arr_scheduled": _utc_text(arr.scheduled, arr_tz),
        "arr_estimated": _utc_text(arr.estimated, arr_tz),
        "arr_actual": _utc_text(arr.actual, arr_tz),
        "arr_timezone": arr_tz or None,
        "aircraft_registration": getattr(aircraft, "registration", None),
        "aircraft_icao24": getattr(aircraft, "icao24", None),
        "is_codeshared": bool(flight.codeshared),
        "live_latitude": getattr(live, "latitude", None),
        "live_longitude": getattr(live, "longitude", None),
        "live_altitude": getattr(live, "altitude", None),
        "live_speed_kmh": getattr(live, "speed_horizontal", None),
        "live_is_ground": getattr(live, "is_ground", None),
        "route": f"{dep_iata}-{arr_iata}" if dep_iata and arr_iata else None,
        "is_delayed": bool(delays and max(delays) > 0),
        "max_delay_min": max(delays) if delays else None,
        "scheduled_duration_min": None,  # derived in clean_flights()
        "dep_local_hour": local_dep.hour if local_dep else None,
        "retrieved_at": retrieved_at,
    }


def records_to_dataframe(
    records: List[FlightRecord],
    retrieved_at: Optional[str] = None,
    known_timezones: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """Flatten validated records into the canonical flights DataFrame."""
    retrieved_at = retrieved_at or utc_now_iso()
    lookup = build_timezone_lookup(records, known_timezones)
    rows = [_record_to_row(rec, retrieved_at, lookup) for rec in records]
    df = pd.DataFrame(rows, columns=FLIGHT_COLUMNS)
    if df.empty:
        return df
    return clean_flights(df)


def _nan_to_none(row: dict) -> dict:
    """Pydantic needs real ``None`` instead of NaN / NaT / pd.NA."""
    out = {}
    for key, value in row.items():
        try:
            out[key] = None if pd.isna(value) else value
        except (TypeError, ValueError):
            out[key] = value
    return out


def transform_records(
    records: List[FlightRecord],
    retrieved_at: Optional[str] = None,
    known_timezones: Optional[Dict[str, str]] = None,
) -> Tuple[pd.DataFrame, TransformReport]:
    """Full transform stage: flatten -> clean -> derive -> row validation.

    Returns the load-ready DataFrame plus a :class:`TransformReport`. Rows that
    fail the second Pydantic gate (:class:`models.FlightRow`) are removed from
    the DataFrame and listed in ``report.rejected``.
    """
    report = TransformReport(rows_in=len(records))
    retrieved_at = retrieved_at or utc_now_iso()
    lookup = build_timezone_lookup(records, known_timezones)
    rows = [_record_to_row(rec, retrieved_at, lookup) for rec in records]
    raw_df = pd.DataFrame(rows, columns=FLIGHT_COLUMNS)
    if raw_df.empty:
        return raw_df, report

    # Timestamps present in the source but lost during localisation: either
    # the timezone could not be resolved or the text was not a valid time.
    src_ts = {  # source field -> output column
        ("dep", "scheduled"): "dep_scheduled", ("dep", "estimated"): "dep_estimated",
        ("dep", "actual"): "dep_actual", ("arr", "scheduled"): "arr_scheduled",
        ("arr", "estimated"): "arr_estimated", ("arr", "actual"): "arr_actual",
    }
    lost = 0
    for (side, attr), col in src_ts.items():
        for rec, out in zip(records, raw_df[col]):
            point = rec.departure if side == "dep" else rec.arrival
            if getattr(point, attr) and pd.isna(out):
                lost += 1
    report.timestamps_unlocalised = lost
    report.timezones_filled = sum(
        1 for rec in records for point in (rec.departure, rec.arrival)
        if point.iata and not (point.timezone or "").strip()
        and point.iata in lookup)
    df = clean_flights(raw_df)
    report.duplicates_removed = _count_key_duplicates(raw_df)
    report.unparseable_timestamps = sum(
        1 for rec in records for point in (rec.departure, rec.arrival)
        for attr in ("scheduled", "estimated", "actual")
        if getattr(point, attr) and parse_wall_clock(getattr(point, attr)) is None)

    # Stage-2 Pydantic gate on the flattened rows.
    dict_rows = [_nan_to_none(r) for r in df.to_dict("records")]
    ok_positions, rejected = validate_rows(dict_rows)
    if rejected:
        df = df.iloc[ok_positions].reset_index(drop=True)
    report.rejected = rejected
    report.rows_rejected = len(rejected)
    report.rows_out = len(df)
    report.missing_by_column = {
        c: int(v) for c, v in df.isna().sum().items() if v
    }
    return df, report


def _count_key_duplicates(df: pd.DataFrame) -> int:
    """Rows that share the natural key with an earlier row."""
    key = [c for c in UNIQUE_KEY if c in df]
    return int(df.duplicated(subset=key, keep="last").sum()) if key else 0


def clean_flights(df: pd.DataFrame) -> pd.DataFrame:
    """Apply consistent cleaning: types, duplicates, date parsing."""
    df = df.copy()

    for col in ("dep_delay_min", "arr_delay_min", "max_delay_min"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ("dep_scheduled", "dep_estimated", "dep_actual",
                "arr_scheduled", "arr_estimated", "arr_actual"):
        if col in df:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)

    if "flight_date" in df:
        df["flight_date"] = df["flight_date"].astype(str).str[:10]
    for col in ("is_codeshared", "is_delayed"):
        if col in df:
            df[col] = df[col].fillna(False).astype(bool)
    if "live_is_ground" in df:
        df["live_is_ground"] = df["live_is_ground"].astype("boolean")

    # Standardise text columns (trim; blank -> NULL; codes upper-cased).
    for col in df.columns:
        if col == "retrieved_at":
            continue
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            cleaned = df[col].where(df[col].isna(), df[col].astype(str).str.strip())
            df[col] = cleaned.replace("", pd.NA).astype(object).where(cleaned.notna(), None)
    for col in ("dep_iata", "arr_iata", "dep_icao", "arr_icao",
                "airline_iata", "airline_icao", "flight_iata", "flight_icao"):
        if col in df:
            df[col] = df[col].where(df[col].isna(), df[col].astype(str).str.upper())

    # Derived numeric feature: scheduled block time in minutes.
    if {"dep_scheduled", "arr_scheduled"} <= set(df.columns):
        duration = (df["arr_scheduled"] - df["dep_scheduled"]).dt.total_seconds() / 60
        df["scheduled_duration_min"] = duration

    # Drop rows that cannot be identified at all.
    key_cols = [c for c in UNIQUE_KEY if c in df]
    if key_cols:
        keep = [c for c in ("dep_iata", "arr_iata") if c in df]
        if keep:
            df = df.dropna(subset=keep, how="all")
        df = df.drop_duplicates(subset=key_cols, keep="last")
    return df.reset_index(drop=True)


def derive_airports(flights_df: pd.DataFrame) -> pd.DataFrame:
    """Build an airports table from the departure/arrival blocks of flights.

    Every row comes straight from the API payload - no external airport list
    is invented. ``sightings`` counts how often each airport appeared.
    """
    if flights_df.empty:
        return pd.DataFrame(
            columns=["airport_name", "iata", "icao", "timezone",
                     "departures", "arrivals", "sightings"]
        )

    dep = flights_df[["dep_airport", "dep_iata", "dep_icao", "dep_timezone"]].rename(
        columns={"dep_airport": "airport_name", "dep_iata": "iata",
                 "dep_icao": "icao", "dep_timezone": "timezone"}
    )
    dep["departures"] = 1
    dep["arrivals"] = 0

    arr = flights_df[["arr_airport", "arr_iata", "arr_icao", "arr_timezone"]].rename(
        columns={"arr_airport": "airport_name", "arr_iata": "iata",
                 "arr_icao": "icao", "arr_timezone": "timezone"}
    )
    arr["departures"] = 0
    arr["arrivals"] = 1

    combined = pd.concat([dep, arr], ignore_index=True)
    combined = combined.dropna(subset=["iata"])
    if combined.empty:
        return pd.DataFrame(
            columns=["airport_name", "iata", "icao", "timezone",
                     "departures", "arrivals", "sightings"]
        )

    grouped = (
        combined.groupby("iata", as_index=False)
        .agg(
            airport_name=("airport_name", "first"),
            icao=("icao", "first"),
            timezone=("timezone", "first"),
            departures=("departures", "sum"),
            arrivals=("arrivals", "sum"),
        )
    )
    grouped["sightings"] = grouped["departures"] + grouped["arrivals"]
    return grouped.sort_values("sightings", ascending=False).reset_index(drop=True)


def quality_report(df: pd.DataFrame) -> dict:
    """Basic data-quality metrics shown by both applications."""
    if df.empty:
        return {
            "rows": 0,
            "columns": 0,
            "missing_values": {},
            "duplicate_rows": 0,
            "unique_flights": 0,
            "delay_data_available": False,
        }
    return {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "missing_values": {c: int(v) for c, v in df.isna().sum().items() if v},
        "duplicate_rows": int(df.duplicated(subset=UNIQUE_KEY).sum()),
        "unique_flights": int(df["flight_iata"].nunique(dropna=True)),
        "delay_data_available": bool(df["max_delay_min"].notna().any()),
    }


def save_processed(df: pd.DataFrame, name: str = "flights_processed") -> Optional[str]:
    """Persist the processed dataset to ``data/processed/`` as CSV."""
    if df.empty:
        return None
    path = config.DATA_PROCESSED_DIR / f"{name}_{timestamp_for_filename()}.csv"
    df.to_csv(path, index=False)
    latest = config.DATA_PROCESSED_DIR / f"{name}_latest.csv"
    df.to_csv(latest, index=False)
    logger.info("Processed dataset saved to %s", path)
    return str(path)


def load_latest_processed(name: str = "flights_processed") -> pd.DataFrame:
    """Load the most recent processed CSV if it exists."""
    latest = config.DATA_PROCESSED_DIR / f"{name}_latest.csv"
    if not latest.exists():
        return pd.DataFrame(columns=FLIGHT_COLUMNS)
    df = pd.read_csv(latest, low_memory=False)
    return clean_flights(df) if not df.empty else df
