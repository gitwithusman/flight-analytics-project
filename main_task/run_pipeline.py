"""Command-line runner for the ETL pipeline (and database inspection).

Run from the project root:

    python main_task/run_pipeline.py                  # live API -> validate -> transform -> SQLite
    python main_task/run_pipeline.py --limit 50 --status active
    python main_task/run_pipeline.py --pages 3        # up to 3 API requests (offset pagination)
    python main_task/run_pipeline.py --replay-raw     # re-run T+L on archived real responses
    python main_task/run_pipeline.py --replay-raw --rebuild   # rebuild DB purely from the archive
    python main_task/run_pipeline.py --init-db        # create / migrate the database only
    python main_task/run_pipeline.py --inspect        # schema, row counts, run history, checks
    python main_task/run_pipeline.py --rebuild-derived   # recompute airports/airlines/routes from stored flights
    python main_task/run_pipeline.py --eda            # run the EDA on the stored data afterwards
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import config, database, pipeline  # noqa: E402
from src.utils import AppError  # noqa: E402


def _print_report(report: pipeline.PipelineReport) -> None:
    print("\n" + "=" * 64)
    print(f"PIPELINE RUN {report.run_id}  -  {report.status.upper()}  ({report.duration_s}s)")
    print("=" * 64)
    for line in report.summary_lines():
        print("  " + line)
    if report.rejection_breakdown:
        print(f"  Rejection reasons      : {report.rejection_breakdown}")
    for msg in report.rejected_messages[:5]:
        print("    - " + msg)
    if len(report.rejected_messages) > 5:
        print(f"    ... and {len(report.rejected_messages) - 5} more")
    for label, value in (("Run report", report.report_file),
                         ("Rejected CSV", report.rejected_file),
                         ("Processed CSV", report.processed_file)):
        if value:
            print(f"  {label:<22}: {value}")


def _inspect() -> None:
    info = database.database_info()
    print(f"\nDatabase: {info['path']}  ({info['size_kb']} KB)")
    print(f"  flights={info['flights']}  airports={info['airports']}  "
          f"runs={info['refreshes']}  rejected_records={info['rejected']}")
    print("\nSchema")
    for table, cols in database.schema_description().items():
        print(f"  {table}: " + ", ".join(
            f"{c['name']}{'*' if c['primary_key'] else ''}" for c in cols[:12])
            + (" ..." if len(cols) > 12 else ""))
    print("  (* = primary key)")
    history = database.fetch_run_history()
    if not history.empty:
        print("\nRun history (refresh_log)")
        print(history[["id", "refreshed_at", "source", "records_fetched",
                       "records_valid", "records_rejected", "records_inserted",
                       "records_updated", "status"]].to_string(index=False))
    print("\nIntegrity checks")
    for key, value in database.verify_database().items():
        print(f"  {key:<28}: {value}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=config.DEFAULT_RECORD_LIMIT,
                        help="records to request (default from .env)")
    parser.add_argument("--pages", type=int, default=1,
                        help="max API requests when limit > 100 (uses quota!)")
    parser.add_argument("--status", help="flight_status filter")
    parser.add_argument("--dep", help="departure IATA filter")
    parser.add_argument("--arr", help="arrival IATA filter")
    parser.add_argument("--airline", help="airline name filter")
    parser.add_argument("--flight", help="flight number filter")
    parser.add_argument("--replay-raw", nargs="*", metavar="FILE",
                        help="replay archived raw JSON (default: all of data/raw/)")
    parser.add_argument("--rebuild", action="store_true",
                        help="with --replay-raw: empty flights/airports first")
    parser.add_argument("--init-db", action="store_true", help="create/migrate DB and exit")
    parser.add_argument("--rebuild-derived", action="store_true",
                        help="recompute airports / airlines / routes from stored flights and exit")
    parser.add_argument("--inspect", action="store_true", help="show DB schema/history/checks")
    parser.add_argument("--eda", action="store_true", help="run the EDA after loading")
    args = parser.parse_args(argv)

    try:
        if args.init_db:
            print(database.initialise_database())
            return 0
        if args.rebuild_derived:
            print(database.rebuild_derived_tables())
            return 0
        if args.inspect and args.replay_raw is None and not args.eda:
            _inspect()
            return 0
        if args.replay_raw is not None:
            files = [Path(f) for f in args.replay_raw] or sorted(config.DATA_RAW_DIR.glob("*.json"))
            if not files:
                print("No raw files found in data/raw/.")
                return 1
            for report in pipeline.replay_raw_files(files, rebuild=args.rebuild):
                _print_report(report)
        else:
            _print_report(pipeline.run_pipeline(
                limit=args.limit, pages=args.pages, flight_status=args.status,
                dep_iata=args.dep, arr_iata=args.arr, airline_name=args.airline,
                flight_number=args.flight))
        if args.inspect:
            _inspect()
        if args.eda:
            from src import eda
            summary = eda.run_eda()
            print(f"\nEDA complete: {len(summary['figures'])} figures in {config.EDA_FIGURES_DIR}")
            print(f"Findings written to {config.EDA_DIR / 'EDA_Findings.md'}")
        return 0
    except AppError as exc:
        print(f"\nPipeline failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
