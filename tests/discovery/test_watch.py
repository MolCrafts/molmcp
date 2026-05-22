"""LocalWatcher tests."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from molmcp.discovery import DiscoveryConfig, DiscoveryEngine
from molmcp.discovery.cache import LocalWatcher


def _engine(tmp_path: Path) -> DiscoveryEngine:
    return DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def m():\n    pass\n", encoding="utf-8")
    return repo


def test_poll_once_reports_no_change(tmp_path):
    watcher = LocalWatcher(_engine(tmp_path), str(_repo(tmp_path)))
    assert watcher.poll_once() is False  # initial resolve
    assert watcher.poll_once() is False  # still unchanged


def test_poll_once_detects_and_refreshes_change(tmp_path):
    repo = _repo(tmp_path)
    changes: list = []
    watcher = LocalWatcher(
        _engine(tmp_path), str(repo), on_change=changes.append
    )
    watcher.poll_once()

    (repo / "m.py").write_text("def m():\n    return 1\n", encoding="utf-8")
    assert watcher.poll_once() is True
    assert len(changes) == 1
    assert changes[0].snapshot is not None


def test_watch_thread_triggers_refresh(tmp_path):
    repo = _repo(tmp_path)
    fired = threading.Event()
    watcher = LocalWatcher(
        _engine(tmp_path),
        str(repo),
        interval=0.05,
        debounce=0.05,
        on_change=lambda result: fired.set(),
    )
    watcher.start()
    try:
        time.sleep(0.15)
        (repo / "m.py").write_text(
            "def m():\n    return 2\n", encoding="utf-8"
        )
        assert fired.wait(timeout=3.0)
    finally:
        watcher.stop()
