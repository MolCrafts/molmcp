"""Snapshot cache eviction tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

from molmcp.discovery import DiscoveryConfig, DiscoveryEngine


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _snapshot_dirs(cache_dir: Path) -> list[Path]:
    root = cache_dir / "snapshots"
    return [d for d in root.iterdir() if d.is_dir()] if root.is_dir() else []


def test_evicts_beyond_max_snapshots_per_spec(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "m.py", "x = 0\n")
    config = DiscoveryConfig(
        cache_dir=tmp_path / "cache", max_snapshots_per_spec=2
    )
    engine = DiscoveryEngine(config)

    for i in range(4):
        (repo / "m.py").write_text(f"x = {i}\n", encoding="utf-8")
        engine.refresh(str(repo))

    assert len(_snapshot_dirs(config.cache_dir)) == 2


def test_evict_keeps_newest_snapshot(tmp_path):
    repo = tmp_path / "repo"
    config = DiscoveryConfig(
        cache_dir=tmp_path / "cache", max_snapshots_per_spec=1
    )
    engine = DiscoveryEngine(config)

    _write(repo / "m.py", "x = 1\n")
    first = engine.refresh(str(repo))
    (repo / "m.py").write_text("x = 2\n", encoding="utf-8")
    second = engine.refresh(str(repo))

    assert engine.cache.snapshot_dir(second.snapshot.snapshot_id).exists()
    assert not engine.cache.snapshot_dir(first.snapshot.snapshot_id).exists()


def test_age_based_eviction(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "m.py", "x = 1\n")
    config = DiscoveryConfig(cache_dir=tmp_path / "cache", max_cache_age_days=30)
    engine = DiscoveryEngine(config)

    snapshot_id = engine.index(str(repo)).snapshot.snapshot_id

    manifest_path = engine.cache.manifest_path(snapshot_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["indexed_at"] = time.time() - 40 * 86400
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    summary = engine.cache.evict()
    assert snapshot_id in summary["removed"]
    assert not engine.cache.snapshot_dir(snapshot_id).exists()


def test_evict_is_noop_within_limits(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "m.py", "x = 1\n")
    engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))
    engine.index(str(repo))

    summary = engine.cache.evict()
    assert summary["removed_count"] == 0
