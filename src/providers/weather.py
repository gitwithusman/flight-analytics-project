"""Destination weather from Open-Meteo (no API key; non-commercial use).

Terms (open-meteo.com): free for non-commercial use under ~10,000 calls/day;
data under CC BY 4.0 -> the attribution below must be shown wherever the data
is displayed. Forecasts reach 16 days ahead; the historical archive (ERA5)
reaches back to 1940 with a delay of a few days.
"""

from __future__ import annotations

import copy

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from ..utils import APIError, get_logger
from ..cache import TTLCache
from .http import get_json

logger = get_logger()
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY_FORECAST = ("weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
                  "precipitation_probability_max,wind_speed_10m_max")
DAILY_ARCHIVE = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"
ARCHIVE_LAG_DAYS = 6          # ERA5 values appear a few days late
FORECAST_HORIZON_DAYS = 15    # today + 15 = the 16th forecast day

WMO = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
       51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle", 56: "Freezing drizzle", 57: "Dense freezing drizzle",
       61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Heavy freezing rain",
       71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Rain showers",
       81: "Heavy showers", 82: "Violent showers", 85: "Snow showers", 86: "Heavy snow showers",
       95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm with hail"}


_RESULT_CACHE = TTLCache(default_ttl=600.0, max_items=128)


def describe_code(code) -> str:
    try:
        return WMO.get(int(code), f"Weather code {int(code)}")
    except (TypeError, ValueError):
        return "Unknown"


@dataclass
class WeatherResult:
    kind: str                       # forecast | current | recent | historical | unavailable
    label: str
    latitude: float
    longitude: float
    target_date: date
    daily: Dict[str, object] = field(default_factory=dict)
    current: Optional[Dict[str, object]] = None
    notes: List[str] = field(default_factory=list)
    attribution: str = ATTRIBUTION

    @property
    def available(self) -> bool:
        return self.kind != "unavailable"


def classify(target: date, today: Optional[date] = None) -> str:
    """Which kind of weather data applies to ``target``."""
    today = today or date.today()
    if target < today - timedelta(days=ARCHIVE_LAG_DAYS):
        return "historical"
    if target < today:
        return "recent"
    if target == today:
        return "current"
    if target <= today + timedelta(days=FORECAST_HORIZON_DAYS):
        return "forecast"
    return "unavailable"


def _daily_row(daily: dict, target: date) -> Dict[str, object]:
    times = daily.get("time") or []
    iso = target.isoformat()
    if iso not in times:
        return {}
    i = times.index(iso)
    return {k: (v[i] if isinstance(v, list) and i < len(v) else None) for k, v in daily.items() if k != "time"}


def get_weather(latitude: float, longitude: float, target: date, label: str = "",
                today: Optional[date] = None) -> WeatherResult:
    """Weather for one place and date, honouring provider limits."""
    today = today or date.today()
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Latitude / longitude are out of range.")
    kind = classify(target, today)
    cache_key = (round(latitude, 3), round(longitude, 3), target.isoformat(), kind, label)
    cached = _RESULT_CACHE.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)
    result = _get_weather_uncached(latitude, longitude, target, label, kind)
    if result.kind != "unavailable" or kind == "unavailable":
        # history never changes; forecasts are reused briefly. Failures raise and are never cached.
        _RESULT_CACHE.set(cache_key, copy.deepcopy(result), ttl=86400.0 if kind == "historical" else 600.0)
    return result


def _get_weather_uncached(latitude: float, longitude: float, target: date, label: str, kind: str) -> WeatherResult:
    res = WeatherResult(kind=kind, label=label or f"{latitude:.2f}, {longitude:.2f}",
                        latitude=latitude, longitude=longitude, target_date=target)
    if kind == "unavailable":
        res.notes.append(f"Open-Meteo forecasts reach {FORECAST_HORIZON_DAYS + 1} days ahead; "
                         f"{target.isoformat()} is beyond that, so no forecast is shown.")
        return res
    if kind == "historical":
        payload = get_json(ARCHIVE_URL, params={
            "latitude": latitude, "longitude": longitude, "start_date": target.isoformat(),
            "end_date": target.isoformat(), "daily": DAILY_ARCHIVE, "timezone": "auto"},
            provider="Open-Meteo archive")
        res.notes.append("Historical weather (ERA5 reanalysis) - what the weather WAS, not a forecast.")
    else:
        params = {"latitude": latitude, "longitude": longitude, "daily": DAILY_FORECAST,
                  "timezone": "auto", "forecast_days": FORECAST_HORIZON_DAYS + 1}
        if kind in ("recent", "current"):
            params["past_days"] = 7
            params["current"] = "temperature_2m,weather_code,wind_speed_10m,precipitation"
        payload = get_json(FORECAST_URL, params=params, provider="Open-Meteo")
        if kind == "forecast":
            res.notes.append("Forecast - conditions can change and do not guarantee flight operations.")
        elif kind == "recent":
            res.notes.append("Recent past from the forecast model's analysis (reanalysis archive lags a few days).")
        else:
            res.notes.append("Current conditions plus today's forecast.")
    if not isinstance(payload, dict) or "daily" not in payload:
        raise APIError("Open-Meteo returned an unexpected response.")
    res.daily = _daily_row(payload["daily"], target)
    if not res.daily:
        res.notes.append("The provider returned no data for this date.")
        res.kind = "unavailable"
    if kind in ("current",) and isinstance(payload.get("current"), dict):
        res.current = payload["current"]
    return res
