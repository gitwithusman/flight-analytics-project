# Flight and Airport Analytics (SkyLens) - v2.1.1

A Python desktop application that combines **flight search**, **flight status and delay analytics**, **airport and
airline dashboards**, an **offline interactive route map** and **destination weather**, on top of a validated **ETL
pipeline** (API -> Pydantic -> pandas -> SQLite) with monitoring, historical storage and exportable reports. Everything on
screen is labelled by origin: **LIVE**, **HISTORICAL** or **SAMPLE DATA** - sample data is never presented as real.

> **Version 2.1.1** fixes slow menu switching (see `docs/PERFORMANCE.md`) and ships the AviationStack key in `.env`.
>
> **Version 2.1** removes the flight-fares feature (fare display, price comparison, fare filters and analytics, price
> alerts, the Travelpayouts integration) and gives the whole interface an aviation-themed, animated and responsive
> design. All other features are unchanged. See `CHANGES.md` for details and for how existing databases are migrated.

| Screen | What it does | Data it uses |
|---|---|---|
| Home Dashboard | KPIs, status mix, data status, interactive quick-action tiles | stored flights |
| Flight Search | route / date / passengers / cabin search, filters (airline, stops, departure time, duration), sorting, detail view, saved searches | FlightAPI flight options or labelled SAMPLE |
| Flight Status and Delays | live status lookup (labelled LIVE) + delay analytics over stored snapshots (labelled HISTORICAL) | AviationStack |
| Airport Analytics | traffic table, detail view per airport, routes, airlines, scope note | stored flights + OurAirports |
| Airline Performance | ranking table with sample sizes, side-by-side comparison, metric definitions | stored flights |
| Flight Route Map | offline map with real coordinates, hover tooltips, click filtering, route details | stored flights + OurAirports + Natural Earth |
| Destination Weather | forecast / current / historical for an airport and date | Open-Meteo |
| ETL Monitoring | pipelines, run history, data-quality indicators, rejected records, redacted log, refresh all sources | refresh_log, rejected_records |
| Reports and Export | CSV / Excel / PDF of exactly the selected rows with filters, period, sources, limitations | everything stored |
| Settings and API | FlightAPI key (masked), flight-search source, animation switch, weather, connection tests (the AviationStack key is built in) | `.env` |

**No API key is needed to try the application:** without a FlightAPI key, Flight Search runs in a clearly labelled
SAMPLE-data mode (fictional carriers). See `docs/API_PROVIDERS.md` for the provider research.

### Look and feel (v2.1)

* **Aviation theme.** Every page opens with a hero banner: an animated scene (dawn, noon, dusk, night or storm sky with
  drifting clouds, airliners with contrails, an airport skyline with a blinking tower beacon and runway lights). Each
  section has its own colour and scene; the content area behind the cards is a live sky.
* **Interactive cards.** Cards and tiles lift, gain a shadow and an accent border on hover or keyboard focus; the Home
  Dashboard tiles open their section (Enter / Space work too). Pages fade in when you navigate.
* **Responsive.** Desktop (>= 1020 px: full sidebar), tablet (700-1019 px: icon sidebar) and phone-width windows
  (< 700 px: slide-in menu drawer, stacked forms, compact headers). No page scrolls sideways down to 340 px.
* **Background images.** The scenery is drawn in code (no image files needed). To use photographs instead, put
  `noon.jpg`, `dawn.jpg`, `dusk.jpg`, `night.jpg`, `storm.jpg` or `day.jpg` in `assets/backgrounds/`; they replace the
  painted sky of that scene and the animated airplanes are drawn on top. `assets/backgrounds/preview_*.png` are stills
  of the built-in scenes.
* **Reduce animations.** Settings -> Appearance (or `REDUCE_MOTION=1` in `.env`) draws the scenery once and disables
  transitions. Animations also pause automatically for pages that are not visible.

---

## 1. Quick start

