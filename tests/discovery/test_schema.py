"""Schema <-> SQLite round-trip tests."""

from __future__ import annotations

from molmcp.discovery.schema import (
    CodeGraph,
    Edge,
    EdgeKind,
    FileRecord,
    Node,
    NodeKind,
    UnresolvedRef,
)
from molmcp.discovery.store import GraphStore


def _sample_graph() -> CodeGraph:
    module = Node(
        id="f.py#m#module",
        kind=NodeKind.MODULE,
        name="m",
        qualname="m",
        language="python",
        file="f.py",
        start_line=1,
        end_line=20,
        docstring="Module doc.",
        summary="Module doc.",
        is_exported=True,
    )
    cls = Node(
        id="f.py#m.C#class",
        kind=NodeKind.CLASS,
        name="C",
        qualname="m.C",
        language="python",
        file="f.py",
        start_line=3,
        end_line=18,
        signature=None,
        decorators=["dataclass"],
        bases=["Base"],
        is_exported=True,
        is_abstract=True,
        metadata={"note": "demo"},
    )
    return CodeGraph(
        nodes=[module, cls],
        edges=[
            Edge(
                source=module.id,
                target=cls.id,
                kind=EdgeKind.CONTAINS,
                file="f.py",
            )
        ],
        files=[
            FileRecord(
                path="f.py",
                language="python",
                content_hash="abc123",
                size=512,
                node_count=2,
                errors=["a warning"],
            )
        ],
        unresolved=[
            UnresolvedRef(
                from_node=cls.id,
                name="Base",
                kind=EdgeKind.EXTENDS,
                file="f.py",
                line=3,
            )
        ],
    )


def test_graph_roundtrip(tmp_path):
    graph = _sample_graph()
    store = GraphStore(tmp_path / "graph.db")
    store.create(graph, meta={"snapshot_id": "x", "schema_version": 1})
    loaded = store.load_graph()

    assert {n.id for n in loaded.nodes} == {n.id for n in graph.nodes}
    cls = loaded.node_by_id("f.py#m.C#class")
    assert cls is not None
    assert cls.kind == "class"
    assert cls.bases == ["Base"]
    assert cls.decorators == ["dataclass"]
    assert cls.is_exported is True
    assert cls.is_abstract is True
    assert cls.metadata == {"note": "demo"}

    assert len(loaded.edges) == 1
    assert loaded.edges[0].kind == "contains"
    assert loaded.edges[0].source == "f.py#m#module"

    assert len(loaded.unresolved) == 1
    assert loaded.unresolved[0].name == "Base"
    assert loaded.unresolved[0].kind == "extends"

    assert len(loaded.files) == 1
    assert loaded.files[0].content_hash == "abc123"
    assert loaded.files[0].errors == ["a warning"]


def test_meta_roundtrip(tmp_path):
    store = GraphStore(tmp_path / "graph.db")
    store.create(
        CodeGraph(),
        meta={"snapshot_id": "snap-1", "schema_version": 1, "engine": "9.9"},
    )
    meta = store.read_meta()
    assert meta["snapshot_id"] == "snap-1"
    assert meta["schema_version"] == 1
    assert meta["engine"] == "9.9"


def test_create_replaces_existing_db(tmp_path):
    store = GraphStore(tmp_path / "graph.db")
    store.create(_sample_graph(), meta={"schema_version": 1})
    store.create(CodeGraph(), meta={"schema_version": 1})
    loaded = store.load_graph()
    assert loaded.nodes == []
    assert loaded.edges == []
