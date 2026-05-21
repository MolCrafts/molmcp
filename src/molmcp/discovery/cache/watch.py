"""LocalWatcher — a polling watcher for local discovery sources.

A stdlib-only watcher: a daemon thread re-checks a source's known files
on an interval (stat-based, cheap) and, after a debounce, triggers an
incremental ``refresh``. Off by default — opt in via ``DiscoveryConfig``.
``poll_once`` exposes the same logic synchronously for tests.
"""

from __future__ import annotations

import threading
from typing import Callable

from .freshness import FreshnessTracker


class LocalWatcher:
    """Polls one local source and refreshes it when it changes."""

    def __init__(
        self,
        engine,
        spec: str,
        *,
        interval: float = 5.0,
        debounce: float = 2.0,
        on_change: Callable | None = None,
    ) -> None:
        self.engine = engine
        self.spec = spec
        self.interval = interval
        self.debounce = debounce
        self.on_change = on_change
        self._snapshot = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> "LocalWatcher":
        self._snapshot = self.engine.resolve(self.spec)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + self.debounce + 1.0)

    def poll_once(self) -> bool:
        """Check once; refresh if the source changed. Returns True if so."""
        if self._snapshot is None:
            self._snapshot = self.engine.resolve(self.spec)
            return False
        if not FreshnessTracker.is_stale(self._snapshot):
            return False
        result = self.engine.refresh(self.spec)
        self._snapshot = result.snapshot
        if self.on_change is not None:
            self.on_change(result)
        return True

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            if self._snapshot is None or not FreshnessTracker.is_stale(
                self._snapshot
            ):
                continue
            if self._stop.wait(self.debounce):
                break
            try:
                result = self.engine.refresh(self.spec)
                self._snapshot = result.snapshot
                if self.on_change is not None:
                    self.on_change(result)
            except Exception:  # noqa: BLE001 - a watch loop must not die
                continue
