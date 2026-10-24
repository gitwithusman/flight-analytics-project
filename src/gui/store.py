"""Shared, cached view of the database for all GUI pages.

Pages used to query SQLite (and rebuild charts) every time they were shown,
each with a different row limit. The store reads once per data version, so
every page sees the same rows and navigation is instant. ``warm()`` loads
everything in a worker thread right after start-up so the first visit to a page
does not wait for the database either. All loads are guarded by a lock: a page
asking while the warm-up runs waits for that single load instead of repeating it.
"""

from __future__ import annotations

import threading
from typing import Optional

import pandas as pd

from src import database, reference

ROW_LIMIT = 100_000  # effectively "all rows" for this application's scale


class DataStore:
    def __init__(self) -> None:
        self.version = 0          # bumped when stored flights / airports change (after a refresh)
        self.runs_version = 0     # bumped when the run history changes (a search or refresh was logged)
        self._lock = threading.RLock()
        self._flights: Optional[pd.DataFrame] = None
        self._airports: Optional[pd.DataFrame] = None
        self._info: Optional[dict] = None
        self._memo: dict = {}

    def memo(self, name: str, factory):
        """Derived tables (airline metrics, airport traffic, routes): computed once per data version."""
        with self._lock:
            if name not in self._memo:
                self._memo[name] = factory()
            value = self._memo[name]
        return value.copy() if isinstance(value, pd.DataFrame) else value

    def invalidate(self) -> None:
        """Call after the database changed (refresh finished)."""
        with self._lock:
            self.version += 1
            self.runs_version += 1
            self._flights = self._airports = self._info = None
            self._memo = {}

    def bump_runs(self) -> None:
        """A pipeline run was logged without changing flights (e.g. a flight search)."""
        self.runs_version += 1

    def flights(self) -> pd.DataFrame:
        with self._lock:
            if self._flights is None:
                self._flights = database.fetch_flights(limit=ROW_LIMIT)
            return self._flights

    def airports(self) -> pd.DataFrame:
        with self._lock:
            if self._airports is None:
                self._airports = database.fetch_airports()
            return self._airports

    def info(self) -> dict:
        with self._lock:
            if self._info is None:
                self._info = database.database_info()
            return self._info

    def warm(self) -> None:
        """Load everything pages need (runs in a worker thread; failures are harmless - pages load on demand)."""
        try:
            self.flights()
            self.airports()
            self.info()
            reference.airport_reference()
            from src.gui.pages_map import land_polygons   # parse the basemap once, off the GUI thread
            land_polygons()
        except Exception:                                  # noqa: BLE001 - warm-up is best effort
            pass
