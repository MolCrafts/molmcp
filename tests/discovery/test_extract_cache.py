"""ExtractCache durability and bounded-growth tests.

The extract cache is the one long-lived *mutable* store in the discovery
tree: every plane process opens the same ``extract.db``. It therefore has
two obligations the immutable snapshot graphs do not — a reader must not
serialize behind a writer, and the file must not grow forever.
"""

from __future__ import annotations

import sqlite3
import time

from molmcp.discovery import DiscoveryConfig, DiscoveryEngine
from molmcp.discovery.analyzers.base import AnalyzerResult
from molmcp.discovery.cache import ExtractCache


def _cache(tmp_path, version: str = "v1") -> ExtractCache:
    return ExtractCache(tmp_path / "extract.db", version)


def _put(cache: ExtractCache, path: str, *, created_at: float | None = None) -> None:
    cache.put(path, f"hash-of-{path}", AnalyzerResult())
    cache.flush()
    if created_at is None:
        return
    conn = sqlite3.connect(cache.db_path)
    try:
        conn.execute(
            "UPDATE extract SET created_at = ? WHERE path = ?", (created_at, path)
        )
        conn.commit()
    finally:
        conn.close()


def _put_bulk(
    cache: ExtractCache, count: int, *, payload_bytes: int = 64 * 1024
) -> None:
    """Fill the cache with realistically sized payloads.

    A real entry is tens of kilobytes of node/edge JSON. Page accounting only
    moves at that scale — a handful of empty AnalyzerResults share one page,
    so deleting them frees nothing and hides whatever the ceiling does.
    """
    now = time.time()
    conn = cache._connect()
    conn.executemany(
        "INSERT OR REPLACE INTO extract VALUES(?,?,?,?,?)",
        [
            (f"f{i}.py", "h", "v1", "x" * payload_bytes, now - (count - i) * 3600)
            for i in range(count)
        ],
    )
    conn.commit()


def _seed(engine, path: str, analyzer_version: str, created_at: float) -> None:
    """Write a payload straight into an engine's cache, bypassing extraction."""
    conn = engine.extract_cache._connect()
    conn.execute(
        "INSERT OR REPLACE INTO extract VALUES(?,?,?,?,?)",
        (path, "h", analyzer_version, "{}", created_at),
    )
    conn.commit()


def _count(db_path, where: str = "1=1") -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM extract WHERE {where}").fetchone()[0]
    finally:
        conn.close()


class TestExtractCacheJournalMode:
    def test_uses_wal_so_a_reader_never_waits_for_a_writer(self, tmp_path):
        cache = _cache(tmp_path)
        try:
            _put(cache, "a.py")
            conn = sqlite3.connect(cache.db_path)
            try:
                mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            finally:
                conn.close()
        finally:
            cache.close()

        assert mode.lower() == "wal"

    def test_reader_sees_committed_rows_while_a_writer_holds_a_transaction(
        self, tmp_path
    ):
        """A second plane process must not stall behind an indexing run."""
        writer = _cache(tmp_path)
        try:
            _put(writer, "a.py")
            held = writer._connect()
            held.execute("BEGIN IMMEDIATE")
            held.execute(
                "INSERT OR REPLACE INTO extract VALUES(?,?,?,?,?)",
                ("b.py", "h", "v1", "{}", time.time()),
            )

            reader = sqlite3.connect(writer.db_path)
            try:
                reader.execute("PRAGMA busy_timeout=1000")
                rows = reader.execute("SELECT COUNT(*) FROM extract").fetchone()[0]
            finally:
                reader.close()
            held.rollback()
        finally:
            writer.close()

        # Only the committed row is visible; crucially, the read did not block.
        assert rows == 1


class TestExtractCachePrune:
    def test_prune_drops_entries_older_than_the_cutoff(self, tmp_path):
        cache = _cache(tmp_path)
        try:
            now = time.time()
            _put(cache, "old.py", created_at=now - 40 * 86400)
            _put(cache, "fresh.py", created_at=now)

            removed = cache.prune_older_than(now - 30 * 86400)

            assert removed == 1
            assert cache.get("fresh.py", "hash-of-fresh.py") is not None
            assert cache.get("old.py", "hash-of-old.py") is None
        finally:
            cache.close()

    def test_prune_reports_zero_when_nothing_is_stale(self, tmp_path):
        cache = _cache(tmp_path)
        try:
            _put(cache, "fresh.py")
            assert cache.prune_older_than(time.time() - 30 * 86400) == 0
        finally:
            cache.close()


