# SkyLens v2.1 - testing summary

Environment: Linux sandbox, Python 3.12, PySide6 6.12 (Qt offscreen platform), no outbound access to the flight / weather APIs.

## Automated suite - 276 passed, 0 failed (about 95 s)
| File | Tests | Focus |
|---|---|---|
| test_performance.py | 41 | **v2.1.1**: lazy pages, reload guards (6 pages), deferred chart rendering, render queue, hidden-page rendering, event-loop responsiveness, TTL / weather / reference caches, store memo, vectorised airline table equals the old loop (12 random frames), table model, log tail, HTTP timeouts, idle CPU, sky partial repaint, built-in key |
| test_travel_backend.py | 67 | FlightAPI request / parsing (price blocks ignored) / errors / retries / key scrubbing, sample provider, flight-option validation, search ETL, saved searches, **v3 -> v4 migration**, no-fare guard, analytics, weather, status, exports |
| test_gui_travel.py | 28 | Flight Search workflows, saved searches, export equals displayed rows, **no fare / price / cheapest text on any screen**, operations pages, settings |
| test_gui_redesign.py | 17 | **desktop / tablet / phone layouts, no sideways scrolling on all 14 pages at 380 / 900 / 1360 px**, mobile drawer, hero banners per section, tiles, animation switch, all scenes render, photo override, flow layout |
| test_validation*.py, test_pipeline.py, test_database*.py, test_eda.py, test_data_processor.py, test_analytics.py, test_regressions.py, test_gui_smoke.py | 123 | original ETL + EDA + GUI baseline (all still passing) |

## Additional checks performed
* Pyflakes over `src/` and `main_task/`: no undefined names or broken imports.
* The real entry point `main_task/gui_main.py` starts and exits cleanly (offscreen).
* `run_pipeline.py --inspect` on the migrated database: schema 4, integrity ok, 230 flights, 0 duplicates, 0 FK violations.
* Extra overflow scan of every page at 380, 640 and 900 px (0 pixels of sideways scroll).
* Screenshots of 10 screens (desktop) and 4 screens each at tablet and phone width were reviewed by eye
  (`docs/screenshots/`).
* Report: rendered PDF checked page by page for the changed pages; deck rendered and checked slide by slide.
* The project database was verified unchanged by the screenshot script and by the test-suite.

## Not verified (be aware)
* **Live APIs.** No FlightAPI or AviationStack call could be made from the sandbox (no keys, no network). FlightAPI parsing is
  verified against a payload shaped like its documentation; the first real search may reveal field differences.
  `main_task/check_apis.py` fails here only because of the missing network.
* **Real devices.** "Tablet" and "phone" mean window widths of the desktop application; it was not run on a physical
  tablet or phone, nor on Windows or macOS (fonts, DPI scaling and animation smoothness may differ).
* **Animation smoothness** was checked by running timers and rendering frames, not by watching a screen.
* **Docker** files were edited but not built (no Docker daemon).
* **Word pagination.** The report's table of contents is static (as in the original); its page numbers were computed from the
  LibreOffice rendering and can differ by a page in Word.

## v2.1.1 performance verification
* Profiled every menu before and after (`docs/PERFORMANCE.md`): revisits of the four unguarded pages went from 150-300 ms to 9-21 ms;
  idle CPU with animation from 26-55 % to 15-22 % of a core; `MainWindow()` from ~560 ms to ~180 ms.
* Airline table output verified identical to the previous implementation (shipped data + random frames).
* Concurrent first-run load of the airport reference from 6 threads: no errors, 9,051 rows.
* **Not verified:** the AviationStack key you supplied could not be tested against the live service (no network access in the
  build environment). All timing numbers are from a headless Linux run, not your machine.
