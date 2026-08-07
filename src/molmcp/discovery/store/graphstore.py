"""GraphStore — the canonical SQLite store for one snapshot's graph.

Snapshots are immutable, so a ``graph.db`` is written exactly once by
:meth:`create` and thereafter only read. That removes any need for
update triggers or row-level sync. A derived FTS5 table is built at
create time when the SQLite build supports it; otherwise search falls
back to ``LIKE`` over indexed columns.
"""

from __future__ import annotations

import importlib.resources
import json
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from ..schema import CodeGraph, Edge, FileRecord, Node, UnresolvedRef

#: SQLite caps host variables per statement; batch reads chunk to fit.
_MAX_SQL_VARIABLES = 900

_SCHEMA_SQL = (
    importlib.resources.files("molmcp.discovery.store")
    .joinpath("schema.sql")
    .read_text(encoding="utf-8")
)


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _fts_match(text: str) -> str:
    """Build a forgiving FTS5 prefix query from free text."""
    # ``\w`` is Unicode-aware in Python.  The previous ASCII-only regex
    # silently discarded Chinese scientific terms and made a multilingual
    # collection impossible to search.
    tokens = re.findall(r"\w+", text, flags=re.UNICODE)
    terms = [f"{token}*" for token in tokens if len(token) >= 2 or not token.isascii()]
    return " OR ".join(terms)


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    """Cross-process advisory lock for one graph destination.

    The lock file deliberately survives the process.  Its contents are not
    state; the OS lock is.  Keeping it avoids a create/unlink race between two
    indexers targeting the same immutable snapshot.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":  # pragma: no cover - exercised in Windows CI
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:  # pragma: no branch - platform split
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    """Best-effort durability for the atomic directory entry replacement."""
    if not hasattr(os, "O_DIRECTORY"):
        return
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:  # pragma: no cover - filesystem dependent
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _build_fts(conn: sqlite3.Connection) -> bool:
    """Create and populate the derived FTS index; False if FTS5 absent."""
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE nodes_fts USING fts5("
            "node_id UNINDEXED, name, qualname, docstring, summary, "
            "tokenize='unicode61')"
        )
    except sqlite3.OperationalError:
        return False
    conn.execute(
        "INSERT INTO nodes_fts(node_id, name, qualname, docstring, summary) "
        "SELECT id, name, qualname, IFNULL(docstring, ''), IFNULL(summary, '') "
        "FROM nodes"
    )
    return True


class GraphStore:
    """Read/write access to a single snapshot's ``graph.db``."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._read_conn: sqlite3.Connection | None = None
        self._fts: bool | None = None

    # -- connections -------------------------------------------------

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
        finally:
            conn.close()

    def _conn(self) -> sqlite3.Connection:
        if self._read_conn is None:
            conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            self._read_conn = conn
        return self._read_conn

    def close(self) -> None:
        if self._read_conn is not None:
            self._read_conn.close()
            self._read_conn = None

    def exists(self) -> bool:
        return self.db_path.is_file()

    # -- creation ----------------------------------------------------

    def create(self, graph: CodeGraph, meta: dict) -> None:
        """Atomically build and publish ``graph``.

        A complete database is created next to the destination, fsynced, and
        moved into place while holding a per-destination process lock.  Readers
        therefore observe either the previous complete graph or the new one,
        never a partially populated database.
        """
        self.close()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.db_path.with_suffix(self.db_path.suffix + ".lock")
        with _exclusive_file_lock(lock_path):
            fd, raw_tmp = tempfile.mkstemp(
                prefix=f".{self.db_path.name}.",
                suffix=".tmp",
                dir=self.db_path.parent,
            )
            os.close(fd)
            tmp_path = Path(raw_tmp)
            try:
                self._create_at(tmp_path, graph, meta)
                _fsync_file(tmp_path)
                os.replace(tmp_path, self.db_path)
                _fsync_directory(self.db_path.parent)
            finally:
                tmp_path.unlink(missing_ok=True)

    def _create_at(self, path: Path, graph: CodeGraph, meta: dict) -> None:
        with sqlite3.connect(path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executescript(_SCHEMA_SQL)
            # The published graph is immutable.  WAL would leave sidecar files
            # outside the atomic replacement boundary, so build in DELETE mode.
            conn.execute("PRAGMA journal_mode=DELETE")
            self._insert_files(conn, graph.files)
            self._insert_nodes(conn, graph.nodes)
            self._insert_edges(conn, graph.edges)
            self._insert_unresolved(conn, graph.unresolved)
            fts_available = _build_fts(conn)
            full_meta = dict(meta)
            full_meta["fts_available"] = fts_available
            self._insert_meta(conn, full_meta)
            conn.commit()

    @staticmethod
    def _insert_meta(conn: sqlite3.Connection, meta: dict) -> None:
        conn.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?)",
            [(k, _dumps(v)) for k, v in meta.items()],
        )

    @staticmethod
    def _insert_files(conn: sqlite3.Connection, files: list[FileRecord]) -> None:
        conn.executemany(
            "INSERT INTO files(path, language, content_hash, size, "
            "node_count, errors, indexed_at) VALUES(?,?,?,?,?,?,?)",
            [
                (
                    f.path,
                    f.language,
                    f.content_hash,
                    f.size,
                    f.node_count,
                    _dumps(f.errors),
                    f.indexed_at,
                )
                for f in files
            ],
        )

    @staticmethod
    def _insert_nodes(conn: sqlite3.Connection, nodes: list[Node]) -> None:
        conn.executemany(
            "INSERT INTO nodes(id, kind, name, qualname, language, "
            "file, start_line, end_line, signature, docstring, summary, "
            "decorators, bases, visibility, is_exported, is_async, "
            "is_abstract, metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    n.id,
                    str(n.kind),
                    n.name,
                    n.qualname,
                    n.language,
                    n.file,
                    n.start_line,
                    n.end_line,
                    n.signature,
                    n.docstring,
                    n.summary,
                    _dumps(n.decorators),
                    _dumps(n.bases),
                    str(n.visibility),
                    int(n.is_exported),
                    int(n.is_async),
                    int(n.is_abstract),
                    _dumps(n.metadata),
                )
                for n in nodes
            ],
        )

    @staticmethod
    def _insert_edges(conn: sqlite3.Connection, edges: list[Edge]) -> None:
        conn.executemany(
            "INSERT INTO edges(source, target, kind, provenance, file, "
            "line, metadata) VALUES(?,?,?,?,?,?,?)",
            [
                (
                    e.source,
                    e.target,
                    str(e.kind),
                    str(e.provenance),
                    e.file,
                    e.line,
                    _dumps(e.metadata),
                )
                for e in edges
            ],
        )

    @staticmethod
    def _insert_unresolved(conn: sqlite3.Connection, refs: list[UnresolvedRef]) -> None:
        conn.executemany(
            "INSERT INTO unresolved(from_node, name, kind, file, line) "
            "VALUES(?,?,?,?,?)",
            [(r.from_node, r.name, str(r.kind), r.file, r.line) for r in refs],
        )

    # -- whole-graph reads -------------------------------------------

    def read_meta(self) -> dict:
        out: dict = {}
        for row in self._conn().execute("SELECT key, value FROM meta"):
            try:
                out[row["key"]] = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                out[row["key"]] = row["value"]
        return out

    def fts_available(self) -> bool:
        if self._fts is None:
            self._fts = bool(self.read_meta().get("fts_available", False))
        return self._fts

    def load_graph(self) -> CodeGraph:
        conn = self._conn()
        return CodeGraph(
            files=[
                _row_to_file(r)
                for r in conn.execute("SELECT * FROM files ORDER BY path")
            ],
            nodes=[
                _row_to_node(r) for r in conn.execute("SELECT * FROM nodes ORDER BY id")
            ],
            edges=[
                _row_to_edge(r) for r in conn.execute("SELECT * FROM edges ORDER BY id")
            ],
            unresolved=[
                _row_to_unresolved(r)
                for r in conn.execute("SELECT * FROM unresolved ORDER BY id")
            ],
        )

    # -- targeted reads ----------------------------------------------

    def get_node(self, node_id: str) -> Node | None:
        row = (
            self._conn()
            .execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
            .fetchone()
        )
        return _row_to_node(row) if row else None

    def get_nodes(self, node_ids: Iterable[str]) -> dict[str, Node]:
        """Load many nodes per statement, keyed by id.

        Callers almost always know every id up front — a module's children,
        an edge list's endpoints — and issuing one ``WHERE id = ?`` apiece
        cost ``outline`` 1312 round trips over 75 modules.

        Chunked because SQLite caps host variables per statement; missing
        ids are simply absent from the result.
        """
        unique = list(dict.fromkeys(node_ids))
        if not unique:
            return {}
        found: dict[str, Node] = {}
        conn = self._conn()
        for start in range(0, len(unique), _MAX_SQL_VARIABLES):
            chunk = unique[start : start + _MAX_SQL_VARIABLES]
            placeholders = ",".join("?" for _ in chunk)
            for row in conn.execute(
                f"SELECT * FROM nodes WHERE id IN ({placeholders})", chunk
            ):
                node = _row_to_node(row)
                found[node.id] = node
        return found

    def nodes_by_qualname(self, qualname: str) -> list[Node]:
        return [
            _row_to_node(r)
            for r in self._conn().execute(
                "SELECT * FROM nodes WHERE qualname = ? ORDER BY id",
                (qualname,),
            )
        ]

    def nodes_by_kind(self, kind: str, limit: int | None = None) -> list[Node]:
        sql = "SELECT * FROM nodes WHERE kind = ? ORDER BY qualname"
        params: tuple = (str(kind),)
        if limit is not None:
            sql += " LIMIT ?"
            params = (str(kind), limit)
        return [_row_to_node(r) for r in self._conn().execute(sql, params)]

    def files(self) -> list[FileRecord]:
        return [
            _row_to_file(r)
            for r in self._conn().execute("SELECT * FROM files ORDER BY path")
        ]

    def edges_from(self, node_id: str, kind: str | None = None) -> list[Edge]:
        if kind is None:
            sql = "SELECT * FROM edges WHERE source = ? ORDER BY id"
            params: tuple = (node_id,)
        else:
            sql = "SELECT * FROM edges WHERE source = ? AND kind = ? ORDER BY id"
            params = (node_id, str(kind))
        return [_row_to_edge(r) for r in self._conn().execute(sql, params)]

    def edges_to(self, node_id: str, kind: str | None = None) -> list[Edge]:
        if kind is None:
            sql = "SELECT * FROM edges WHERE target = ? ORDER BY id"
            params: tuple = (node_id,)
        else:
            sql = "SELECT * FROM edges WHERE target = ? AND kind = ? ORDER BY id"
            params = (node_id, str(kind))
        return [_row_to_edge(r) for r in self._conn().execute(sql, params)]

    def incoming_edge_counts(
        self, node_ids: list[str], kind: str, *, provenance: str | None = None
    ) -> dict[str, int]:
        """Count incoming edges of ``kind`` per node id in one statement.

        When ``provenance`` is given, only edges with that provenance are
        counted — callers use this to exclude guessed (heuristic) edges from
        relevance signals. Ids with no matching in-edges are absent.
        """
        if not node_ids:
            return {}
        placeholders = ",".join("?" for _ in node_ids)
        sql = (
            "SELECT target, COUNT(*) AS n FROM edges "
            f"WHERE kind = ? AND target IN ({placeholders})"
        )
        params: tuple = (str(kind), *node_ids)
        if provenance is not None:
            sql += " AND provenance = ?"
            params = (*params, str(provenance))
        rows = self._conn().execute(sql + " GROUP BY target", params)
        return {row["target"]: row["n"] for row in rows}

    def search(
        self, query: str, kind: str | None = None, limit: int = 30
    ) -> list[Node]:
        """Rank symbols by relevance to free-text ``query``.

        Uses the FTS5 index when available, else a ``LIKE`` scan. Results
        are de-duplicated and capped at ``limit``.
        """
        conn = self._conn()
        # The kind filter is part of the query, not a post-filter. Dropping
        # wrong-kind rows after a fixed-size prefetch starved rare kinds:
        # asking for the ten matching classes among forty matching functions
        # returned whatever few classes happened to rank inside the window.
        kind_clause = " AND n.kind = ?" if kind is not None else ""
        kind_params: tuple = (str(kind),) if kind is not None else ()
        ids: list[str] = []
        if self.fts_available():
            match = _fts_match(query)
            if match:
                try:
                    ids = [
                        r["node_id"]
                        for r in conn.execute(
                            # Field-weighted bm25: a hit in the symbol NAME
                            # far outweighs one buried in a docstring, so
                            # `read_lammps_data` beats a reader that merely
                            # mentions "frame" in prose. Column order is
                            # (node_id, name, qualname, docstring, summary).
                            "SELECT f.node_id FROM nodes_fts f "
                            "JOIN nodes n ON n.id = f.node_id "
                            f"WHERE nodes_fts MATCH ?{kind_clause} "
                            "ORDER BY bm25(nodes_fts, 0.0, 10.0, 5.0, "
                            "1.0, 2.0) LIMIT ?",
                            (match, *kind_params, limit),
                        )
                    ]
                except sqlite3.OperationalError:
                    ids = []
        if not ids:
            like = f"%{query}%"
            ids = [
                r["id"]
                for r in conn.execute(
                    "SELECT n.id FROM nodes n WHERE (n.name LIKE ? "
                    "OR n.qualname LIKE ? OR IFNULL(n.summary, '') LIKE ?)"
                    f"{kind_clause} ORDER BY n.qualname LIMIT ?",
                    (like, like, like, *kind_params, limit),
                )
            ]
        found = self.get_nodes(ids)
        return [found[node_id] for node_id in ids if node_id in found]


