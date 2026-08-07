"""`molmcp cache` — the operator's view of, and handle on, the shared cache.

Pruning inside a tool call is deliberately conservative (once per process,
no VACUUM), so a cache that already grew to gigabytes needs an explicit
command to hand those pages back to the filesystem.
"""

from __future__ import annotations

import json
import sqlite3
import time

from molmcp import cli


def _config(tmp_path, cache_dir) -> None:
    (tmp_path / "molcrafts.json").write_text(
        json.dumps(
            {
                "schema_version": "2",
                "sources": {"project": "."},
                "cache_dir": str(cache_dir),
                "watch": False,
            }
        ),
        encoding="utf-8",
    )


def _seed(cache_dir, rows: list[tuple[str, float]]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cache_dir / "extract.db")
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS extract ("
            "path TEXT NOT NULL, content_hash TEXT NOT NULL, "
            "analyzer_version TEXT NOT NULL, payload TEXT NOT NULL, "
            "created_at REAL NOT NULL, "
            "PRIMARY KEY (path, content_hash, analyzer_version))"
        )
        conn.executemany(
            "INSERT OR REPLACE INTO extract VALUES(?,?,?,?,?)",
            [(path, "h", "v1", "{}" * 200, created_at) for path, created_at in rows],
        )
        conn.commit()
    finally:
        conn.close()


def _entries(cache_dir) -> int:
    conn = sqlite3.connect(cache_dir / "extract.db")
    try:
        return conn.execute("SELECT COUNT(*) FROM extract").fetchone()[0]
    finally:
        conn.close()


def test_cache_reports_size_and_entry_count(monkeypatch, tmp_path, capsys):
    cache_dir = tmp_path / "cache"
    _seed(cache_dir, [("a.py", time.time()), ("b.py", time.time())])
    _config(tmp_path, cache_dir)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["cache"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["extract_cache"]["entries"] == 2
    assert payload["extract_cache"]["size_bytes"] > 0
    assert payload["extract_cache"]["used_bytes"] > 0
    assert payload["extract_cache"]["path"].endswith("extract.db")


def test_cache_separates_live_content_from_disk_footprint(
    monkeypatch, tmp_path, capsys
):
    """After a prune the file keeps its size; only live content drops."""
    cache_dir = tmp_path / "cache"
    now = time.time()
    _seed(cache_dir, [(f"old{i}.py", now - 90 * 86400) for i in range(400)])
    _config(tmp_path, cache_dir)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["cache", "--prune"]) == 0

    entry = json.loads(capsys.readouterr().out)["extract_cache"]
    assert entry["used_bytes"] < entry["size_bytes"]
    assert entry["reclaimable_bytes"] == entry["size_bytes"] - entry["used_bytes"]


def test_cache_prune_drops_payloads_past_the_retention_window(
    monkeypatch, tmp_path, capsys
):
    cache_dir = tmp_path / "cache"
    now = time.time()
    _seed(cache_dir, [("old.py", now - 90 * 86400), ("fresh.py", now)])
    _config(tmp_path, cache_dir)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["cache", "--prune"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["pruned"] == 1
    assert _entries(cache_dir) == 1


def test_cache_vacuum_returns_freed_pages_to_the_filesystem(
    monkeypatch, tmp_path, capsys
):
    cache_dir = tmp_path / "cache"
    now = time.time()
    stale = [(f"old{i}.py", now - 90 * 86400) for i in range(400)]
    _seed(cache_dir, [*stale, ("fresh.py", now)])
    before = (cache_dir / "extract.db").stat().st_size
    _config(tmp_path, cache_dir)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["cache", "--vacuum"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["pruned"] == 400
    assert payload["vacuumed"] is True
    assert (cache_dir / "extract.db").stat().st_size < before


def test_cache_reports_a_busy_cache_without_a_traceback(monkeypatch, tmp_path, capsys):
    """Live plane servers hold the cache; that is an operating condition."""
    cache_dir = tmp_path / "cache"
    _seed(cache_dir, [("old.py", time.time() - 90 * 86400)])
    _config(tmp_path, cache_dir)
    monkeypatch.chdir(tmp_path)

    holder = sqlite3.connect(cache_dir / "extract.db", isolation_level=None)
    try:
        holder.execute("BEGIN EXCLUSIVE")
        assert cli.main(["cache", "--prune"]) == 2
    finally:
        holder.close()

    err = capsys.readouterr().err
    assert err.startswith("molmcp:")
    assert "molmcp serve" in err


def test_cache_is_read_only_without_flags(monkeypatch, tmp_path, capsys):
    cache_dir = tmp_path / "cache"
    _seed(cache_dir, [("old.py", time.time() - 90 * 86400)])
    _config(tmp_path, cache_dir)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["cache"]) == 0

    assert _entries(cache_dir) == 1
    assert json.loads(capsys.readouterr().out)["pruned"] is None
