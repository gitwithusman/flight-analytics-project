"""Desktop GUI entry point - Flight and Airport Analytics (PySide6).

Run from the project root::

    python main_task/gui_main.py

The interface lives in the ``src.gui`` package (theme, widgets, pages and
main window). All business logic is shared with the terminal application.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make ``src`` importable when launched from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.gui.main_window import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
