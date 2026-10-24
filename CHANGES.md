# SkyLens v2.1.1 - performance release (menu loading / freezing)

Only performance and bug fixes; no menu, feature, API integration or design was removed or redesigned.
Root causes, fixes and measurements: `docs/PERFORMANCE.md`.

* **Fixed:** switching menus rebuilt every chart and table on each click (on the GUI thread) -> pages are rebuilt only when
  their data changed; charts are drawn one at a time after the click; pages are built lazily / while idle.
* **Added:** data warm-up thread, caches (airport reference, weather, derived tables), vectorised airline metrics, faster
  table model, 5 s connect timeout for API calls, cheaper background animation (partial repaint, 20 fps, hero-only fade).
* **API key:** the AviationStack key is now built in (project `.env`, git-ignored); the manual key fields were removed from
  Settings. The FlightAPI key field, both connection tests and all other settings remain. The key you supplied is assumed to be
  an AviationStack key (32 hex characters); it could not be tested live from the build environment.
* **Tests:** 276 pass (41 new performance / regression tests in `tests/test_performance.py`).

---

# SkyLens v2.1 - what changed

Version 2.1 does two things: it **removes the flight-fares feature** and **redesigns the interface**. Nothing else was
removed. All remaining features keep their function.

## 1. Flight fares removed

| Removed | Notes |
|---|---|
| Fare Comparison screen | side-by-side fare comparison, cheapest highlight, fare breakdown |
| Fare Analytics screen | price statistics, distributions, history, airline / route / travel-date charts, price model, alerts tab |
| Fare parts of Flight Search | price column, price sort, price filter, currency selector, "target fare" on saved searches |
| Price alerts | alert checks, `main_task/run_alert_check.py`, `docs/ALERTS.md`, the `alerts` Docker service, `ALERT_CHECK_INTERVAL_MIN` |
| Fare storage and pipeline | tables `fare_observations`, `fare_alerts`; `src/fare_etl.py`, `src/fare_analytics.py`, `src/alerts.py` |
| Fare integrations | Travelpayouts / Aviasales provider (it only returned cached prices); price parsing in the FlightAPI client |
| Fare figures elsewhere | Airline Performance (average fare, fare counts), Route Map (cheapest fare), ETL Monitoring (fare counts), Reports (fare datasets) |
| Fare settings | `FARE_DEFAULT_CURRENCY`, `FARE_FORCE_DEMO`, `TRAVELPAYOUTS_*` (stale entries in an existing `.env` are ignored) |

### Kept (function unchanged)
Flight Search (route, dates, passengers, cabin, direct-only, filters for airline / stops / departure time / duration,
sorting, detail view, **saved searches**, CSV / Excel export), Flight Status and Delays, Airport Analytics, Airline
Performance, Flight Route Map, Destination Weather, Flight Analytics, Flight Explorer, ETL Monitoring, Reports and Export,
Data Management, Settings, About, the terminal menu and the whole ETL + EDA pipeline.

### How Flight Search works now
FlightAPI is still the source of flight options. Only itinerary facts are read (airline, flight number, times, stops,
duration); the API's pricing blocks are ignored and never stored or shown. Without a key the labelled SAMPLE provider is
used. Search results are transient (shown and exported on demand); each search run is logged in ETL Monitoring under the
`flight_search` pipeline. The module `src/offers_view.py` became `src/options_view.py`.

### Decisions to be aware of
* **Fare Comparison was removed entirely**, because it was a price comparison. If you would like a price-free "compare
  flights by duration / stops" view, that can be added.
* Saved searches keep route, dates, passengers and cabin but **lose their target price**.
* A FlightAPI call still needs a currency segment in its URL; a fixed placeholder is sent and nothing derived from it is used.

## 2. Database migration (schema v3 -> v4)
Automatic on first connection: drops the fare tables, rebuilds `saved_searches` without fare columns, renames old
`fares` log rows to `flight_search`. Flights, airports, airlines, routes, rejected records and the other run history are
kept. The delivered `database/flight_airport.db` was migrated (230 flights, integrity checks pass). The old database
can be restored only from your own backup; the migration is not reversible.

## 3. Interface redesign
* Aviation theme: animated sky, clouds, airliners with contrails, airport skyline with tower beacon and runway lights.
  Hero banner per page; every section has its own colour and scene. Modern type stack (Inter / Segoe UI Variable / SF Pro,
  with fallbacks), translucent bars, gradient primary buttons.
* Interactive cards and tiles (hover / focus animation), page fade-in, clickable quick-action tiles on the dashboard.
* Responsive: desktop >= 1020 px, tablet 700-1019 px (icon sidebar), phone < 700 px (slide-in menu). Fixed rows became
  reflowing grids or wrapping rows; minimum window size lowered from 860x560 to 340x480; no page scrolls sideways at
  380, 640, 900 or 1360 px.
* New Settings switch **Reduce animations** (`REDUCE_MOTION`); animations pause on pages that are not visible.
* New app icon (the old SVG carried a large embedded metadata block).
* Background images: the scenery is painted in code. Real photographs can be dropped into `assets/backgrounds/`
  (`noon.jpg`, `dawn.jpg`, `dusk.jpg`, `night.jpg`, `storm.jpg`, `day.jpg`). `preview_*.png` show the built-in scenes.

## 4. Bugs and defects fixed
* "Delay by airline" / "Delay by departure airport" chart labels were clipped at the right edge; the "Delay by hour" title
  was cut off - fixed.
* Many pages could not be narrowed without sideways scrolling (fixed rows, long buttons, long titles) - fixed.
* Unused imports removed in the modules touched. Static analysis (pyflakes) found no undefined names or broken imports; the
  original test-suite and a start-up of the real entry point showed no runtime errors, so no further pre-existing
  runtime defects were found.

## 5. Documents
`Project_Report.docx` / `.pdf` and `Project_Report.pptx` described the earlier ETL + EDA version and contained no fare
content. They keep that history, get a new **Section 16 / two new slides** (what changed), new GUI screenshots,
a refreshed table of contents and the current headline numbers (14 sections, 235 tests). The older copies are in
`archive/`. `README.md`, `docs/API_PROVIDERS.md`, `.env.example`, `docker-compose.yml` were updated.
