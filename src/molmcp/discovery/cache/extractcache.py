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

    def entry_count(self) -> int:
        return self._connect().execute("SELECT COUNT(*) FROM extract").fetchone()[0]

    def prune_older_than(self, cutoff: float) -> int:
        conn = self._connect()
        removed = conn.execute(
            "DELETE FROM extract WHERE created_at < ?", (cutoff,)
        ).rowcount
        conn.commit()
        return removed

    def close(self) -> None:
        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None
