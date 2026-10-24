"""Validation stress test: deliberately corrupt COPIES of real archived records.

Shows, on a throw-away database, that every Pydantic rule fires and is reported
with a field-level reason. Nothing here touches the project database.
This is a test harness - the corrupted records are synthetic and clearly
labelled as such in the output.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import api_client, config, database, pipeline  # noqa: E402
from src.models import validate_batch  # noqa: E402

CASES = [
    ("unknown flight_status", lambda r: r.update(flight_status="exploded")),
    ("flight_date not ISO", lambda r: r.update(flight_date="09/10/2026")),
    ("negative departure delay", lambda r: r["departure"].update(delay=-15)),
    ("implausible delay (> 48 h)", lambda r: r["departure"].update(delay=99999)),
    ("airport IATA wrong length", lambda r: r["departure"].update(iata="ABCDE")),
    ("airline IATA wrong length", lambda r: r["airline"].update(iata="XYZ9")),
    ("timestamp not ISO-8601", lambda r: r["departure"].update(scheduled="yesterday")),
    ("live latitude out of range", lambda r: r.update(live={"latitude": 123.0})),
    ("no flight identifier", lambda r: r.update(flight={"number": None, "iata": None, "icao": None})),
    ("no airport codes", lambda r: (r["departure"].update(iata=None), r["arrival"].update(iata=None))),
    ("arrival before departure", lambda r: r["arrival"].update(
        scheduled="2000-01-01T00:00:00+00:00")),
]


def main() -> int:
    files = sorted(config.DATA_RAW_DIR.glob("*.json"))
    if not files:
        print("No archived raw responses in data/raw/ - nothing to corrupt.")
        return 1
    base = api_client.load_raw_payload(files[0])["data"]
    healthy = [r for r in base if validate_batch([r]).accepted_count == 1][: len(CASES) + 5]
    corrupted = []
    for i, (label, mutate) in enumerate(CASES):
        rec = copy.deepcopy(healthy[i])
        mutate(rec)
        rec["_case"] = label
        corrupted.append(rec)
    batch = healthy[len(CASES):] + corrupted           # 5 good + 11 corrupted
    report = validate_batch(batch)

    print("VALIDATION STRESS TEST (synthetic corruption of real records)")
    print(f"  records submitted : {report.total}")
    print(f"  accepted          : {report.accepted_count}")
    print(f"  rejected          : {report.rejected_count}\n")
    rows = []
    for rec in report.rejected:
        case = batch[rec.index].get("_case")
        reasons = "; ".join(f"{e['field']}: {e['message']}" for e in rec.errors)
        print(f"  [{case}]\n      -> {reasons}")
        rows.append({"injected_defect": case, "rejected_fields": [e["field"] for e in rec.errors],
                     "reason": reasons})
    detected = {r["injected_defect"] for r in rows}
    missed = [c for c, _ in CASES if c not in detected]
    print(f"\n  defects detected: {len(detected)} of {len(CASES)}; missed: {missed or 'none'}")

    with tempfile.TemporaryDirectory() as tmp:           # run through the real pipeline too
        payload = Path(tmp) / "stress.json"
        payload.write_text(json.dumps({"data": batch}), encoding="utf-8")
        db = Path(tmp) / "stress.db"
        run = pipeline.run_pipeline(raw_file=payload, db_path=db, save_artifacts=False)
        audit = database.fetch_rejected(db_path=db)
        print(f"\n  pipeline: stored {run.inserted} rows, audit table holds {len(audit)} rejections")
    out = config.REPORTS_DIR / "validation_stress_test.json"
    out.write_text(json.dumps({
        "note": "synthetic corruption of copies of real archived records; test only",
        "submitted": report.total, "accepted": report.accepted_count,
        "rejected": report.rejected_count, "defects_detected": len(detected),
        "defects_injected": len(CASES), "cases": rows}, indent=2), encoding="utf-8")
    print(f"  written -> {out}")
    return 0 if not missed else 1


if __name__ == "__main__":
    raise SystemExit(main())