```bash
# 1. Install dependencies (Python 3.10+)
pip install -r requirements.txt

# 2. Configure API keys (never commit .env) - all optional
copy .env.example .env        # Windows
# cp .env.example .env        # macOS / Linux
#   then edit .env:   AVIATIONSTACK_API_KEY=<flight data / live status>
#                     FLIGHTAPI_API_KEY=<flight search options>
#   (or paste them in the app: Settings and API). Weather needs no key.

# 3. Initialise / inspect the database (safe to run any time)
python main_task/run_pipeline.py --init-db
python main_task/run_pipeline.py --inspect

# 4. Run the ETL pipeline against the live API
python main_task/run_pipeline.py                 # uses DEFAULT_RECORD_LIMIT
python main_task/run_pipeline.py --limit 50 --status active
python main_task/run_pipeline.py --limit 300 --pages 3   # 3 API requests (quota!)

# 4b. ...or WITHOUT an API key / quota: replay the archived real responses
python main_task/run_pipeline.py --replay-raw --rebuild

# 5. Exploratory data analysis from the database (12 figures + findings)
python main_task/run_eda.py                      # or: run_pipeline.py --eda

# 6. Desktop / terminal applications
python main_task/gui_main.py                     # works without any API key (sample-data mode)
python main_task/main.py

# 7. Tests (no network or key needed)
python -m pytest tests/ -v

# 7b. Check every external API with one small request each (prints PASS/FAIL, never prints keys)
python main_task/check_apis.py
```

All commands run from the project root. The notebook is opened with
`jupyter notebook notebooks/ETL_EDA_Analysis.ipynb` (run all cells).

**Reproducing the delivered results:** the delivered database was produced with
`python main_task/run_pipeline.py --replay-raw --rebuild` from the four raw
responses in `data/raw/`. Running that command again gives the same 230 flights;
running it a second time without `--rebuild` inserts 0 new rows.

### Outputs

| Path | Content |
|---|---|
| `database/flight_airport.db` | SQLite database (flights, airports, airlines, routes, saved searches, status observations, refresh_log, rejected_records) |
| `outputs/exports/` | CSV / Excel / PDF exports from the GUI (git-ignored) |
| `data/raw/` | untouched API responses (JSON) - the reproducibility archive |
| `data/processed/` | cleaned CSV snapshots and exports |
| `outputs/reports/pipeline_run_*.json` | per-run report (counts for every stage) |
| `outputs/reports/rejected_records_*.csv` | records Pydantic rejected, with reasons |
| `outputs/reports/validation_stress_test.json` | result of `main_task/demo_validation.py` |
| `outputs/eda/` | `EDA_Findings.md`, `eda_summary.json`, `timestamp_evidence.csv` |
| `visualizations/eda/` | the 12 EDA figures (PNG) |
| `outputs/logs/application.log` | rotating log |

---

## 1a. The ETL pipeline in detail

| Stage | Module | What happens |
|---|---|---|
| Extract | `src/api_client.py` | `GET /v1/flights`; timeout, connection errors and HTTP 5xx are retried with exponential back-off (`MAX_RETRIES`, `RETRY_BACKOFF_SECONDS`); 401/403/429, quota and plan errors fail fast with the provider's message; empty body, non-JSON and malformed payloads raise clear errors; the access key is read from the environment and scrubbed from every error message; each raw response is archived to `data/raw/` |
| Validate | `src/models.py` | Pydantic `FlightRecord` (nested models): status vocabulary, ISO date/timestamps, 3-letter airport / 2-letter airline codes, delay 0-2880 min, lat/lon ranges, "record is identifiable", "has an airport code", "arrival not before departure" (timezone-aware). Output: accepted list + `RejectedRecord` objects with field-level reasons |
| Transform | `src/data_processor.py`, `src/timeutils.py` | flatten nested JSON; trim / blank->NULL / upper-case codes; **convert the API's mislabelled `+00:00` local times to true UTC** (see below); fill a missing airport timezone only from another record of the same airport; derive `route`, `is_delayed`, `max_delay_min`, `scheduled_duration_min`, `dep_local_hour`; drop in-batch duplicates (keep last); never impute missing delays. Second Pydantic gate `FlightRow` checks the flat row. `TRANSFORM_DECISIONS` documents every choice and its justification |
| Load | `src/database.py` | one transaction: `INSERT ... ON CONFLICT(natural key) DO UPDATE`, airports rebuilt from all stored flights, run logged, rejected records archived - all or nothing |
| Verify | `database.verify_database()` | `PRAGMA integrity_check`, foreign-key check, duplicate natural keys, missing identity, bad status, negative delay, airport tallies vs flights |

**Why the timestamps are converted.** AviationStack labels airport-*local* times
with `+00:00`. Evidence (reproducible with `eda.timestamp_semantics_check` and
shown in the notebook, section 3): for all 11 flights carrying both `live.updated`
(true UTC) and a departure time, trusting the suffix puts the live report 7-9 hours
*before* departure, whereas reading the digits as local time puts it 18-48 minutes
after. Reading the suffix literally also made DOH->CMB look like 435 min instead of
285 min. The raw JSON in `data/raw/` is never modified.

