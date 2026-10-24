"""Tiny thread-safe TTL cache used to avoid repeating identical API calls and database reads."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Hashable, Optional, Tuple

_MISSING = object()


class TTLCache:
    """Key -> (value, expiry). Safe to use from the GUI thread and worker threads."""

    def __init__(self, default_ttl: float = 600.0, max_items: int = 256) -> None:
        self._ttl, self._max = default_ttl, max_items
        self._data: Dict[Hashable, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return default
            if item[0] < time.monotonic():
                self._data.pop(key, None)
                return default
            return item[1]

    def has(self, key: Hashable) -> bool:
        return self.get(key, _MISSING) is not _MISSING

    def set(self, key: Hashable, value: Any, ttl: Optional[float] = None) -> None:
        with self._lock:
            if len(self._data) >= self._max:
                now = time.monotonic()
                for k in [k for k, (exp, _v) in self._data.items() if exp < now]:
                    self._data.pop(k, None)
                if len(self._data) >= self._max:               # still full: drop the oldest entry
                    self._data.pop(next(iter(self._data)), None)
            self._data[key] = (time.monotonic() + (self._ttl if ttl is None else ttl), value)

    def get_or_set(self, key: Hashable, factory: Callable[[], Any], ttl: Optional[float] = None) -> Any:
        value = self.get(key, _MISSING)
        if value is _MISSING:
            value = factory()
            self.set(key, value, ttl)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
