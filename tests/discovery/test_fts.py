"""FTS index tests — including its rebuildability and LIKE fallback."""

from __future__ import annotations

from molmcp.discovery.schema import CodeGraph, Node, NodeKind
from molmcp.discovery.store import GraphStore
from molmcp.discovery.store.graphstore import _build_fts


def _graph() -> CodeGraph:
    return CodeGraph(
        nodes=[
            Node(
                id="m.py#m.parse_lammps#function",
                kind=NodeKind.FUNCTION,
                name="parse_lammps",
                qualname="m.parse_lammps",
                language="python",
                file="m.py",
                start_line=1,
                end_line=4,
                summary="Parse a LAMMPS data file.",
            ),
            Node(
                id="m.py#m.Widget#class",
                kind=NodeKind.CLASS,
                name="Widget",
                qualname="m.Widget",
                language="python",
                file="m.py",
                start_line=6,
                end_line=10,
                summary="A widget.",
            ),
        ]
    )


def test_fts_is_enabled(tmp_path):
    store = GraphStore(tmp_path / "graph.db")
    store.create(_graph(), meta={"schema_version": 1})
    assert store.fts_available() is True


def test_fts_search_finds_symbol(tmp_path):
    store = GraphStore(tmp_path / "graph.db")
    store.create(_graph(), meta={"schema_version": 1})
    hits = store.search("lammps")
    assert "m.parse_lammps" in {n.qualname for n in hits}


def test_fts_index_rebuildable_from_nodes(tmp_path):
    """Dropping and rebuilding nodes_fts yields identical answers."""
    db = tmp_path / "graph.db"
    store = GraphStore(db)
    store.create(_graph(), meta={"schema_version": 1})
    before = [n.qualname for n in store.search("widget")]
    store.close()

    with store.connect() as conn:
        conn.execute("DROP TABLE nodes_fts")
        assert _build_fts(conn) is True
        conn.commit()

    after = [n.qualname for n in GraphStore(db).search("widget")]
    assert before == after
    assert "m.Widget" in after


def test_like_fallback_when_fts_unavailable(tmp_path):
    db = tmp_path / "graph.db"
    store = GraphStore(db)
    store.create(_graph(), meta={"schema_version": 1})
    store.close()

    # Simulate an FTS5-less SQLite build.
    with store.connect() as conn:
        conn.execute("UPDATE meta SET value = 'false' WHERE key = 'fts_available'")
        conn.commit()

    fallback = GraphStore(db)
    assert fallback.fts_available() is False
    hits = fallback.search("lammps")
    assert "m.parse_lammps" in {n.qualname for n in hits}
