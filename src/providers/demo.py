"""Clearly-labelled SAMPLE flight generator (demonstration mode).

Used only when no flight-search API key is configured (or the user forces it).
Every row it produces carries ``data_origin = 'sample'`` and fictional carriers
(``SA``, ``DM``, ``TJ``, ``EX``) so a sample flight can never be mistaken for a
real one. Distances use the real airport coordinates; times and availability
are synthetic.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, time, timedelta, timezone
from typing import List, Optional

from .. import reference
from .base import FlightFetchResult, FlightQuery

SOURCE = "demo"
CARRIERS = [("SA", "Sample Air"), ("DM", "Demo Airways"), ("TJ", "Test Jet"), ("EX", "Example Express")]


def _seed(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def _distance_km(origin: str, destination: str, db_path=None) -> float:
    a, b = reference.lookup(origin, db_path), reference.lookup(destination, db_path)
    if not a or not b:
        return 1500.0
    return reference.haversine_km(a["latitude"], a["longitude"], b["latitude"], b["longitude"])


def make_options(q: FlightQuery, retrieved_at: datetime, db_path=None, count: int = 9) -> List[dict]:
    km = _distance_km(q.origin, q.destination, db_path)
    rng = random.Random(_seed(q.origin, q.destination, q.departure_date, retrieved_at.date()))
    options = []
    for i in range(count):
        code, _name = CARRIERS[i % len(CARRIERS)]
        stops = rng.choices([0, 1, 2], weights=[5, 4, 1])[0] if km > 800 else rng.choices([0, 1], [8, 1])[0]
        if q.direct_only:
            stops = 0
        dep = datetime.combine(q.departure_date, time(rng.randint(5, 22), rng.choice([0, 15, 30, 45])),
                               tzinfo=timezone.utc)
        duration = int(km / 800 * 60 + 35 + stops * 95 + rng.randint(-10, 15))
        options.append({
            "origin_iata": q.origin, "destination_iata": q.destination,
            "departure_at": dep.isoformat(),
            "return_at": datetime.combine(q.return_date, time(rng.randint(6, 21), 0),
                                          tzinfo=timezone.utc).isoformat() if q.return_date else None,
            "airline_iata": code, "flight_number": f"{code}{rng.randint(100, 989)}",
            "stops": stops, "duration_min": duration,
            "arrival_at": (dep + timedelta(minutes=duration)).isoformat(), "arrival_derived": 0,
            "baggage": rng.choice(["1 x 23 kg checked (sample)", "Cabin bag only (sample)", "2 x 23 kg checked (sample)"]),
            "cabin": q.cabin, "booking_url": None, "source": SOURCE, "data_origin": "sample",
        })
    options.sort(key=lambda o: o["departure_at"])
    return options[: q.max_results]


class DemoFlightProvider:
    name = "Demonstration data (SAMPLE - not real flights)"
    data_origin = "sample"
    configured = True

    def __init__(self, db_path=None):
        self._db = db_path

    def search(self, q: FlightQuery, retrieved_at: Optional[datetime] = None) -> FlightFetchResult:
        now = retrieved_at or datetime.now(timezone.utc)
        return FlightFetchResult(
            options=make_options(q, now, self._db), source=SOURCE, data_origin="sample",
            retrieved_at=now,
            notes=["SAMPLE DATA: these are not real flights or availability. Add a FlightAPI key in Settings "
                   "to retrieve real flight options."])
