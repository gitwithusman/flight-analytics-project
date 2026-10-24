"""Check every external integration with ONE small request each and print PASS / FAIL.

    python main_task/check_apis.py

Keys come from your .env (never printed). Share the output - it contains no secrets - if something fails.
Checks: AviationStack (flights), FlightAPI (flight search), Open-Meteo forecast + archive (weather, no key).
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import config  # noqa: E402
from src.providers import flightapi, status, weather  # noqa: E402
from src.providers.http import scrub  # noqa: E402


def run(label: str, fn, needs: str = "") -> bool:
    if needs:
        print(f"SKIP  {label}: {needs}")
        return True
    try:
        print(f"PASS  {label}: {fn()}")
        return True
    except Exception as exc:  # report every failure kind (auth, rate limit, network, parsing)
        print(f"FAIL  {label}: {type(exc).__name__}: {scrub(exc)}")
        return False


def main() -> int:
    print(f"search mode: {config.search_mode()}   AviationStack key: {config.mask_secret(config.AVIATIONSTACK_API_KEY)}   "
          f"FlightAPI key: {config.mask_secret(config.FLIGHTAPI_API_KEY)}\n")
    ok = [
        run("AviationStack /v1/flights", status.test_connection, "" if config.api_key_configured() else "no AVIATIONSTACK_API_KEY in .env"),
        run("FlightAPI onewaytrip (2 credits)", flightapi.test_connection,
            "" if config.flightapi_configured() else "no FLIGHTAPI_API_KEY in .env"),
        run("Open-Meteo forecast (Dubai, +3 days)", lambda: _wx(date.today() + timedelta(days=3))),
        run("Open-Meteo archive (Dubai, -30 days)", lambda: _wx(date.today() - timedelta(days=30))),
    ]
    print("\nAll executed checks passed." if all(ok) else "\nSome checks failed - see FAIL lines above.")
    return 0 if all(ok) else 1


def _wx(day: date) -> str:
    r = weather.get_weather(25.2532, 55.3657, day, "Dubai")
    d = r.daily
    return f"{r.kind}: {d.get('temperature_2m_min')}-{d.get('temperature_2m_max')} C, {weather.describe_code(d.get('weather_code'))}"


if __name__ == "__main__":
    raise SystemExit(main())