### Database schema (SQLite, schema version 4)

* `flights` - `id` PRIMARY KEY; natural key `UNIQUE(flight_date, flight_iata, dep_iata, arr_iata)`;
  `CHECK` constraints on status, delays, flags and local hour; `first_seen_at`, `updated_at`.
* `airports` - `id` PRIMARY KEY, `iata` UNIQUE; derived from stored flights.
* `refresh_log` - one row per pipeline run (fetched / valid / rejected / inserted / updated / status / duration).
* `rejected_records` - audit trail; `run_id` FOREIGN KEY -> `refresh_log(id)`.
* `airlines`, `routes` - derived from stored flights, rebuilt in the same transaction as every flight load.
* `airport_reference` - OurAirports coordinates / names / countries (public domain), loaded once from `data/reference/`.
* `saved_searches` - routes and dates you saved in Flight Search (name, origin, destination, dates, passengers, cabin).
* `flight_status_observations` - live status lookups (labelled `live_api`).
* `refresh_log` has `pipeline` (flights | flight_search) and `data_origin`, so the monitor covers every pipeline.

Databases created by earlier versions are migrated automatically on first
connection (flights and run history are kept; the removed fare tables are dropped and saved searches keep their
route and dates but lose target prices - see `CHANGES.md`). Rows migrated from version 1 still
carry the uncorrected timestamps; run `--replay-raw --rebuild` to regenerate them.

## 2. Data source — AviationStack

