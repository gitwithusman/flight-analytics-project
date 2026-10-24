"""ETL pipeline orchestrator: Extract -> Validate -> Transform -> Load -> Verify.

This module is the single place where the five stages are wired together. The
terminal app, the GUI (through :mod:`src.service`) and the command-line runner
``main_task/run_pipeline.py`` all call :func:`run_pipeline`, so every entry
point behaves identically and produces the same :class:`PipelineReport`.

Stages
------
1. **Extract**   - AviationStack ``/v1/flights`` (HTTP errors, timeouts, empty
   and malformed responses handled in :mod:`src.api_client`) *or* replay of an
   archived raw response from ``data/raw/``.
2. **Validate**  - Pydantic :class:`~src.models.FlightRecord` gate; rejected
   records are kept with field-level reasons.
3. **Transform** - pandas flattening / cleaning / derived columns, followed by
   the second Pydantic gate (:class:`~src.models.FlightRow`).
4. **Load**      - one atomic SQLite transaction (upsert, airports, run log,
   rejected-record audit trail).
5. **Verify**    - SQL integrity checks on the stored data.
"""

from __future__ import annotations

import csv
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import api_client, config, data_processor, database
from .models import RejectedRecord, validate_batch
from .utils import AppError, get_logger, save_json, timestamp_for_filename, utc_now_iso

logger = get_logger()


@dataclass
class PipelineReport:
    """Complete, serialisable description of one pipeline run."""

    success: bool = False
    status: str = "failed"  # success | partial | empty | failed
    message: str = ""
    source: str = ""
    started_at: str = ""
    duration_s: float = 0.0
    run_id: Optional[int] = None
    # Extract
    extracted: int = 0
    pages_requested: int = 1
    raw_file: Optional[str] = None
    # Validate (stage 1)
    accepted: int = 0
    rejected_extract: int = 0
    acceptance_rate_pct: float = 0.0
    rejection_breakdown: Dict[str, int] = field(default_factory=dict)
    # Transform (stage 2)
    duplicates_removed: int = 0
    unparseable_timestamps: int = 0
    rejected_transform: int = 0
    rows_ready: int = 0
    missing_by_column: Dict[str, int] = field(default_factory=dict)
    # Load
    inserted: int = 0
    updated: int = 0
    airports: int = 0
    flights_in_database: int = 0
    # Verify
    verification: Dict[str, Any] = field(default_factory=dict)
    # Artifacts
    processed_file: Optional[str] = None
    rejected_file: Optional[str] = None
    report_file: Optional[str] = None
    rejected_messages: List[str] = field(default_factory=list)

    @property
    def rejected_total(self) -> int:
        return self.rejected_extract + self.rejected_transform

    def to_dict(self) -> dict:
        data = asdict(self)
        data["rejected_total"] = self.rejected_total
        return data

    def summary_lines(self) -> List[str]:
        """Human-readable run summary shared by the CLI and the terminal app."""
        return [
            f"Source                 : {self.source}",
            f"Extracted records      : {self.extracted}",
            f"Accepted (Pydantic)    : {self.accepted} "
            f"({self.acceptance_rate_pct}% of extracted)",
            f"Rejected               : {self.rejected_total} "
            f"(extract {self.rejected_extract}, transform {self.rejected_transform})",
            f"Duplicates removed     : {self.duplicates_removed}",
            f"New rows inserted      : {self.inserted}",
            f"Existing rows updated  : {self.updated}",
            f"Flights in database    : {self.flights_in_database}",
            f"Airports (derived)     : {self.airports}",
            f"Integrity checks       : "
            f"{'PASSED' if self.verification.get('all_checks_passed') else 'FAILED/NA'}",
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_rejected_csv(rejected: Iterable[RejectedRecord], stamp: str) -> Optional[str]:
    rejected = list(rejected)
    if not rejected:
        return None
    path = config.REPORTS_DIR / f"rejected_records_{stamp}.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["stage", "record_index", "identifier",
                         "failed_fields", "reasons"])
        for rec in rejected:
            writer.writerow([
                rec.stage, rec.index, rec.identifier,
                ", ".join(sorted({e["field"] for e in rec.errors})),
                " | ".join(e["message"] for e in rec.errors),
            ])
    return str(path)


