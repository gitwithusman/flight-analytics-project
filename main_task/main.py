"""Flight and Airport Analytics - terminal application.

Run from the project root:

    python main_task/main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make ``src`` importable when launched from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src import __version__, analytics, api_client, config, database
from src import service, utils, visualizations

APP_TITLE = f"Flight and Airport Analytics v{__version__}"
LINE = "-" * 74


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------


def banner() -> None:
    print("\n" + "=" * 74)
    print(APP_TITLE.center(74))
    print("=" * 74)
    print(
        "Explore real flight and airport data retrieved from the AviationStack\n"
        "API, stored locally in SQLite, and analysed with pandas."
    )


def menu() -> None:
    print("\n" + LINE)
    print("MAIN MENU")
    print(LINE)
    options = [
        ("1", "Application overview"),
        ("2", "Retrieve / refresh aviation data"),
        ("3", "View flight records"),
        ("4", "View airport records"),
        ("5", "Search and filter records"),
        ("6", "Flight and airport statistics"),
        ("7", "Exploratory data analysis"),
        ("8", "Generate visualizations"),
        ("9", "Database information"),
        ("10", "Export records or analysis"),
        ("11", "Configuration / data-source status"),
        ("12", "ETL run history, integrity checks and structured EDA"),
        ("0", "Exit"),
    ]
    for key, label in options:
        print(f"  {key:>2}. {label}")


def _readline(text: str = "") -> str:
    """input() that treats EOF (piped input ending) as an exit request."""
    try:
        return input(text)
    except EOFError:
        raise _QuitRequested()


class _QuitRequested(Exception):
    """Internal signal used to leave the menu loop on EOF."""


def pause() -> None:
    _readline("\nPress Enter to return to the main menu...")


def prompt(text: str, default: str = "") -> str:
    value = _readline(
        f"{text}" + (f" [{default}]" if default else "") + ": ").strip()
    return value or default


def prompt_int(text: str, default: int, low: int, high: int) -> int:
    while True:
        raw = prompt(text, str(default))
        try:
            value = int(raw)
        except ValueError:
            print("  ! Please enter a whole number.")
            continue
        if not low <= value <= high:
            print(f"  ! Value must be between {low} and {high}.")
            continue
        return value


def show_error(exc: Exception) -> None:
    print(f"\n  ! {exc}")


def print_table(df: pd.DataFrame, columns=None, max_rows: int = 20) -> None:
    """Print a readable slice of a DataFrame."""
    if df is None or df.empty:
        print("  (no records)")
        return
    view = df.copy()
    if columns:
        view = view[[c for c in columns if c in view.columns]]
    if len(view) > max_rows:
        print(view.head(max_rows).to_string(index=False))
        print(f"  ... showing {max_rows} of {len(view)} rows")
    else:
        print(view.to_string(index=False))


def stored_flights(**filters) -> pd.DataFrame:
    return database.fetch_flights(**filters)


FLIGHT_VIEW_COLS = [
    "flight_date", "flight_iata", "airline_name", "flight_status",
    "dep_iata", "dep_airport", "arr_iata", "arr_airport",
    "dep_delay_min", "route",
]


# ---------------------------------------------------------------------------
# Menu actions
# ---------------------------------------------------------------------------


def action_overview() -> None:
    info = database.database_info()
    last = database.last_refresh()
    print("\nABOUT THIS APPLICATION")
    print(LINE)
    print(
        "Flight and Airport Analytics retrieves live flight information from\n"
        "the AviationStack REST API, validates it with Pydantic, cleans it\n"
        "with pandas, stores it in a local SQLite database, and produces\n"
        "statistics and charts you can explore here or in the desktop app.\n"
    )
    print(f"  Data source        : AviationStack ({config.AVIATIONSTACK_BASE_URL})")
    key_state = "yes" if config.api_key_configured() else "no  (see option 11)"
    print(f"  API key configured : {key_state}")
    print(f"  Database           : {info['path']}")
    print(f"  Stored flights     : {utils.format_number(info['flights'])}")
    print(f"  Stored airports    : {utils.format_number(info['airports'])}")
    print(f"  Last refresh       : {utils.safe_str(info['last_refresh'])}")
    if last and last.get("status") != "success":
        print(f"  Last refresh status: {last['status']} - {last.get('message', '')}")
    pause()


def action_refresh() -> None:
    print("\nRETRIEVE / REFRESH AVIATION DATA")
    print(LINE)
    if not config.api_key_configured():
        print(
            "  No API key is configured yet.\n"
            "  1. Create a free account at https://aviationstack.com\n"
            "  2. Copy .env.example to .env\n"
            "  3. Put your key in AVIATIONSTACK_API_KEY and restart.\n"
            "\n"
            "  Existing database records remain available in the meantime."
        )
        pause()
        return

    print("Optional filters - press Enter to skip:")
    status = prompt("  Flight status (scheduled/active/landed/cancelled/incident/diverted)")
    if status and status.lower() not in api_client.FILTERABLE_STATUSES:
        print("  ! Unknown status - the filter will be ignored.")
        status = ""
    dep = prompt("  Departure airport IATA (e.g. JFK)").upper()
    arr = prompt("  Arrival airport IATA (e.g. LHR)").upper()
    airline = prompt("  Airline name (e.g. 'American Airlines')")
    number = prompt("  Flight number (e.g. 100)")
    limit = prompt_int("  Records to fetch (1-1000)", config.DEFAULT_RECORD_LIMIT,
                       1, config.MAX_RECORD_LIMIT)

    print("\n  Contacting AviationStack...")
    try:
        result = service.refresh_data(
            limit=limit,
            flight_status=status or None,
            dep_iata=dep or None,
            arr_iata=arr or None,
            airline_name=airline or None,
            flight_number=number or None,
        )
    except utils.AppError as exc:  # the pipeline already logged the failed run
        show_error(exc)
        pause()
        return

    print(f"\n  {result.message}")
    print(f"    fetched from API   : {result.fetched}")
    print(f"    passed validation  : {result.valid}")
    print(f"    rejected           : {result.invalid}")
    print(f"    new rows inserted  : {result.inserted}")
    print(f"    existing refreshed : {result.updated}")
    print(f"    airport records    : {result.airports_stored}")
    if result.processed_file:
        print(f"    processed file     : {result.processed_file}")
    if result.validation_errors:
        print("\n  First validation errors:")
        for err in result.validation_errors[:5]:
            print(f"    - {err}")
    pause()


def action_flights() -> None:
    df = stored_flights()
    print("\nFLIGHT RECORDS")
    print(LINE)
    if df.empty:
        print("  No flights stored yet. Use menu option 2 to retrieve data.")
    else:
        print(f"  {len(df)} stored records (latest first)\n")
        print_table(df, FLIGHT_VIEW_COLS, max_rows=25)
    pause()


def action_airports() -> None:
    df = database.fetch_airports()
    print("\nAIRPORT RECORDS")
    print(LINE)
    if df.empty:
        print("  No airports stored yet. Retrieve flight data first - airport\n"
              "  records are derived from the departure/arrival information\n"
              "  supplied by the API for each flight.")
    else:
        print(f"  {len(df)} airports observed in stored flights\n")
        print_table(df, max_rows=30)
    pause()


def action_search() -> None:
    print("\nSEARCH AND FILTER RECORDS")
    print(LINE)
    term = prompt("Search text (flight no, airline, airport, route)")
    status = prompt("Filter by status (Enter to skip)")
    if status and status.lower() not in api_client.FILTERABLE_STATUSES:
        print("  ! Unknown status - ignored.")
        status = ""
    dep = prompt("Filter by departure IATA (Enter to skip)").upper()
    arr = prompt("Filter by arrival IATA (Enter to skip)").upper()
    delayed = prompt("Delayed flights only? (y/n)", "n").lower() == "y"

    if not any([term, status, dep, arr, delayed]):
        print("  No criteria supplied - showing nothing.")
        pause()
        return

    df = stored_flights(
        search=term or None,
        status=status or None,
        dep_iata=dep or None,
        arr_iata=arr or None,
        delayed_only=delayed,
    )
    print(f"\n  {len(df)} matching record(s)\n")
    print_table(df, FLIGHT_VIEW_COLS, max_rows=30)
    pause()


def action_statistics() -> None:
    df = stored_flights()
    print("\nFLIGHT AND AIRPORT STATISTICS")
    print(LINE)
    if df.empty:
        print("  No data yet - retrieve records first (menu option 2).")
        pause()
        return

    print(f"  Total stored flights : {len(df)}")
    counts = analytics.unique_value_counts(df)
    for label, value in counts.items():
        print(f"  Unique {label.replace('_', ' '):<18}: {value}")

    print("\n  Flight status:")
    print_table(analytics.status_distribution(df), max_rows=10)

    delays = analytics.delay_statistics(df)
    print("\n  Delays:")
    if delays["available"]:
        print(f"    flights with delay data : {delays['flights_with_delay_data']}")
        print(f"    delayed flights         : {delays['delayed_flights']} "
              f"({delays['delayed_share_pct']}%)")
        print(f"    average delay           : {delays['avg_delay_min']} min")
        print(f"    median delay            : {delays['median_delay_min']} min")
        print(f"    worst delay             : {delays['max_delay_min']} min")
    else:
        print(f"    {delays['reason']}")

    cs = analytics.codeshare_share(df)
    print(f"\n  Codeshared flights: {cs['codeshared']} ({cs['share_pct']}%)")
    pause()


def action_eda() -> None:
    df = stored_flights()
    print("\nEXPLORATORY DATA ANALYSIS")
    print(LINE)
    if df.empty:
        print("  No data yet - retrieve records first (menu option 2).")
        pause()
        return

    overview = analytics.dataset_overview(df)
    print(f"  Shape          : {overview['rows']} rows x {overview['columns']} cols")
    print(f"  Missing cells  : {overview['missing_total']}")
    print(f"  Duplicate rows : {overview['duplicate_rows']}")
    if overview["date_range"]:
        print(f"  Flight dates   : {overview['date_range'][0]} to "
              f"{overview['date_range'][1]}")

    print("\n  Columns with missing values:")
    missing = overview["missing_by_column"]
    if missing:
        for col, count in list(missing.items())[:15]:
            print(f"    {col:<24} {count}")
    else:
        print("    none")

    print("\n  Top airlines:")
    print_table(analytics.top_airlines(df), max_rows=10)
    print("\n  Top departure airports:")
    print_table(analytics.top_airports(df, "dep"), max_rows=10)
    print("\n  Top arrival airports:")
    print_table(analytics.top_airports(df, "arr"), max_rows=10)
    print("\n  Most frequent routes:")
    print_table(analytics.top_routes(df), max_rows=10)
    print("\n  Flights by scheduled departure hour (airport local time):")
    print_table(analytics.departure_hour_distribution(df), max_rows=24)
    print("\n  Numeric summary:")
    print_table(analytics.numeric_summary(df), max_rows=10)
    pause()


def action_visualizations() -> None:
    df = stored_flights()
    print("\nGENERATE VISUALIZATIONS")
    print(LINE)
    if df.empty:
        print("  No data yet - retrieve records first (menu option 2).")
        pause()
        return

    keys = list(visualizations.CHART_TYPES)
    for i, key in enumerate(keys, 1):
        print(f"  {i}. {visualizations.CHART_TYPES[key]['title']}")
    print("  a. Generate all charts")
    choice = prompt("Choose a chart number, or 'a' for all").lower()

    try:
        if choice == "a":
            paths = visualizations.save_all_charts(df)
            for key, path in paths.items():
                print(f"  saved {key:<12} -> {path}")
        elif choice.isdigit() and 1 <= int(choice) <= len(keys):
            path = visualizations.save_chart(keys[int(choice) - 1], df)
            print(f"  saved -> {path}")
        else:
            print("  ! Invalid chart selection.")
    except utils.AppError as exc:
        show_error(exc)
    pause()


def action_db_info() -> None:
    info = database.database_info()
    print("\nDATABASE INFORMATION")
    print(LINE)
    print(f"  Path              : {info['path']}")
    print(f"  Exists            : {info['exists']}")
    print(f"  Size              : {info['size_kb']} KB")
    print(f"  Flight rows       : {utils.format_number(info['flights'])}")
    print(f"  Airport rows      : {utils.format_number(info['airports'])}")
    print(f"  Refresh log rows  : {utils.format_number(info['refreshes'])}")
    print(f"  Last refresh      : {utils.safe_str(info['last_refresh'])}")
    print(f"  Last success      : {utils.safe_str(info['last_success'])}")

    recent = database.last_refresh()
    if recent:
        print("\n  Most recent refresh:")
        for key in ("source", "records_fetched", "records_valid",
                    "records_stored", "status", "message"):
            print(f"    {key:<16}: {recent.get(key)}")
    pause()


def action_export() -> None:
    print("\nEXPORT RECORDS / ANALYSIS")
    print(LINE)
    print("  1. Flights  -> CSV")
    print("  2. Flights  -> JSON")
    print("  3. Airports -> CSV")
    print("  4. Airports -> JSON")
    print("  5. Analytics summary -> JSON")
    choice = prompt("Choose an export")
    table_fmt = {
        "1": ("flights", "csv"),
        "2": ("flights", "json"),
        "3": ("airports", "csv"),
        "4": ("airports", "json"),
    }
    try:
        if choice in table_fmt:
            table, fmt = table_fmt[choice]
            if database.count_rows(table) == 0:
                print(f"  The '{table}' table is empty - nothing to export.")
            else:
                path = database.export_table(table, fmt)
                print(f"  exported -> {path}")
        elif choice == "5":
            df = stored_flights()
            if df.empty:
                print("  No data yet - retrieve records first.")
            else:
                summary = analytics.full_summary(df, database.fetch_airports())
                path = database.export_summary_json(summary, "analytics_summary")
                print(f"  exported -> {path}")
        else:
            print("  ! Invalid export option.")
    except (utils.AppError, ValueError) as exc:
        show_error(exc)
    pause()


def action_config_status() -> None:
    status = config.data_source_status()
    print("\nCONFIGURATION / DATA-SOURCE STATUS")
    print(LINE)
    print(f"  Provider          : {status['provider']}")
    print(f"  API key           : {status['api_key_display']}")
    print(f"  Base URL          : {status['base_url']}")
    print(f"  Weather provider  : {status['weather_provider']} "
          "(informational only)")
    print(f"  Request timeout   : {status['request_timeout']}s")
    print(f"  Default limit     : {status['default_limit']} records/request")
    print(f"  Database          : {status['database_path']}")
    if not status["api_key_configured"]:
        print("\n  To configure the API key:")
        print("    1. Sign up free at https://aviationstack.com")
        print("    2. Copy .env.example to .env")
        print("    3. Set AVIATIONSTACK_API_KEY=<your key>")
    pause()


def action_etl_eda() -> None:
    """Show the pipeline audit trail, verify the database and run the EDA."""
    from src import eda

    print("\nETL RUN HISTORY (refresh_log)")
    print(LINE)
    history = database.fetch_run_history()
    print_table(history, ["id", "refreshed_at", "source", "records_fetched",
                          "records_valid", "records_rejected", "records_inserted",
                          "records_updated", "status"], max_rows=15)
    print("\nDATABASE INTEGRITY CHECKS")
    print(LINE)
    for key, value in database.verify_database().items():
        print(f"  {key:<28}: {value}")
    rejected = database.fetch_rejected()
    print(f"\nREJECTED RECORDS STORED: {len(rejected)}")
    print_table(rejected, ["run_id", "stage", "identifier", "error_fields",
                          "error_messages"], max_rows=5)
    if not service.dataset_available():
        print("\n  No flights stored yet - retrieve data first (option 2).")
        pause()
        return
    print("\nSTRUCTURED EDA (from the SQLite database)")
    print(LINE)
    summary = eda.run_eda()
    for i, text in enumerate(summary["findings"], 1):
        print(f"  {i}. {text}")
    print(f"\n  {len(summary['figures'])} figures saved to {config.EDA_FIGURES_DIR}")
    print(f"  summary saved to {config.EDA_DIR}")
    pause()


ACTIONS = {
    "1": action_overview,
    "2": action_refresh,
    "3": action_flights,
    "4": action_airports,
    "5": action_search,
    "6": action_statistics,
    "7": action_eda,
    "8": action_visualizations,
    "9": action_db_info,
    "10": action_export,
    "11": action_config_status,
    "12": action_etl_eda,
}


def main() -> None:
    banner()
    try:
        while True:
            menu()
            choice = _readline("\nSelect an option: ").strip()
            if choice == "0":
                break
            action = ACTIONS.get(choice)
            if action is None:
                print("  ! Invalid option - please pick a number from the menu.")
                continue
            try:
                action()
            except utils.AppError as exc:
                show_error(exc)
                pause()
            except KeyboardInterrupt:
                print("\n  (cancelled)")
                pause()
            except Exception as exc:  # last-resort safety net
                utils.get_logger().exception("Unexpected error")
                print(f"\n  ! Unexpected error: {exc}")
                pause()
    except _QuitRequested:
        pass
    print("\nGoodbye - safe travels!\n")


if __name__ == "__main__":
    main()
