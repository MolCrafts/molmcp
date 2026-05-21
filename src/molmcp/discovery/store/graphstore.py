"""GraphStore — the canonical SQLite store for one snapshot's graph.

Snapshots are immutable, so a ``graph.db`` is written exactly once by
:meth:`create` and thereafter only read. That removes any need for
update triggers or row-level sync.
"""

from __future__ import annotations

import importlib.resources
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..schema import CodeGraph, Edge, FileRecord, Node, UnresolvedRef

_SCHEMA_SQL = (
    importlib.resources.files("molmcp.discovery.store")
    .joinpath("schema.sql")
    .read_text(encoding="utf-8")
)


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


class GraphStore:
    """Read/write access to a single snapshot's ``graph.db``."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def exists(self) -> bool:
        return self.db_path.is_file()

    def create(self, graph: CodeGraph, meta: dict) -> None:
        """Write ``graph`` to a fresh database, replacing any existing one."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self.db_path.unlink()
        with self.connect() as conn:
            conn.executescript(_SCHEMA_SQL)
            conn.execute("PRAGMA journal_mode=WAL")
            self._insert_meta(conn, meta)
            self._insert_files(conn, graph.files)
            self._insert_nodes(conn, graph.nodes)
            self._insert_edges(conn, graph.edges)
            self._insert_unresolved(conn, graph.unresolved)
            conn.commit()

    # -- writers -----------------------------------------------------

    @staticmethod
    def _insert_meta(conn: sqlite3.Connection, meta: dict) -> None:
        conn.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?)",
            [(k, _dumps(v)) for k, v in meta.items()],
        )

    @staticmethod
    def _insert_files(
        conn: sqlite3.Connection, files: list[FileRecord]
    ) -> None:
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
            "INSERT OR IGNORE INTO nodes(id, kind, name, qualname, language, "
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
    def _insert_unresolved(
        conn: sqlite3.Connection, refs: list[UnresolvedRef]
    ) -> None:
        conn.executemany(
            "INSERT INTO unresolved(from_node, name, kind, file, line) "
            "VALUES(?,?,?,?,?)",
            [(r.from_node, r.name, str(r.kind), r.file, r.line) for r in refs],
        )

    # -- readers -----------------------------------------------------

    def read_meta(self) -> dict:
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value FROM meta").fetchall()
        out: dict = {}
        for row in rows:
            try:
                out[row["key"]] = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                out[row["key"]] = row["value"]
        return out

    def load_graph(self) -> CodeGraph:
        with self.connect() as conn:
            files = [
                _row_to_file(r)
                for r in conn.execute("SELECT * FROM files ORDER BY path")
            ]
            nodes = [
                _row_to_node(r)
                for r in conn.execute("SELECT * FROM nodes ORDER BY id")
            ]
            edges = [
                _row_to_edge(r)
                for r in conn.execute("SELECT * FROM edges ORDER BY id")
            ]
            unresolved = [
                _row_to_unresolved(r)
                for r in conn.execute("SELECT * FROM unresolved ORDER BY id")
            ]
        return CodeGraph(
            nodes=nodes, edges=edges, files=files, unresolved=unresolved
        )


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
