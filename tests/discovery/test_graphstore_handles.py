"""Every sqlite handle GraphStore opens must be closed before it returns.

`create()` builds the database in a temp file and then `os.replace`s it into
place. POSIX happily renames a file that still has an open handle, so a leaked
connection is invisible there — on Windows the same call raises
``PermissionError``, which is why the discovery suite was excluded from the
Windows CI matrix rather than fixed.

The trap is that ``sqlite3.Connection.__exit__`` commits the transaction and
leaves the connection **open**; ``with sqlite3.connect(...) as conn`` is not
the close-on-exit idiom it reads as.
"""

from __future__ import annotations

import sqlite3

import pytest

from molmcp.discovery.schema import CodeGraph, Node, NodeKind
from molmcp.discovery.store import GraphStore


def _graph() -> CodeGraph:
    return CodeGraph(
        nodes=[
            Node(
                id="m.py#m.parse#function",
                kind=NodeKind.FUNCTION,
                name="parse",
                qualname="m.parse",
                language="python",
                file="m.py",
                start_line=1,
                end_line=4,
                summary="Parse something.",
            )
        ]
    )


@pytest.fixture
def tracked_connections(monkeypatch):
    """Every connection sqlite3 hands out, and whether it is still usable."""
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def spy(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", spy)
    return opened


def _still_open(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return False
    return True


class TestCreateLeavesNoOpenHandle:
    def test_create_closes_every_connection_it_opened(
        self, tmp_path, tracked_connections
    ):
        GraphStore(tmp_path / "graph.db").create(_graph(), meta={"schema_version": 1})

        leaked = [c for c in tracked_connections if _still_open(c)]
        assert leaked == [], (
            f"{len(leaked)} sqlite connection(s) still open after create(); "
            "os.replace() raises PermissionError on Windows while a handle "
            "is held. sqlite3.Connection.__exit__ commits but does not close."
        )

    def test_the_temp_build_file_is_gone(self, tmp_path):
        GraphStore(tmp_path / "graph.db").create(_graph(), meta={"schema_version": 1})

        strays = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert strays == []

    def test_the_published_graph_is_readable_afterwards(self, tmp_path):
        store = GraphStore(tmp_path / "graph.db")
        store.create(_graph(), meta={"schema_version": 1})

        assert store.exists()
        assert store.fts_available() is True
        store.close()

    def test_rebuilding_over_an_existing_graph_also_closes(
        self, tmp_path, tracked_connections
    ):
        store = GraphStore(tmp_path / "graph.db")
        store.create(_graph(), meta={"schema_version": 1})
        store.fts_available()  # opens the long-lived read connection
        store.create(_graph(), meta={"schema_version": 2})

        store.close()
        leaked = [c for c in tracked_connections if _still_open(c)]
        assert leaked == [], (
            "a re-index must release the previous read connection too — on "
            "Windows the replace would fail against the reader's own handle"
        )


class TestFsyncOpensForWriting:
    """`os.fsync` needs a writable handle on Windows.

    POSIX happily flushes a descriptor opened read-only, so `open("rb")`
    looked fine for years. On Windows the same call is
    ``OSError: [Errno 9] Bad file descriptor`` — 106 of them in one run, which
    is what kept the discovery suite off the Windows matrix.
    """

    def test_the_file_is_opened_writable(self, tmp_path, monkeypatch):
        from pathlib import Path as _Path

        from molmcp.discovery.store import graphstore

        target = tmp_path / "f.bin"
        target.write_bytes(b"x")
        modes: list[str] = []
        real_open = _Path.open

        def spy(self, mode="r", *args, **kwargs):
            modes.append(mode)
            return real_open(self, mode, *args, **kwargs)

        monkeypatch.setattr(_Path, "open", spy)
        graphstore._fsync_file(target)

        assert modes, "_fsync_file did not open the file at all"
        assert all("+" in m or "w" in m or "a" in m for m in modes), (
            f"opened {modes} — os.fsync raises Bad file descriptor on Windows "
            "unless the handle is writable"
        )

    def test_create_survives_the_fsync(self, tmp_path):
        store = GraphStore(tmp_path / "graph.db")
        store.create(_graph(), meta={"schema_version": 1})
        assert store.exists()
        store.close()


class TestEngineCloseReleasesItsQueries:
    """`engine.query()` hands out a store; closing the engine must free it.

    Each call builds a fresh `GraphStore` for `DiscoveryQuery` and nothing
    tracks it, so every query leaked a read connection until garbage
    collection. On Windows that is what stops pytest from removing `tmp_path`.
    """

    def _engine(self, tmp_path):
        from molmcp.discovery import DiscoveryConfig, DiscoveryEngine

        return DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))

    def test_close_releases_the_store_behind_a_query(self, tmp_path, monkeypatch):
        src = tmp_path / "pkg"
        src.mkdir()
        (src / "m.py").write_text("def parse():\n    return 1\n", encoding="utf-8")

        engine = self._engine(tmp_path)
        query = engine.query(str(src))
        query.search("parse")  # forces the read connection open
        assert _still_open(query.store._read_conn)

        engine.close()

        assert query.store._read_conn is None, (
            "engine.close() must release stores handed out by query(); "
            "an open read handle blocks tmp_path removal on Windows"
        )

    def test_close_is_idempotent(self, tmp_path):
        src = tmp_path / "pkg"
        src.mkdir()
        (src / "m.py").write_text("def parse():\n    return 1\n", encoding="utf-8")

        engine = self._engine(tmp_path)
        engine.query(str(src)).search("parse")
        engine.close()
        engine.close()  # must not raise on the already-closed store