class TestExtractCacheSizeLimit:
    """Age is the wrong bound on its own.

    Measured on a real cache: 3.6 GB across 59k rows, of which only 376 were
    past a 30-day window and 3.34 GB belonged to the *current* analyzer
    generation. Nothing about that is stale — the cache simply had no ceiling.
    """

    def test_sheds_oldest_entries_once_over_the_limit(self, tmp_path):
        cache = _cache(tmp_path)
        try:
            now = time.time()
            for i in range(20):
                _put(cache, f"f{i}.py", created_at=now - (20 - i) * 3600)

            removed = cache.enforce_size_limit(1)

            assert removed > 0
            assert cache.get("f0.py", "hash-of-f0.py") is None
            assert cache.get("f19.py", "hash-of-f19.py") is not None
        finally:
            cache.close()

    def test_leaves_a_cache_inside_the_limit_untouched(self, tmp_path):
        cache = _cache(tmp_path)
        try:
            _put(cache, "a.py")
            assert cache.enforce_size_limit(512 * 1024 * 1024) == 0
            assert cache.get("a.py", "hash-of-a.py") is not None
        finally:
            cache.close()

    def test_limit_of_zero_disables_the_ceiling(self, tmp_path):
        cache = _cache(tmp_path)
        try:
            _put(cache, "a.py")
            assert cache.enforce_size_limit(0) == 0
        finally:
            cache.close()

    def test_repeated_sheds_converge_instead_of_emptying_the_cache(self, tmp_path):
        """Deleting rows never shrinks the file, so a ceiling measured on
        bytes-on-disk would stay over the limit forever and cut until nothing
        was left. The ceiling must read live content instead."""
        cache = _cache(tmp_path)
        try:
            _put_bulk(cache, 60)
            ceiling = cache.used_bytes() // 2

            for _ in range(50):
                if cache.enforce_size_limit(ceiling) == 0:
                    break

            assert cache.used_bytes() <= ceiling
            assert cache.entry_count() > 0
        finally:
            cache.close()

    def test_used_bytes_drops_after_a_shed_though_the_file_does_not(self, tmp_path):
        cache = _cache(tmp_path)
        try:
            _put_bulk(cache, 60)
            before_used = cache.used_bytes()
            before_file = cache.size_bytes()

            cache.enforce_size_limit(1)

            assert cache.used_bytes() < before_used
            assert cache.size_bytes() >= before_file
        finally:
            cache.close()