def retrieved_at_from_filename(path: Path) -> Optional[str]:
    """``flights_raw_20261009_101516.json`` -> UTC timestamp string.

    The file name holds the *local* time at which the response was archived;
    it is converted to UTC using the machine's own timezone.
    """
    match = re.search(r"(\d{8})_(\d{6})", Path(path).name)
    if not match:
        return None
    try:
        local = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _log_failure(source: str, message: str, db_path) -> None:
    """Record a failed run; never let logging hide the original error."""
    try:
        database.log_refresh(source, 0, 0, 0, "failed", message, db_path)
    except Exception:  # pragma: no cover - best effort only
        logger.exception("Could not write failure to refresh_log")


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    *,
    limit: int = config.DEFAULT_RECORD_LIMIT,
    pages: int = 1,
    flight_status: Optional[str] = None,
    dep_iata: Optional[str] = None,
    arr_iata: Optional[str] = None,
    airline_name: Optional[str] = None,
    flight_number: Optional[str] = None,
    raw_file: Optional[Path] = None,
    retrieved_at: Optional[str] = None,
    save_artifacts: bool = True,
    db_path=None,
) -> PipelineReport:
    """Run the whole ETL cycle once and return a :class:`PipelineReport`.

    ``raw_file`` replays an archived API response instead of calling the API.
    Hard failures (no key, network down, quota exhausted, database error) are
    logged to ``refresh_log`` and re-raised as :class:`AppError` subclasses;
    bad *records* never abort the run - they are rejected and reported.
    """
    started = time.perf_counter()
    stamp = timestamp_for_filename()
    report = PipelineReport(started_at=utc_now_iso())
    report.source = (f"raw_replay:{Path(raw_file).name}" if raw_file
                     else "aviationstack/flights")

    # ---- 1. EXTRACT -------------------------------------------------------
    try:
        if raw_file:
            payload = api_client.load_raw_payload(raw_file)
            report.raw_file = str(raw_file)
            retrieved_at = retrieved_at or retrieved_at_from_filename(Path(raw_file))
        else:
            filters = dict(flight_status=flight_status, dep_iata=dep_iata,
                           arr_iata=arr_iata, airline_name=airline_name,
                           flight_number=flight_number)
            if pages > 1:
                payload = api_client.fetch_flights_paged(
                    total=limit, page_size=min(limit, 100), max_pages=pages,
                    **filters)
                report.pages_requested = int(payload.get("pages_requested", 1))
            else:
                payload = api_client.fetch_flights(limit=limit, **filters)
    except AppError as exc:
        logger.error("Extract failed: %s", exc)
        _log_failure(report.source, str(exc), db_path)
        raise

    raw_records = payload.get("data") or []
    report.extracted = len(raw_records)
    logger.info("Extract: %d records from %s", report.extracted, report.source)

    if report.extracted == 0:
        report.success, report.status = True, "empty"
        report.message = "The API returned zero flights for the chosen filters."
        report.run_id = database.log_refresh(
            report.source, 0, 0, 0, "empty", "API returned no records", db_path)
        report.verification = database.verify_database(db_path)
        report.flights_in_database = report.verification["flights"]
        report.duration_s = round(time.perf_counter() - started, 2)
        return report

    # ---- 2. VALIDATE (Pydantic gate 1) -----------------------------------
    validation = validate_batch(raw_records)
    report.accepted = validation.accepted_count
    report.rejected_extract = validation.rejected_count
    report.acceptance_rate_pct = validation.acceptance_rate
    report.rejection_breakdown = validation.error_breakdown()
    logger.info("Validate: %d accepted, %d rejected",
                validation.accepted_count, validation.rejected_count)

    # ---- 3. TRANSFORM (pandas + Pydantic gate 2) --------------------------
    flights_df, transform = data_processor.transform_records(
        validation.accepted, retrieved_at=retrieved_at)
    report.duplicates_removed = transform.duplicates_removed
    report.unparseable_timestamps = transform.unparseable_timestamps
    report.rejected_transform = transform.rows_rejected
    report.rows_ready = transform.rows_out
    report.missing_by_column = transform.missing_by_column
    all_rejected: List[RejectedRecord] = validation.rejected + transform.rejected
    report.rejected_messages = [r.summary() for r in all_rejected]
    logger.info("Transform: %d rows ready (%d duplicates removed, %d rejected)",
                transform.rows_out, transform.duplicates_removed,
                transform.rows_rejected)

    # ---- 4. LOAD (single atomic transaction) ------------------------------
    status = "partial" if all_rejected else "success"
    message = (f"Loaded {report.rows_ready} flights; "
               f"{len(all_rejected)} record(s) rejected by validation."
               if all_rejected else f"Loaded {report.rows_ready} flights.")
    try:
        loaded = database.load_batch(
            flights_df,
            source=report.source,
            fetched=report.extracted,
            valid=report.accepted,
            rejected=all_rejected,
            status=status,
            message=message,
            duration_s=round(time.perf_counter() - started, 2),
            db_path=db_path,
        )
    except AppError as exc:
        logger.error("Load failed and was rolled back: %s", exc)
        _log_failure(report.source, str(exc), db_path)
        raise
    report.inserted, report.updated = loaded.inserted, loaded.updated
    report.airports, report.run_id = loaded.airports, loaded.run_id
    logger.info("Load: %d inserted, %d updated, %d airports",
                loaded.inserted, loaded.updated, loaded.airports)

    # ---- 5. VERIFY (SQL checks on what was actually stored) ---------------
    report.verification = database.verify_database(db_path)
    report.flights_in_database = report.verification["flights"]
    if not report.verification["all_checks_passed"]:
        logger.warning("Verification flagged problems: %s", report.verification)

    # ---- artifacts --------------------------------------------------------
    stamp = f"{stamp}_run{report.run_id}"  # unique even within one second
    if save_artifacts:
        report.processed_file = data_processor.save_processed(
            flights_df, name=f"flights_processed_run{report.run_id}")
        report.rejected_file = _write_rejected_csv(all_rejected, stamp)
    report.success, report.status = True, status
    report.message = message
    report.duration_s = round(time.perf_counter() - started, 2)
    if save_artifacts:
        path = config.REPORTS_DIR / f"pipeline_run_{stamp}.json"
        save_json(report.to_dict(), path)
        report.report_file = str(path)
    return report


def replay_raw_files(
    paths: Iterable[Path],
    *,
    rebuild: bool = False,
    db_path=None,
    save_artifacts: bool = True,
) -> List[PipelineReport]:
    """Re-run Transform + Load over archived raw responses, oldest first.

    ``rebuild=True`` first empties the flights/airports tables (the run
    history is kept), so the database is reproduced purely from the archive.
    """
    ordered = sorted(Path(p) for p in paths)
    if rebuild:
        database.clear_flights(db_path)
    return [run_pipeline(raw_file=p, db_path=db_path, save_artifacts=save_artifacts)
            for p in ordered]
