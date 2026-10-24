"""Flight search pipeline: extract (provider) -> validate (Pydantic) -> transform (pandas).

Mirrors the flight ETL: bad options are rejected with field-level reasons and
logged to the run history (``refresh_log`` / ``rejected_records``), and the
untouched provider response is archived for real sources. Search results are
transient - they are shown in the Flight Search screen and exported on demand.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from . import config, database, database_travel
from .models import RejectedRecord, _flatten_errors
from .providers import demo, flightapi
from .providers.base import FlightFetchResult, FlightQuery
from .utils import AppError, get_logger, save_json, timestamp_for_filename

logger = get_logger()
ORIGINS = {"live_api", "sample"}
PIPELINE = "flight_search"

OPTION_COLUMNS = ["option_key", "retrieved_at", "source", "data_origin", "origin_iata", "destination_iata",
                  "departure_at", "return_at", "airline_iata", "flight_number", "cabin", "stops", "duration_min",
                  "arrival_at", "arrival_derived", "baggage", "booking_url"]


class FlightOption(BaseModel):
    """Validation gate for one normalised flight option."""

    model_config = ConfigDict(extra="ignore")

    origin_iata: str = Field(pattern=r"^[A-Z]{3}$")
    destination_iata: str = Field(pattern=r"^[A-Z]{3}$")
    departure_at: str
    return_at: Optional[str] = None
    arrival_at: Optional[str] = None
    arrival_derived: int = 0
    airline_iata: Optional[str] = Field(default=None, pattern=r"^[A-Z0-9]{2}$")
    flight_number: Optional[str] = Field(default=None, max_length=12)
    stops: Optional[int] = Field(default=None, ge=0, le=6)
    duration_min: Optional[int] = Field(default=None, ge=5, le=3000)
    cabin: Optional[str] = None
    baggage: Optional[str] = Field(default=None, max_length=80)
    booking_url: Optional[str] = None
    source: str
    data_origin: str

    @field_validator("departure_at", "return_at", "arrival_at")
    @classmethod
    def _iso(cls, v):
        if v in (None, ""):
            return None
        try:
            datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"{v!r} is not an ISO-8601 timestamp")
        return str(v)

    @field_validator("data_origin")
    @classmethod
    def _origin(cls, v):
        if v not in ORIGINS:
            raise ValueError(f"unknown data origin {v!r}")
        return v

    @field_validator("booking_url")
    @classmethod
    def _url(cls, v):
        if v in (None, ""):
            return None
        if not str(v).startswith("https://www.aviasales.com"):
            raise ValueError("booking URL is not from a verified provider host")
        return v

    @model_validator(mode="after")
    def _consistency(self):
        if self.origin_iata == self.destination_iata:
            raise ValueError("origin and destination are the same airport")
        dep = _utc(self.departure_at)
        for label, val in (("return", self.return_at), ("arrival", self.arrival_at)):
            if val and _utc(val) < dep:
                raise ValueError(f"{label} time is earlier than departure")
        return self


def _utc(text: str) -> datetime:
    d = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)


def validate_options(raw: List[dict]):
    """-> (accepted FlightOption list, rejected RejectedRecord list)."""
    accepted, rejected = [], []
    for i, item in enumerate(raw):
        try:
            accepted.append(FlightOption.model_validate(item))
        except ValidationError as exc:
            label = f"{(item or {}).get('flight_number') or 'flight'} ({(item or {}).get('origin_iata')}-{(item or {}).get('destination_iata')})" \
                if isinstance(item, dict) else f"row {i}"
            rejected.append(RejectedRecord(i, label, "extract", _flatten_errors(exc), item))
    return accepted, rejected


def _option_key(o: dict) -> str:
    parts = [o["source"], o["origin_iata"], o["destination_iata"], o["departure_at"], o.get("return_at") or "",
             o.get("airline_iata") or "", o.get("flight_number") or "", o.get("cabin") or "", str(o.get("stops"))]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def transform_options(options: List[FlightOption], retrieved_at: datetime) -> pd.DataFrame:
    """Options -> display-ready DataFrame (UTC times, derived arrival, de-duplicated)."""
    rows = []
    for o in options:
        d = o.model_dump()
        d["departure_at"] = _utc(d["departure_at"]).isoformat()
        d["return_at"] = _utc(d["return_at"]).isoformat() if d["return_at"] else None
        if d["arrival_at"]:
            d["arrival_at"] = _utc(d["arrival_at"]).isoformat()
        elif d["duration_min"]:
            d["arrival_at"] = (_utc(d["departure_at"]) + timedelta(minutes=d["duration_min"])).isoformat()
            d["arrival_derived"] = 1          # computed, not supplied by the source
        d["retrieved_at"] = retrieved_at.astimezone(timezone.utc).isoformat(timespec="seconds")
        d["option_key"] = _option_key(d)
        rows.append(d)
    df = pd.DataFrame(rows, columns=OPTION_COLUMNS)
    if df.empty:
        return df
    return df.drop_duplicates(["option_key"], keep="last").reset_index(drop=True)


@dataclass
class SearchRunReport:
    success: bool = False
    status: str = "failed"
    message: str = ""
    source: str = ""
    data_origin: str = ""
    run_id: Optional[int] = None
    extracted: int = 0
    accepted: int = 0
    rejected: int = 0
    duplicates_in_batch: int = 0
    duration_s: float = 0.0
    rejection_breakdown: Dict[str, int] = field(default_factory=dict)
    rejected_messages: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    options: Optional[pd.DataFrame] = None
    raw_file: Optional[str] = None


def pick_provider(db_path=None):
    """FlightAPI when a key is configured, else the labelled sample provider."""
    if config.search_mode() == "live_api":
        return flightapi.FlightApiProvider()
    return demo.DemoFlightProvider(db_path)


def ingest(result: FlightFetchResult, db_path=None, archive_raw: bool = True,
           started: Optional[float] = None) -> SearchRunReport:
    """Validate and transform one fetch result and log the run."""
    started = started or time.perf_counter()
    rep = SearchRunReport(source=result.source, data_origin=result.data_origin,
                          extracted=len(result.options), notes=list(result.notes))
    if archive_raw and result.raw is not None and result.data_origin != "sample":
        path = config.DATA_RAW_DIR / f"flight_search_raw_{result.source}_{timestamp_for_filename()}.json"
        save_json(result.raw, path)
        rep.raw_file = str(path)
    accepted, rejected = validate_options(result.options)
    df = transform_options(accepted, result.retrieved_at)
    rep.accepted, rep.rejected = len(accepted), len(rejected)
    rep.duplicates_in_batch = len(accepted) - len(df)
    breakdown: Dict[str, int] = {}
    for r in rejected:
        for e in r.errors:
            breakdown[e["field"]] = breakdown.get(e["field"], 0) + 1
    rep.rejection_breakdown = dict(sorted(breakdown.items(), key=lambda kv: -kv[1]))
    rep.rejected_messages = [r.summary() for r in rejected]
    status = "empty" if not result.options else ("partial" if rejected else "success")
    msg = (f"{len(df)} flight option(s) from {result.source}; {len(rejected)} rejected."
           if result.options else "The source returned no flights.")
    rep.duration_s = round(time.perf_counter() - started, 2)
    rep.run_id = database_travel.log_search_run(
        source=result.source, fetched=len(result.options), accepted=len(df), rejected=rejected, status=status,
        message=msg, duration_s=rep.duration_s, data_origin=result.data_origin, db_path=db_path)
    rep.options = df
    rep.success, rep.status, rep.message = True, status, msg
    logger.info("Flight search (%s): %d extracted, %d accepted, %d rejected",
                result.source, rep.extracted, rep.accepted, rep.rejected)
    return rep


def run_flight_search(query: FlightQuery, provider=None, db_path=None) -> SearchRunReport:
    """Search with ``provider`` and ingest the result. Provider errors are logged to
    ``refresh_log`` (status ``failed``) and re-raised for the UI to show."""
    started = time.perf_counter()
    provider = provider or pick_provider(db_path)
    try:
        result = provider.search(query)
    except AppError as exc:
        try:
            database.log_refresh(getattr(provider, "name", "flight search"), 0, 0, 0, "failed", str(exc), db_path,
                                 pipeline=PIPELINE, data_origin=getattr(provider, "data_origin", "live_api"))
        except Exception:  # logging must never hide the original error
            logger.exception("Could not log flight-search failure")
        raise
    return ingest(result, db_path, started=started)
