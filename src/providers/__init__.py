"""External data providers (flight search, flight status, weather).

Every provider is isolated from the GUI and analytics code and returns plain
Python / pandas objects tagged with a ``data_origin`` so the UI can always say
whether a result is LIVE, HISTORICAL or SAMPLE.
"""

from .base import (  # noqa: F401  (re-exported public API)
    DATA_ORIGIN_LABELS,
    FlightFetchResult,
    FlightQuery,
    FlightQueryError,
    validate_query,
)
