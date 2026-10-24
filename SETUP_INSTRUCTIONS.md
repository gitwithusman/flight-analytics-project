# SkyLens v2.1 - setup instructions

Requirements: Python 3.10 or newer (tested with 3.12). A display is needed for the desktop GUI; everything else, including
the test-suite, also runs headless.

## 1. Install
```bash
cd SkyLens_v2
python -m venv .venv                      # optional but recommended
.venv\Scripts\activate                    # Windows      (macOS / Linux: source .venv/bin/activate)
pip install -r requirements.txt           # includes PySide6; the first install downloads ~150 MB
```

## 2. Keys
The AviationStack key is already built in: it is in the `.env` file at the project root (git-ignored). Nothing has to be
entered in the app. Do not share or commit that file. To change the key later, edit `AVIATIONSTACK_API_KEY=` in `.env`.
(If `.env` is missing, copy `.env.example` to `.env` and add the key.)
* `AVIATIONSTACK_API_KEY` - live flights / live status (built in). Stored data (230 flights) also works without it.
* `FLIGHTAPI_API_KEY` - needed only for real Flight Search results. Without it Flight Search returns clearly labelled SAMPLE flights.
* Weather needs no key. Never commit `.env`.

## 3. Run
```bash
python main_task/gui_main.py              # desktop application
python main_task/main.py                  # terminal menu
python main_task/run_pipeline.py --inspect    # database integrity overview
```
Existing databases are migrated to schema v4 automatically on first start (see `CHANGES.md`). **Back up your own
`database/flight_airport.db` first** if it contains data you cannot recreate: the removal of the fare tables cannot be undone.

## 4. Try the interface
* Resize the window: below 1020 px the sidebar becomes icons, below 700 px a menu button (top left) opens it as a drawer.
* Settings -> Appearance -> **Reduce animations** switches the moving scenery off.
* Optional photographs: put `noon.jpg`, `dawn.jpg`, `dusk.jpg`, `night.jpg`, `storm.jpg` or `day.jpg` into `assets/backgrounds/`.
* Regenerate the screenshots: `python main_task/make_screenshots.py` (headless, uses a temporary copy of the database).

## 5. Tests
```bash
python -m pytest tests -q                 # 276 tests, ~95 s, no network or key needed
```
On a machine without a display: `set QT_QPA_PLATFORM=offscreen` (Windows) / `export QT_QPA_PLATFORM=offscreen` (Linux / macOS).

## 6. If something does not work
| Symptom | Fix |
|---|---|
| `No module named PySide6` | `pip install -r requirements.txt` |
| Fonts look plain | The theme prefers Inter / Segoe UI Variable; install Inter for the intended look, otherwise a system font is used |
| Animation is slow on an old machine | Settings -> Reduce animations |
| Flight Search shows SAMPLE DATA | no `FLIGHTAPI_API_KEY` is set (intended); add it in Settings |
| `main_task/check_apis.py` fails | it makes real network calls; check your connection and keys |
