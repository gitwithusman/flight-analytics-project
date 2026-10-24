"""Airport reference data (coordinates, city, country) and geometry helpers.

Coordinates come exclusively from ``data/reference/airports_reference.csv``
(OurAirports, public domain - see ``data/reference/SOURCES.md``). Nothing in
the application estimates or invents airport locations.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import math
import sqlite3
from typing import Optional, Tuple

import pandas as pd

from . import config
from .utils import get_logger

logger = get_logger()
REFERENCE_CSV = config.REFERENCE_DIR / "airports_reference.csv"
LAND_GEOJSON = config.REFERENCE_DIR / "world_land_110m.geojson"
_COLUMNS = ["iata", "icao", "name", "city", "country_code", "country",
            "latitude", "longitude", "elevation_ft", "airport_type"]


_LOAD_LOCK = threading.Lock()


def ensure_loaded(conn: sqlite3.Connection) -> int:
    """Load the reference CSV into ``airport_reference`` once (idempotent, safe from several threads)."""
    count = conn.execute("SELECT COUNT(*) FROM airport_reference").fetchone()[0]
    if count or not REFERENCE_CSV.exists():
        return int(count)
    with _LOAD_LOCK:                       # the start-up warm-up thread and the GUI thread may both arrive here
        count = conn.execute("SELECT COUNT(*) FROM airport_reference").fetchone()[0]
        if count:
            return int(count)
        return _load_reference(conn)


def _load_reference(conn: sqlite3.Connection) -> int:
    df = pd.read_csv(REFERENCE_CSV, dtype=str, keep_default_na=False)
    rows = []
    for r in df.itertuples(index=False):
        try:
            lat, lon = float(r.latitude), float(r.longitude)
        except ValueError:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or len(r.iata) != 3:
            continue
        elev = float(r.elevation_ft) if r.elevation_ft not in ("", "nan") else None
        rows.append((r.iata.upper(), r.icao or None, r.name or None, r.city or None,
                     r.country_code or None, r.country or None, lat, lon, elev,
                     r.airport_type or None))
    conn.executemany(
        "INSERT OR IGNORE INTO airport_reference (iata, icao, name, city, country_code, "
        "country, latitude, longitude, elevation_ft, airport_type) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows)
    logger.info("Loaded %d airports into airport_reference", len(rows))
    return len(rows)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(a)))


def great_circle_points(lat1: float, lon1: float, lat2: float, lon2: float,
                        n: int = 48) -> Tuple[list, list]:
    """Points along the great-circle arc (longitudes unwrapped for plotting)."""
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    d = 2 * math.asin(min(1.0, math.sqrt(math.sin((p2 - p1) / 2) ** 2
                                         + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2)))
    if d == 0:
        return [lon1], [lat1]
    lons, lats = [], []
    for i in range(n + 1):
        f = i / n
        a, b = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
        x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
        y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
        z = a * math.sin(p1) + b * math.sin(p2)
        lats.append(math.degrees(math.atan2(z, math.hypot(x, y))))
        lons.append(math.degrees(math.atan2(y, x)))
    # unwrap so an arc crossing the date line is drawn continuously
    for i in range(1, len(lons)):
        while lons[i] - lons[i - 1] > 180:
            lons[i] -= 360
        while lons[i] - lons[i - 1] < -180:
            lons[i] += 360
    return lons, lats


_REF_CACHE: dict = {}
_REF_LOCK = threading.Lock()


def _db_stamp(db_path=None):
    """(path, mtime, size) of the database and its journal files: changes whenever anything is written."""
    from . import config
    path = Path(db_path or config.DATABASE_PATH)
    stamp = [str(path)]
    for suffix in ("", "-wal", "-journal"):
        try:
            st = os.stat(str(path) + suffix)
            stamp += [st.st_mtime_ns, st.st_size]
        except OSError:
            stamp += [0, 0]
    return tuple(stamp)


def airport_reference(db_path=None) -> pd.DataFrame:
    """The whole reference table as a DataFrame (cached until the database file changes)."""
    from . import database
    stamp = _db_stamp(db_path)
    with _REF_LOCK:
        cached = _REF_CACHE.get(stamp[0])
        if cached is not None and cached[0] == stamp:
            return cached[1].copy()
    with database.connect(db_path) as conn:
        ensure_loaded(conn)
        frame = pd.read_sql_query("SELECT * FROM airport_reference ORDER BY iata", conn)
    stamp = _db_stamp(db_path)           # ensure_loaded may have just written the table
    with _REF_LOCK:
        _REF_CACHE[stamp[0]] = (stamp, frame)
    return frame.copy()


def lookup(iata: Optional[str], db_path=None) -> Optional[dict]:
    """One airport's reference record, or None when unknown."""
    if not iata:
        return None
    from . import database
    with database.connect(db_path) as conn:
        ensure_loaded(conn)
        row = conn.execute("SELECT * FROM airport_reference WHERE iata = ?",
                           (iata.strip().upper(),)).fetchone()
    return dict(row) if row else None


def search_airports(text: str, limit: int = 12, db_path=None) -> pd.DataFrame:
    """Case-insensitive search by IATA / name / city (for autocomplete)."""
    from . import database
    t = f"%{text.strip().upper()}%"
    with database.connect(db_path) as conn:
        ensure_loaded(conn)
        return pd.read_sql_query(
            "SELECT iata, name, city, country, latitude, longitude FROM airport_reference "
            "WHERE UPPER(iata) = ? OR UPPER(name) LIKE ? OR UPPER(city) LIKE ? "
            "ORDER BY (UPPER(iata) = ?) DESC, (airport_type = 'large_airport') DESC, name LIMIT ?",
            conn, params=(text.strip().upper(), t, t, text.strip().upper(), limit))


def with_coordinates(df: pd.DataFrame, code_col: str, prefix: str,
                     ref: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Add ``{prefix}_lat`` / ``{prefix}_lon`` columns from the reference data."""
    ref = airport_reference() if ref is None else ref
    lut = ref.set_index("iata")[["latitude", "longitude"]]
    out = df.copy()
    out[f"{prefix}_lat"] = out[code_col].map(lut["latitude"])
    out[f"{prefix}_lon"] = out[code_col].map(lut["longitude"])
    return out
