"""Incremental refresh and freshness-tracking tests."""

from __future__ import annotations

from pathlib import Path

from molmcp.discovery import DiscoveryConfig, DiscoveryEngine
from molmcp.discovery.cache import FreshnessTracker


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for name in ("a", "b", "c"):
        _write(repo / f"{name}.py", f"def {name}():\n    pass\n")
    return repo


def _engine(tmp_path: Path) -> DiscoveryEngine:
    return DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))


def test_refresh_reindexes_only_changed_files(tmp_path):
    repo = _repo(tmp_path)
    engine = _engine(tmp_path)

    first = engine.refresh(str(repo))
    assert first.extract_stats["analyzed"] == 3
    assert first.extract_stats["reused"] == 0

    (repo / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    second = engine.refresh(str(repo))
    assert second.extract_stats["analyzed"] == 1
    assert second.extract_stats["reused"] == 2


def test_deleted_file_is_purged(tmp_path):
    repo = _repo(tmp_path)
    engine = _engine(tmp_path)
    engine.refresh(str(repo))

    (repo / "c.py").unlink()
    result = engine.refresh(str(repo))

    quals = {n.qualname for n in result.graph.nodes}
    assert "c.c" not in quals
    assert "a.a" in quals
    assert result.changes is not None
    assert result.changes.removed == ["c.py"]


def test_refresh_reports_change_set(tmp_path):
    repo = _repo(tmp_path)
    engine = _engine(tmp_path)
    engine.refresh(str(repo))

    (repo / "a.py").write_text("def a():\n    return 9\n", encoding="utf-8")
    _write(repo / "d.py", "def d():\n    pass\n")
    result = engine.refresh(str(repo))

    assert result.changes is not None
    assert result.changes.changed == ["a.py"]
    assert result.changes.added == ["d.py"]
    assert result.changes.removed == []


def test_first_refresh_has_no_change_set(tmp_path):
    result = _engine(tmp_path).refresh(str(_repo(tmp_path)))
    assert result.changes is None


def test_changed_content_yields_new_snapshot_id(tmp_path):
    repo = _repo(tmp_path)
    engine = _engine(tmp_path)
    first = engine.refresh(str(repo)).snapshot.snapshot_id

    (repo / "b.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    second = engine.refresh(str(repo)).snapshot.snapshot_id
    assert first != second


def test_extract_cache_shared_across_engines(tmp_path):
    repo = _repo(tmp_path)
    cache_dir = tmp_path / "cache"
    DiscoveryEngine(DiscoveryConfig(cache_dir=cache_dir)).refresh(str(repo))

    # A fresh engine over the same cache dir reuses every extraction.
    second = DiscoveryEngine(DiscoveryConfig(cache_dir=cache_dir))
    result = second.refresh(str(repo))
    assert result.extract_stats["reused"] == 3
    assert result.extract_stats["analyzed"] == 0


def test_is_stale_detects_edit(tmp_path):
    repo = _repo(tmp_path)
    snapshot = _engine(tmp_path).resolve(str(repo))
    assert FreshnessTracker.is_stale(snapshot) is False

    (repo / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    assert FreshnessTracker.is_stale(snapshot) is True


def test_is_stale_detects_deletion(tmp_path):
    repo = _repo(tmp_path)
    snapshot = _engine(tmp_path).resolve(str(repo))
    (repo / "b.py").unlink()
    assert FreshnessTracker.is_stale(snapshot) is True
