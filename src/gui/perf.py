"""GUI performance helpers.

``RenderQueue`` runs expensive drawing jobs (Matplotlib figures, the route map) one at a time from the event loop
instead of inside the click handler, so the window keeps painting and answering input while a page fills in.
Jobs are keyed: submitting the same key again replaces the pending job, so quick filter changes draw only the last state.
"""

from __future__ import annotations

from typing import Callable, Dict, Hashable

from PySide6.QtCore import QObject, QTimer

from src.utils import get_logger

logger = get_logger()


class RenderQueue(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._jobs: Dict[Hashable, Callable[[], None]] = {}
        self._scheduled = False

    @property
    def busy(self) -> bool:
        return bool(self._jobs)

    def submit(self, key: Hashable, job: Callable[[], None]) -> None:
        self._jobs.pop(key, None)            # re-queue at the end: the latest request wins
        self._jobs[key] = job
        if not self._scheduled:
            self._scheduled = True
            QTimer.singleShot(0, self._run_next)

    def cancel(self, key: Hashable) -> None:
        self._jobs.pop(key, None)

    def _run_next(self) -> None:
        self._scheduled = False
        if not self._jobs:
            return
        key = next(iter(self._jobs))
        job = self._jobs.pop(key)
        try:
            job()
        except RuntimeError:
            pass                              # the widget was deleted while the job waited
        except Exception:                     # a drawing bug must never stop the queue
            logger.exception("Render job failed")
        if self._jobs and not self._scheduled:
            self._scheduled = True
            QTimer.singleShot(1, self._run_next)   # yield to the event loop between jobs

    def clear(self) -> None:
        """Drop every pending job (e.g. when windows are torn down)."""
        self._jobs.clear()

    def flush(self) -> None:
        """Run every pending job now (used by tests and before exporting)."""
        while self._jobs:
            key = next(iter(self._jobs))
            job = self._jobs.pop(key)
            try:
                job()
            except RuntimeError:
                pass


render_queue = RenderQueue()
