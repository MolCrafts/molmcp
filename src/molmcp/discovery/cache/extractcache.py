"""ExtractCache — a content-addressed cache of per-file extraction.

Extraction of one file is a pure function of its content and the
analyzer version, so it is cached keyed by ``(path, content_hash,
analyzer_version)``. This makes every (re-)index incremental: unchanged
files skip the analyzer entirely.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from ..analyzers.base import AnalyzerResult
from ..schema import Edge, Node, UnresolvedRef

_CREATE = """
CREATE TABLE IF NOT EXISTS extract (
    path             TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    analyzer_version TEXT NOT NULL,
    payload          TEXT NOT NULL,
    created_at       REAL NOT NULL,
    PRIMARY KEY (path, content_hash, analyzer_version)
)
"""


def _encode(result: AnalyzerResult) -> str:
    return json.dumps(
        {
            "nodes": [n.to_dict() for n in result.nodes],
            "edges": [e.to_dict() for e in result.edges],
            "unresolved": [u.to_dict() for u in result.unresolved],
            "errors": list(result.errors),
        },
        ensure_ascii=False,
    )


def _decode(payload: str) -> AnalyzerResult:
    data = json.loads(payload)
    return AnalyzerResult(
        nodes=[Node.from_dict(d) for d in data["nodes"]],
        edges=[Edge.from_dict(d) for d in data["edges"]],
        unresolved=[UnresolvedRef.from_dict(d) for d in data["unresolved"]],
        errors=list(data.get("errors", [])),
    )


class ExtractCache:
    """A SQLite-backed cache of per-file :class:`AnalyzerResult` objects."""

    def __init__(self, db_path: str | Path, analyzer_version: int | str) -> None:
        self.db_path = Path(db_path)
        self.analyzer_version = str(analyzer_version)
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA busy_timeout=5000")
            # Every plane process opens this same file, so a rollback journal
            # would serialize each of them behind whichever one is indexing —
            # readers hit the busy timeout and the tool call stalls for
            # seconds. WAL lets them read the last commit instead of waiting.
            # Unlike a published graph.db this file is never atomically
            # replaced, so the -wal/-shm sidecars are safe here.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(_CREATE)
            conn.commit()
            self._conn = conn
        return self._conn

    def get(self, path: str, content_hash: str) -> AnalyzerResult | None:
        row = (
            self._connect()
            .execute(
                "SELECT payload FROM extract WHERE path=? AND content_hash=? "
                "AND analyzer_version=?",
                (path, content_hash, self.analyzer_version),
            )
            .fetchone()
        )
        if row is None:
            return None
        try:
            return _decode(row[0])
        except (json.JSONDecodeError, KeyError):
            return None

    def put(self, path: str, content_hash: str, result: AnalyzerResult) -> None:
        self._connect().execute(
            "INSERT OR REPLACE INTO extract"
            "(path, content_hash, analyzer_version, payload, created_at) "
            "VALUES(?,?,?,?,?)",
            (path, content_hash, self.analyzer_version, _encode(result), time.time()),
        )

    def flush(self) -> None:
        if self._conn is not None:
            self._conn.commit()

    def exists(self) -> bool:
        """True when the cache file has been created on disk."""
        return self.db_path.is_file()

    def entry_count(self) -> int:
        return self._connect().execute("SELECT COUNT(*) FROM extract").fetchone()[0]

    def prune_older_than(self, cutoff: float) -> int:
        """Drop payloads written before ``cutoff``; returns the row count.

        Age is write time, not last use, so a file that has not changed in a
        full retention window is re-analyzed once and re-cached with a fresh
        timestamp. Tracking real recency would turn every cache *hit* into a
        write, which is the wrong trade for a cache this hot.
        """
        conn = self._connect()
        removed = conn.execute(
            "DELETE FROM extract WHERE created_at < ?", (cutoff,)
        ).rowcount
        conn.commit()
        return removed

    def enforce_size_limit(self, max_bytes: int, *, shed: float = 0.1) -> int:
        """Shed the oldest entries while the cache is over ``max_bytes``.

        Age alone does not bound this cache. A single indexed environment can
        hold tens of thousands of files whose extraction payloads are fat
        JSON, all of it current and none of it stale — which is how a real
        cache reached 3.6 GB with only a few hundred rows past its retention
        window. This is the ceiling that actually holds.

        Measured against :meth:`used_bytes`, not the file size: deleting rows
        frees pages for reuse but never shrinks the file, so growth stops at
        the high-water mark and only ``vacuum`` hands the space back.
        ``max_bytes <= 0`` disables the ceiling.

        Args:
            max_bytes: Live content the cache may hold.
            shed: Fraction of the oldest rows to drop per pass. A caller that
                wants the cache brought all the way under the ceiling loops
                until this returns 0.

        Returns:
            The number of rows removed.
        """
        if max_bytes <= 0 or self.used_bytes() <= max_bytes:
            return 0
        conn = self._connect()
        total = conn.execute("SELECT COUNT(*) FROM extract").fetchone()[0]
        if not total:
            return 0
        removed = conn.execute(
            "DELETE FROM extract WHERE rowid IN "
            "(SELECT rowid FROM extract ORDER BY created_at LIMIT ?)",
            (max(int(total * shed), 1),),
        ).rowcount
        conn.commit()
        return removed

    def vacuum(self) -> None:
        """Return freed pages to the filesystem.

        Pruning alone only marks pages reusable, so a cache that once grew to
        gigabytes keeps occupying them. Exclusive and proportional to file
        size — an operator action (``molmcp cache prune --vacuum``), never
        something a tool call does behind the user's back.
        """
        self._connect().execute("VACUUM")

    def size_bytes(self) -> int:
        """On-disk size of the cache, including its write-ahead log."""
        total = 0
        for suffix in ("", "-wal", "-shm"):
            path = self.db_path.with_name(self.db_path.name + suffix)
            if path.is_file():
                total += path.stat().st_size
        return total

    def used_bytes(self) -> int:
        """Bytes of *live* content, excluding pages freed by earlier deletes.

        The size ceiling has to read this rather than the file size: deleting
        rows never shrinks the file, so a ceiling that watched bytes-on-disk
        would find itself still over the limit after every shed and keep
        cutting until the cache was empty. Both pragmas are O(1).
        """
        conn = self._connect()
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        free = conn.execute("PRAGMA freelist_count").fetchone()[0]
        return max(page_count - free, 0) * page_size

    def close(self) -> None:
        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None
