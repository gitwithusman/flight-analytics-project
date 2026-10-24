# SkyLens v2.1.1 - performance notes

## Symptom
Opening or switching menus took a noticeable moment and the window stuttered or briefly froze.

## Root causes (found by profiling, measured on the shipped data)
| # | Cause | Effect |
|---|---|---|
| 1 | `navigate()` called `page.reload()` on **every** click. Four pages (Delays, Airports, Airlines, Route Map) had no guard, so each visit rebuilt every Matplotlib chart and table. | 150-300 ms per click, all on the GUI thread |
| 2 | Charts were built and drawn **inside the click handler**, all in one block. | one long freeze per page |
| 3 | **No caching**: the airport reference table (9,051 rows) was re-read from SQLite on every use; weather was re-requested on every visit; the log file was scanned from the start on every ETL visit. | repeated database / network / file work |
| 4 | Table model looked every cell up in the DataFrame (`.iat`) for display, alignment and **each sort comparison**. | 134 rows cost ~130 ms to fill and sort |
| 5 | The airline metrics were computed with a per-airline pandas loop. | ~110 ms per visit |
| 6 | All 14 pages were built before the window appeared. | slow start-up |
| 7 | The animated sky repainted the **whole page 25 times a second** (so every chart and table repainted too) and the page fade re-rasterised the whole page. | 26-55 % of a CPU core while idle, jank during transitions |

Network requests were already made on worker threads, so they were not what froze the window.

## Fixes
1. **Reload guard** (`PageBase.reload_if_needed`): a page is rebuilt only when the data it shows changed (data version, plus the run history for ETL Monitoring). Cheap, settings-dependent pages (Flight Search, Weather, Data, Settings, About) stay "volatile" and refresh on every visit.
2. **Render queue** (`src/gui/perf.py`): charts and the route map are drawn one at a time from the event loop, latest request per chart wins, hidden pages are drawn only when shown, and a small "Preparing chart..." placeholder shows meanwhile.
3. **Lazy pages**: only the Home page is built at start; the rest are built while the app is idle in the first seconds (or on first click, whichever comes first).
4. **Data warm-up**: one short-lived worker thread loads flights, airports, database info, the airport reference and the basemap during start-up, behind a lock (no duplicate loads). Derived tables (airline metrics, airport traffic, routes) are memoised per data version.
5. **Caches** (`src/cache.py`): airport reference (invalidated when the database file changes), status-bar weather (10 min, failures back off for 1 min, concurrent callers share one request), destination weather (forecast 10 min, history 24 h; errors are never cached).
6. **Faster code paths**: vectorised airline table (identical output, verified against the old loop on the shipped data and random frames); table model precomputes alignment and sort keys once; the log tail reads only the end of the file.
7. **Cheaper animation**: the content-area sky repaints only the small rectangles where clouds / planes move, at 20 fps, and pauses while charts are being drawn; the page transition fades only the small header banner. "Reduce animations" in Settings still switches everything off.
8. **Error handling**: HTTP calls use a 5 s connect timeout (a dead network fails in seconds) with the existing retry / back-off; all API calls stay on worker threads; failures never raise into the UI.

## Measured results (same machine, shipped data, Qt offscreen)
| | Before | After |
|---|---|---|
| Revisiting Delays / Airports / Airlines / Map | 150-300 ms each | 9-21 ms |
| Revisiting any other page | 7-50 ms | 7-20 ms |
| Page content drawn inside the click | whole page (100-300 ms) | table / data only; charts one by one afterwards |
| Idle CPU with animation (one core) | 26-55 % | 15-22 % |
| Airport reference lookup | 132 ms every time | 0.6 ms (cached) |
| Airline table | ~110 ms | ~40 ms, memoised |
| Window construction (`MainWindow()`) | ~560 ms | ~180 ms |

First visit of a data-heavy page still costs 70-260 ms of synchronous data preparation (table fill, filters); the charts then appear one at a time without blocking input. Each Matplotlib chart redraws once more just after it is first shown, when it settles to its final size.

Numbers come from a headless run on a Linux sandbox and will differ on your machine; the relative improvement is the point.