**Chosen API:** [AviationStack](https://aviationstack.com) (`/v1/flights`)

Why it was chosen:

- Free tier with a simple `access_key` query parameter — no OAuth.
- Each flight object embeds **departure and arrival airport** details
  (name, IATA/ICAO, terminal, gate, timezone, delay), **airline** info,
  flight status, schedule/actual timestamps and optional live position —
  enough for genuine analytics without extra paid calls.
- Airport records are *derived* from those embedded airport blocks, so the
  Airports page always shows real data from the same source. The paid
  `/v1/airports` directory endpoint is not assumed to be available.

Free-tier limitations handled by the app:

- ~100 requests/month → results are persisted in SQLite between runs.
- No historical data and no delay *causes* → the app never attributes a
  delay to weather unless the source confirms it.
- Lookup endpoints (`/airports`, `/routes`) may return
  `function_access_restricted` on the free plan → handled gracefully.

**Optional weather context:** [Open-Meteo](https://open-meteo.com) (free, no
key) can display current weather for a location you configure in Settings
(`WEATHER_LATITUDE` / `WEATHER_LONGITUDE` / `WEATHER_LABEL`). It is purely
informational.

### Getting an API key

1. Register free at https://aviationstack.com and copy your access key.
2. Create `.env` from `.env.example` and set `AVIATIONSTACK_API_KEY`.
3. Alternatively paste it in the GUI **Settings** page (it is stored in
   `.env` and never displayed in full).

---

## 3. What the application does

### Terminal app (`main_task/main.py`)

Numbered menu covering: overview, data retrieval with optional API filters
(status, dep/arr IATA, airline, flight number, limit), flight/airport
record viewers, search & filters, statistics, full exploratory analysis
(missing values, duplicates, top airlines/airports/routes, departure-hour
patterns, numeric summary), chart generation (saved as PNG), database
inspection, CSV/JSON export and configuration status. All input is
validated and all errors produce readable messages.

### Desktop app (`main_task/gui_main.py`)

| Page            | Contents |
|-----------------|----------|
| Dashboard       | Live metric cards (flights, airports, airlines, delayed, routes, last refresh), empty state with retrieve action, quick navigation |
| Flights         | Sortable/searchable table with status filter and "delayed only" toggle |
| Airports        | Searchable airport table derived from real flight data |
| Search          | Field-aware search + status/route/delay filters, clear button, match counts |
| Analytics       | Metric cards + live analysis tables |
| Visualizations  | Seven chart types, regenerate + save PNG |
| Data Management | Retrieval with filters, DB status, export to CSV/JSON |
| Settings        | Masked API-key handling, weather lookup options |
| About           | Version, description, credits |

A **flight-conditions status bar** at the bottom shows colour-coded counts
(On Time, Delayed, Cancelled, Weather Alert, Weather Delay, Landed, Status
Unknown) computed from actual stored rows, refreshed after every retrieval.
Network work runs on background threads so the UI stays responsive.

---

## 4. Project structure

```
Flight_Airport_Analytics/
├── main_task/
│   ├── run_pipeline.py      # ETL command line (run / replay / init / inspect)
│   ├── run_eda.py           # structured EDA from the database
│   ├── demo_validation.py   # validation stress test (synthetic defects)
│   ├── main.py              # terminal entry point
│   └── gui_main.py          # PySide6 desktop entry point (thin launcher)
├── notebooks/
│   └── ETL_EDA_Analysis.ipynb   # executed ETL audit + EDA notebook
├── src/
│   ├── __init__.py
│   ├── config.py            # paths, .env loading, settings
│   ├── api_client.py        # AviationStack + Open-Meteo HTTP clients (retries, paging)
│   ├── models.py            # Pydantic gates, ValidationReport, RejectedRecord
│   ├── timeutils.py         # airport-local -> UTC conversion
│   ├── data_processor.py    # pandas cleaning / derived columns / TRANSFORM_DECISIONS
│   ├── pipeline.py          # Extract -> Validate -> Transform -> Load -> Verify
│   ├── database.py          # SQLite schema v2, migration, upsert, verification
│   ├── eda.py               # structured EDA (statistics, outliers, findings)
│   ├── eda_charts.py        # the 12 EDA figures
│   ├── analytics.py         # statistics & insights
│   ├── visualizations.py    # matplotlib chart registry (light theme)
│   ├── service.py           # thin wrapper over pipeline.run_pipeline for the GUIs
│   ├── palette.py           # shared design tokens (colours) for GUI + charts
│   ├── gui/                 # PySide6 front end
│   │   ├── main_window.py   # navigation, header, status bar, refresh workflow
│   │   ├── pages.py         # the nine pages
│   │   ├── widgets.py       # cards, KPI tiles, responsive grid, charts, banner
│   │   ├── tables.py        # table model with numeric sorting + search helpers
│   │   ├── theme.py         # stylesheet built from the design tokens
│   │   ├── workers.py       # background tasks with GUI-thread callbacks
│   │   ├── store.py         # cached database view shared by all pages
│   │   └── icons.py         # built-in SVG line icons
│   └── utils.py             # logging, error types, helpers
├── data/
│   ├── raw/                 # untouched API responses (JSON)
│   └── processed/           # cleaned CSV datasets & exports
├── database/
│   └── flight_airport.db    # SQLite database (created on first run)
├── visualizations/          # generated PNG charts (eda/ = the 12 EDA figures)
├── assets/                  # icons / images
├── tests/                   # pytest suite (no network required)
├── outputs/logs/            # application.log
├── .env.example             # configuration template (no secrets)
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 5. Deduplication and re-running

The natural uniqueness key is `(flight_date, flight_iata, dep_iata, arr_iata)`.
Loading is a true upsert, so re-running the pipeline refreshes existing flights
(`updated`) instead of duplicating them (`inserted`), and keeps each row's `id`
and `first_seen_at`. Flights without an identifier are rejected rather than
stored under an empty key. Both counts are printed after each run, stored in
`refresh_log`, and shown in the GUI.

---

## 6. Configuration reference (`.env`)

| Variable | Purpose | Required |
|---|---|---|
| `AVIATIONSTACK_API_KEY` | your AviationStack access key | yes, for retrieval |
| `FLIGHTAPI_API_KEY` | FlightAPI key (flight search options; get it from your FlightAPI dashboard) - empty = SAMPLE flights | no |
| `SEARCH_FORCE_DEMO` | `1` = always use SAMPLE flights in Flight Search | no (0) |
| `REDUCE_MOTION` | `1` = no animated background / transitions | no (0) |
| `AVIATIONSTACK_BASE_URL` | API base URL — free plan **requires `http://`**, paid plans may use `https://` | no |
| `REQUEST_TIMEOUT` | HTTP timeout in seconds | no (20) |
| `MAX_RETRIES` / `RETRY_BACKOFF_SECONDS` | retries for timeouts / 5xx and back-off base | no (3 / 2) |
| `DEFAULT_RECORD_LIMIT` | rows fetched per refresh | no (100) |
| `ENABLE_WEATHER_LOOKUP` | `1`/`0` — show weather chip in GUI | no |
| `WEATHER_LATITUDE` / `WEATHER_LONGITUDE` | coordinates for weather lookup | no |
| `WEATHER_LABEL` | display name of the monitored location | no |

---

## 7. Tests

```bash
python -m pytest tests/ -v          # no network or API key needed
```

| File | Covers |
|---|---|
| `test_validation.py`, `test_validation_and_transform.py` | every Pydantic rule (field-level reasons), timezone-aware consistency, second gate, timezone conversion and filling, transform report, timestamp evidence |
| `test_pipeline.py` | end-to-end pipeline on raw files, idempotent re-run, rejected records persisted, in-batch duplicates, empty / malformed input, atomic rollback, run logging, API retries / back-off / no retry on auth errors, empty body, HTML body, key redaction, pagination |
| `test_database.py`, `test_database_v2.py` | CRUD, constraints (CHECK / UNIQUE / FOREIGN KEY), upsert semantics, migration from the v1 schema, integrity verification |
| `test_eda.py` | EDA reads from SQLite, IQR outliers, z-test, generated findings, figures + summary written, empty database |
| `test_data_processor.py`, `test_analytics.py` | flattening, derived columns, airports, statistics, chart builders |
| `test_travel_backend.py` | query validation, FlightAPI request / payload parsing (pricing blocks ignored) / error mapping / retries / secret scrubbing (mocked HTTP), sample provider, flight-option validation rules, flight-search ETL (derived arrival, de-duplication, audit, raw archive, failure logging), options view (filters, sorting), saved searches, **schema v3 -> v4 migration**, a guard that no fare code or table remains, airline / airport / route / delay analytics, ETL monitor, weather classification and endpoints, live status mapping, CSV / Excel / PDF exports |
| `test_gui_travel.py` | headless GUI workflows: Flight Search (validation, filters, sorting, provider failure, empty result, saved searches, export equals displayed rows), a sweep proving no fare / price text appears on any screen, airport / airline / status / ETL / reports pages, route-map hit-testing, weather states, settings, overlap prevention |
| `test_performance.py` | lazy pages, reload guards, deferred chart rendering, render queue, caches (weather, airport reference, memo), vectorised airline table equals the old loop, table model, log tail, HTTP timeouts, idle CPU, sky partial repaint, built-in key |
| `test_gui_redesign.py` | responsive layout (desktop / tablet / phone, no sideways scrolling on any page), mobile drawer, hero banners and per-section styling, quick-action tiles, animation switch, every scene renders, photo override, flow layout |
| `test_gui_smoke.py`, `test_regressions.py` | headless PySide6 widgets, threading, previously fixed bugs |

Tests use temporary databases and directories and never touch project data.
On a machine without a display set `QT_QPA_PLATFORM=offscreen` (the GUI tests do this).

---

## 8. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| "No AVIATIONSTACK_API_KEY configured" | Create `.env` from `.env.example` and add your key, or use GUI → Settings. |
| "API key missing" although `.env` has a key | Older versions failed on a `.env` saved with a UTF-8 BOM; this is fixed — re-save the key in GUI → Settings if it persists. |
| Refresh fails with `HTTP 403` | The error text now shows the provider's reason. Free plans typically cap *Records* at 100 per request. |
| "API usage limit reached" | Free tier ≈100 requests/month; wait for reset or upgrade. Stored data keeps working. |
| "Endpoint not available on this plan" | You hit a paid endpoint; the app only needs `/v1/flights`. |
| "https_access_restricted" error | Free plan is HTTP-only — keep `AVIATIONSTACK_BASE_URL=http://...` in `.env`. |
| Charts look empty | No records stored yet — retrieve data first. |
| GUI does not start | `pip install PySide6`, then run from the project root. |
| Old data shown after a failed refresh | By design — the last refresh status is shown in Dashboard / Data pages. |
| `Request ... failed after 4 attempts` | Network/server problem; the pipeline retried with back-off. Check your connection, then re-run. Failed runs are recorded in `refresh_log`. |
| Many records rejected | See `outputs/reports/rejected_records_*.csv` or `run_pipeline.py --inspect`; each row states the failed field and reason. |
| Durations/hours look different from an older database | Older rows hold uncorrected timestamps - run `python main_task/run_pipeline.py --replay-raw --rebuild`. |

---

## 9. Docker (CLI / ETL / tests)

```bash
docker build -t skylens .
docker run --rm skylens                                             # runs the test-suite
docker compose run --rm pipeline --inspect                          # database overview
```

The image runs the pipeline, EDA and tests headlessly; database, raw archive and outputs live in named volumes.
The desktop GUI can be forwarded to a Linux X server (`docker compose --profile gui up gui`, needs `xhost +local:docker`);
on Windows / macOS run the GUI natively (`python main_task/gui_main.py`).
**Status: the Dockerfile and Compose file were written but have not been built or run in the development environment
(no Docker daemon was available) - treat them as untested until you run the commands above.**
