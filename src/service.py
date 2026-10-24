"""Application service layer shared by the terminal app and the GUI.

This module wires the full data flow together:

    API request -> Pydantic validation -> Pandas transformation
    -> SQLite loading -> refresh log

Keeping it in one place guarantees both applications perform exactly the
same steps when the user asks for fresh data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from . import database, pipeline
from .utils import AppError, get_logger

logger = get_logger()


@dataclass
class RefreshResult:
    """Outcome of a retrieve-and-store cycle."""

    success: bool
    message: str
    fetched: int = 0
    valid: int = 0
    invalid: int = 0
    stored: int = 0
    airports_stored: int = 0
    validation_errors: List[str] = field(default_factory=list)
    processed_file: Optional[str] = None
    inserted: int = 0
    updated: int = 0
    report_file: Optional[str] = None


def refresh_data(
    limit: int = 100,
    flight_status: Optional[str] = None,
    dep_iata: Optional[str] = None,
    arr_iata: Optional[str] = None,
    airline_name: Optional[str] = None,
    flight_number: Optional[str] = None,
    db_path=None,
) -> RefreshResult:
    """Retrieve flights from the API, validate, transform and store them.

    Thin wrapper over :func:`src.pipeline.run_pipeline` that keeps the
    interface used by the terminal app and the GUI. Raises ``AppError``
    subclasses for hard failures (no key, network down, quota exhausted);
    validation problems degrade gracefully.
    """
    report = pipeline.run_pipeline(
        limit=limit,
        flight_status=flight_status,
        dep_iata=dep_iata,
        arr_iata=arr_iata,
        airline_name=airline_name,
        flight_number=flight_number,
        db_path=db_path,
    )
    return RefreshResult(
        success=report.success,
        message=report.message,
        fetched=report.extracted,
        valid=report.accepted,
        invalid=report.rejected_total,
        stored=report.inserted + report.updated,
        airports_stored=report.airports,
        validation_errors=report.rejected_messages,
        processed_file=report.processed_file,
        inserted=report.inserted,
        updated=report.updated,
        report_file=report.report_file,
    )


def load_stored_flights(**filters) -> pd.DataFrame:
    """Read stored flights through the same path as the database module."""
    return database.fetch_flights(**filters)


def dataset_available(db_path=None) -> bool:
    """True when the database already contains usable flight records."""
    try:
        return database.count_rows("flights", db_path) > 0
    except AppError:
        return False
