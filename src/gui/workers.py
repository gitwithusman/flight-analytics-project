"""Background execution helpers.

Long-running work (HTTP requests, database reads, chart-independent data
preparation) runs on Qt's thread pool. Results are delivered through a
signal owned by a main-thread QObject, so every callback runs on the GUI
thread - widgets are never touched from a worker thread.
"""

from __future__ import annotations

import itertools
import traceback
from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

try:  # shiboken6 ships with PySide6
    from shiboken6 import isValid as _is_valid
except Exception:  # pragma: no cover - defensive
    def _is_valid(_obj) -> bool:
        return True

from src.utils import get_logger

logger = get_logger()


class _Job(QRunnable):
    def __init__(self, runner: "TaskRunner", task_id: int, fn, args, kwargs):
        super().__init__()
        self._runner, self._id = runner, task_id
        self._fn, self._args, self._kwargs = fn, args, kwargs

    def run(self) -> None:  # executes on a pool thread
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:
            logger.warning("Background task failed: %s\n%s", exc,
                           traceback.format_exc())
            self._runner._failed.emit(self._id, str(exc) or exc.__class__.__name__)
        else:
            self._runner._finished.emit(self._id, result)


class TaskRunner(QObject):
    """Run callables off the GUI thread and call back on the GUI thread."""

    _finished = Signal(int, object)
    _failed = Signal(int, str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)
        self._ids = itertools.count(1)
        self._callbacks: Dict[int, Tuple[Optional[Callable], Optional[Callable],
                                         Optional[QObject]]] = {}
        # Bound methods of a main-thread QObject => queued delivery.
        self._finished.connect(self._on_finished)
        self._failed.connect(self._on_failed)

    def submit(self, fn: Callable, on_done: Optional[Callable] = None,
               on_error: Optional[Callable] = None,
               owner: Optional[QObject] = None, **kwargs) -> int:
        """Queue ``fn(**kwargs)``.

        ``owner``: if that widget has been destroyed by the time the task
        finishes (e.g. the page rebuilt its rows), the callback is skipped
        instead of raising "Internal C++ object already deleted".
        """
        task_id = next(self._ids)
        self._callbacks[task_id] = (on_done, on_error, owner)
        self._pool.start(_Job(self, task_id, fn, (), kwargs))
        return task_id

    def busy(self) -> bool:
        return bool(self._callbacks)

    def wait(self, timeout_ms: int = 3000) -> bool:
        """Block until running tasks finish (used while closing the app)."""
        return self._pool.waitForDone(timeout_ms)

    def _take(self, task_id: int):
        on_done, on_error, owner = self._callbacks.pop(task_id, (None, None, None))
        alive = owner is None or _is_valid(owner)
        return on_done, on_error, alive

    @Slot(int, object)
    def _on_finished(self, task_id: int, result) -> None:
        on_done, _err, alive = self._take(task_id)
        if on_done and alive:
            on_done(result)

    @Slot(int, str)
    def _on_failed(self, task_id: int, message: str) -> None:
        _done, on_error, alive = self._take(task_id)
        if on_error and alive:
            on_error(message)
