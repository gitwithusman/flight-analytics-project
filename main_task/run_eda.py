"""Run the structured EDA on the data stored in SQLite.

    python main_task/run_eda.py

Writes figures to visualizations/eda/ and the summary to outputs/eda/.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import config, eda  # noqa: E402


def main() -> int:
    try:
        summary = eda.run_eda()
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print("\nKEY FINDINGS")
    for i, text in enumerate(summary["findings"], 1):
        print(f" {i}. {text}")
    print(f"\n{len(summary['figures'])} figures -> {config.EDA_FIGURES_DIR}")
    print(f"Summary  -> {config.EDA_DIR / 'eda_summary.json'}")
    print(f"Markdown -> {config.EDA_DIR / 'EDA_Findings.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