class TestEngineBoundsTheExtractCache:
    def test_indexing_prunes_payloads_orphaned_by_an_earlier_run(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "m.py").write_text("x = 1\n", encoding="utf-8")
        config = DiscoveryConfig(cache_dir=tmp_path / "cache", max_cache_age_days=30)
        engine = DiscoveryEngine(config)

        # An earlier process left a payload keyed to an analyzer generation
        # that no longer exists: nothing will read it again, so only pruning
        # can reclaim it.
        _seed(engine, "stale.py", "ancient-analyzer", time.time() - 90 * 86400)

        engine.index(str(repo))
        db_path = engine.extract_cache.db_path
        engine.close()

        assert _count(db_path, "path = 'stale.py'") == 0

    def test_pruning_keeps_payloads_inside_the_retention_window(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "m.py").write_text("x = 1\n", encoding="utf-8")
        config = DiscoveryConfig(cache_dir=tmp_path / "cache", max_cache_age_days=30)
        engine = DiscoveryEngine(config)
        engine.index(str(repo))
        (repo / "m.py").write_text("x = 2\n", encoding="utf-8")
        engine.refresh(str(repo))
        db_path = engine.extract_cache.db_path
        engine.close()

        assert _count(db_path) >= 1

    def test_retention_disabled_keeps_everything(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "m.py").write_text("x = 1\n", encoding="utf-8")
        config = DiscoveryConfig(cache_dir=tmp_path / "cache", max_cache_age_days=0)
        engine = DiscoveryEngine(config)
        _seed(engine, "ancient.py", "old", time.time() - 900 * 86400)

        engine.index(str(repo))
        db_path = engine.extract_cache.db_path
        engine.close()

        assert _count(db_path, "path = 'ancient.py'") == 1

    def test_indexing_enforces_the_configured_ceiling(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "m.py").write_text("x = 1\n", encoding="utf-8")
        config = DiscoveryConfig(
            cache_dir=tmp_path / "cache", max_extract_cache_bytes=1
        )
        engine = DiscoveryEngine(config)
        now = time.time()
        for i in range(10):
            _seed(engine, f"bulk{i}.py", "v1", now - (10 - i) * 3600)

        engine.index(str(repo))
        db_path = engine.extract_cache.db_path
        engine.close()

        assert _count(db_path, "path = 'bulk0.py'") == 0

    def test_pruning_runs_once_per_process(self, tmp_path):
        """A per-index full-table delete would cost more than it reclaims."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "m.py").write_text("x = 1\n", encoding="utf-8")
        config = DiscoveryConfig(cache_dir=tmp_path / "cache", max_cache_age_days=30)
        engine = DiscoveryEngine(config)
        engine.index(str(repo))

        _seed(engine, "later.py", "old", time.time() - 90 * 86400)
        (repo / "m.py").write_text("x = 2\n", encoding="utf-8")
        engine.refresh(str(repo))
        db_path = engine.extract_cache.db_path
        engine.close()

        assert _count(db_path, "path = 'later.py'") == 1


class TestVacuumActuallyReclaims:
    """`vacuumed: true` has to mean the space came back.

    Under WAL, VACUUM rebuilds the database *into the log*; the main file
    only shrinks once a checkpoint folds it back. Reporting success off the
    VACUUM alone once claimed a 3.5 GB file had been reclaimed while it sat
    there untouched beside a 2.3 GB write-ahead log.
    """

    def test_vacuum_shrinks_the_file_and_reports_what_it_freed(self, tmp_path):
        cache = _cache(tmp_path)
        try:
            _put_bulk(cache, 200)
            cache.prune_older_than(time.time() + 1)  # drop everything
            before = cache.size_bytes()

            report = cache.vacuum()

            assert report["checkpointed"] is True
            assert report["skipped"] is False
            assert report["before_bytes"] == before
            assert report["after_bytes"] < before
            assert cache.size_bytes() < before
        finally:
            cache.close()

    def test_a_blocked_checkpoint_is_reported_not_claimed(self, tmp_path):
        cache = _cache(tmp_path)
        reader = None
        try:
            _put_bulk(cache, 60)
            cache.prune_older_than(time.time() + 1)
            # A second connection mid-read is what a live plane server is.
            reader = sqlite3.connect(cache.db_path, isolation_level=None)
            reader.execute("BEGIN")
            cursor = reader.execute("SELECT path FROM extract")
            cursor.fetchone()

            report = cache.vacuum()

            assert report["checkpointed"] is False
        finally:
            if reader is not None:
                reader.close()
            cache.close()

    def test_a_blocked_vacuum_costs_nothing(self, tmp_path):
        """A refused attempt must not be worse than no attempt.

        VACUUM under WAL writes the whole rebuild into the log before the
        checkpoint can fail, so retrying against a live server grew a real
        cache by half a gigabyte per attempt. Check for readers first.
        """
        cache = _cache(tmp_path)
        reader = None
        try:
            _put_bulk(cache, 200)
            # A reader pinned *behind* the head of the log is what a live
            # plane server looks like mid-query while indexing continues.
            reader = sqlite3.connect(cache.db_path, isolation_level=None)
            reader.execute("BEGIN")
            reader.execute("SELECT path FROM extract").fetchone()
            _put_bulk(cache, 40, payload_bytes=16 * 1024)
            before = cache.size_bytes()

            report = cache.vacuum()

            assert report["checkpointed"] is False
            assert report["skipped"] is True
            assert cache.size_bytes() == before
        finally:
            if reader is not None:
                reader.close()
            cache.close()


class TestCacheFileNaming:
    """The file has to announce that it is disposable.

    A 6 GB file called ``extract.db`` tells an operator nothing about
    whether it is safe to delete — which is exactly the question it
    provoked. ``extraction-cache.db`` answers it in the name.
    """

    def test_the_cache_lives_at_a_self_describing_name(self, tmp_path):
        from molmcp.discovery.cache import SnapshotCache
        from molmcp.discovery.config import DiscoveryConfig

        cache = SnapshotCache(DiscoveryConfig(cache_dir=tmp_path))

        assert cache.extract_db_path().name == "extraction-cache.db"

    def test_a_legacy_extract_db_is_reclaimed(self, tmp_path):
        """Renaming must not strand the old file; it can be gigabytes."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "m.py").write_text("x = 1\n", encoding="utf-8")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        legacy = cache_dir / "extract.db"
        legacy.write_bytes(b"x" * 2048)
        (cache_dir / "extract.db-wal").write_bytes(b"x" * 512)

        engine = DiscoveryEngine(DiscoveryConfig(cache_dir=cache_dir))
        engine.index(str(repo))
        engine.close()

        assert not legacy.exists()
        assert not (cache_dir / "extract.db-wal").exists()
        assert (cache_dir / "extraction-cache.db").is_file()