def _row_to_node(row: sqlite3.Row) -> Node:
    return Node(
        id=row["id"],
        kind=row["kind"],
        name=row["name"],
        qualname=row["qualname"],
        language=row["language"],
        file=row["file"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        signature=row["signature"],
        docstring=row["docstring"],
        summary=row["summary"],
        decorators=json.loads(row["decorators"]),
        bases=json.loads(row["bases"]),
        visibility=row["visibility"],
        is_exported=bool(row["is_exported"]),
        is_async=bool(row["is_async"]),
        is_abstract=bool(row["is_abstract"]),
        metadata=json.loads(row["metadata"]),
    )


def _row_to_edge(row: sqlite3.Row) -> Edge:
    return Edge(
        id=row["id"],
        source=row["source"],
        target=row["target"],
        kind=row["kind"],
        provenance=row["provenance"],
        file=row["file"],
        line=row["line"],
        metadata=json.loads(row["metadata"]),
    )


def _row_to_unresolved(row: sqlite3.Row) -> UnresolvedRef:
    return UnresolvedRef(
        id=row["id"],
        from_node=row["from_node"],
        name=row["name"],
        kind=row["kind"],
        file=row["file"],
        line=row["line"],
    )


def _row_to_file(row: sqlite3.Row) -> FileRecord:
    return FileRecord(
        path=row["path"],
        language=row["language"],
        content_hash=row["content_hash"],
        size=row["size"],
        node_count=row["node_count"],
        errors=json.loads(row["errors"]),
        indexed_at=row["indexed_at"],
    )
