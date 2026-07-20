"""Collection federation and context contract tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from molmcp.collection import (
    MAX_CONTEXT_BUDGET,
    CollectionIndex,
    SourceBinding,
)
from molmcp.discovery.schema import Node


def _node(
    qualname: str,
    *,
    kind: str = "function",
    summary: str = "molecular operation",
    file: str = "api.py",
) -> Node:
    name = qualname.rsplit(".", 1)[-1]
    return Node(
        id=f"{file}#{qualname}#{kind}",
        kind=kind,
        name=name,
        qualname=qualname,
        language="python",
        file=file,
        start_line=1,
        end_line=3,
        signature=f"{name}(value: float)",
        summary=summary,
        docstring=summary,
        is_exported=True,
    )


class FakeStore:
    def __init__(self, nodes):
        self.nodes = {node.id: node for node in nodes}
        self.closed = False

    def get_node(self, node_id):
        return self.nodes.get(node_id)

    def close(self):
        self.closed = True


class FakeQuery:
    def __init__(
        self,
        snapshot: str,
        nodes,
        *,
        freshness: str = "fresh",
        root_dir: Path | None = None,
    ):
        self.nodes = list(nodes)
        self.snapshot = SimpleNamespace(snapshot_id=snapshot, root_dir=root_dir)
        self.freshness = freshness
        self.store = FakeStore(nodes)

    def search(self, query, kind=None, limit=30):
        words = query.casefold().split()
        matches = [
            node
            for node in self.nodes
            if (kind is None or node.kind == kind)
            and all(
                word
                in " ".join(
                    [node.qualname, node.summary or "", node.signature or ""]
                ).casefold()
                for word in words
            )
        ]
        return matches[:limit]

    def get_node(self, qualname):
        return next((node for node in self.nodes if node.qualname == qualname), None)

    def examples_of(self, qualname, limit=3):
        return []

    def tests_of(self, qualname, limit=5):
        return []

    def conventions_for(self, qualname, limit=3):
        return []

    def callers_pairs(self, qualname, limit=6):
        return []

    def callees_pairs(self, qualname, limit=6):
        return []


class FakeEngine:
    def __init__(self, query=None, error=None):
        self.result = query
        self.error = error
        self.calls = []

    def query(self, spec):
        self.calls.append(spec)
        if self.error is not None:
            raise self.error
        return self.result


class FakeRegistry:
    def __init__(self, items):
        self.items = {item["id"]: dict(item) for item in items}

    def search(self, query, kinds=None, namespaces=None, limit=20):
        words = query.casefold().split()
        results = []
        for item in self.items.values():
            namespace = item["id"].split("/", 1)[0][1:]
            text = " ".join(
                [item["id"], item["title"], item.get("summary", "")]
            ).casefold()
            if not all(word in text for word in words):
                continue
            if kinds is not None and item["kind"] not in kinds:
                continue
            if namespaces is not None and namespace not in namespaces:
                continue
            results.append(item)
        return results[:limit]

    def get(self, ref):
        return self.items[ref]

    def list_items(self):
        return [self.items[key] for key in sorted(self.items)]

    def info(self):
        return {"item_count": len(self.items)}


@dataclass
class Fixture:
    collection: CollectionIndex
    molpy_engine: FakeEngine
    molpack_engine: FakeEngine


@pytest.fixture
def fixture(tmp_path) -> Fixture:
    molpy_node = _node("molpy.analysis.rdf", summary="radial molecular analysis")
    molpack_node = _node("molpack.pack", summary="molecular packing workflow")
    (tmp_path / "api.py").write_text(
        "def pack(value: float):\n    return value\n",
        encoding="utf-8",
    )
    molpy_engine = FakeEngine(FakeQuery("git:sha:py", [molpy_node]))
    molpack_engine = FakeEngine(
        FakeQuery("git:sha:pack", [molpack_node], root_dir=tmp_path)
    )
    registry = FakeRegistry(
        [
            {
                "schema_version": "1",
                "id": "@molpack/pack",
                "kind": "executable",
                "title": "Pack molecules",
                "summary": "molecular packing workflow",
                "provenance": {"manifest_digest": "abc"},
            },
            {
                "schema_version": "1",
                "id": "@molpy/rdf-convention",
                "kind": "convention",
                "title": "RDF convention",
                "summary": "radial molecular analysis",
                "provenance": {"manifest_digest": "def"},
            },
        ]
    )
    collection = CollectionIndex(
        [
            SourceBinding(
                "molpack",
                "pkg:molpack",
                molpack_engine,
                namespace="molpack",
            ),
            SourceBinding("molpy", "pkg:molpy", molpy_engine, namespace="molpy"),
        ],
        registry,
    )
    return Fixture(collection, molpy_engine, molpack_engine)


def test_default_search_uses_every_source_and_registry(fixture):
    hits = fixture.collection.search("molecular", limit=20)

    assert {hit.ref for hit in hits} == {
        "@molpack/pack",
        "@molpy/rdf-convention",
        "molpack@git:sha:pack:api.py#molpack.pack#function",
        "molpy@git:sha:py:api.py#molpy.analysis.rdf#function",
    }
    assert fixture.molpy_engine.calls == ["pkg:molpy"]
    assert fixture.molpack_engine.calls == ["pkg:molpack"]
    assert fixture.molpy_engine.result.store.closed is True
    assert fixture.molpack_engine.result.store.closed is True


def test_explicit_source_namespace_and_kind_filters(fixture):
    hits = fixture.collection.search(
        "molecular",
        sources=["molpy"],
        namespaces=["molpy"],
        kinds=["function"],
    )

    assert [hit.source for hit in hits] == ["molpy"]
    assert fixture.molpack_engine.calls == []


def test_empty_explicit_sources_searches_registry_only(fixture):
    hits = fixture.collection.search("packing", sources=[])

    assert [hit.ref for hit in hits] == ["@molpack/pack"]
    assert fixture.molpy_engine.calls == []
    assert fixture.molpack_engine.calls == []


def test_unknown_explicit_source_fails_instead_of_silently_guessing(fixture):
    with pytest.raises(ValueError, match="unknown sources: typo"):
        fixture.collection.search("molecular", sources=["typo"])


def test_source_failure_isolated_and_reported_by_explore(fixture):
    broken = FakeEngine(error=RuntimeError("index unavailable"))
    collection = CollectionIndex(
        [
            *fixture.collection.sources,
            SourceBinding("broken", "pkg:broken", broken, namespace="broken"),
        ],
        fixture.collection.registry,
    )

    hits = collection.search("molecular")
    pack = collection.explore("molecular")

    assert hits
    assert pack.coverage["failed_sources"] == 1
    assert pack.coverage["successful_sources"] == 2
    assert any(item["ref"] == "broken" for item in pack.unresolved)


def test_rrf_order_is_deterministic_when_source_input_order_changes(fixture):
    reverse = CollectionIndex(
        list(reversed(fixture.collection.sources)), fixture.collection.registry
    )

    first = [hit.ref for hit in fixture.collection.search("molecular")]
    second = [hit.ref for hit in reverse.search("molecular")]

    assert first == second
    assert first == [
        "@molpack/pack",
        "molpack@git:sha:pack:api.py#molpack.pack#function",
        "molpy@git:sha:py:api.py#molpy.analysis.rdf#function",
        "@molpy/rdf-convention",
    ]
    assert all(hit.score_channel == "rrf" for hit in reverse.search("molecular"))


def test_symbol_ref_is_stable_and_describe_is_exact(fixture):
    hit = next(
        hit for hit in fixture.collection.search("packing") if hit.source == "molpack"
    )

    detail = fixture.collection.describe(hit.ref, include_source=True)

    assert hit.ref == "molpack@git:sha:pack:api.py#molpack.pack#function"
    assert detail is not None
    assert detail["qualname"] == "molpack.pack"
    assert detail["ref"] == hit.ref
    assert "def pack" in detail["source_code"]
    assert (
        fixture.collection.describe("molpack@git:sha:old:api.py#molpack.pack#function")
        is None
    )


def test_only_registry_executable_is_marked_executable(fixture):
    hits = fixture.collection.search("packing")
    registry_hit = next(hit for hit in hits if hit.ref == "@molpack/pack")
    symbol_hit = next(hit for hit in hits if hit.source == "molpack")

    assert registry_hit.executable is True
    assert registry_hit.executable_capability_id == "@molpack/pack"
    assert symbol_hit.executable is False
    assert symbol_hit.executable_capability_id is None
    assert fixture.collection.describe(symbol_hit.ref)["executable"] is False


def test_registry_search_only_status_blocks_molexp_handoff(fixture):
    class SearchOnlyRegistry(FakeRegistry):
        def execution_status(self, ref):
            return "search_only"

    registry = SearchOnlyRegistry(
        [
            {
                "id": "@molpack/pack",
                "kind": "executable",
                "title": "Pack molecules",
                "summary": "molecular packing workflow",
                "provenance": {"manifest_digest": "abc"},
            }
        ]
    )
    collection = CollectionIndex([], registry)
    hit = collection.search("packing")[0]
    assert hit.executable is False
    assert hit.execution_status == "search_only"
    assert hit.executable_capability_id is None


def test_explore_reports_freshness_coverage_and_bounded_truncation(fixture):
    long_node = _node("molpy.long", summary="molecular " + "x" * 4_000)
    fixture.molpy_engine.result.nodes.append(long_node)
    fixture.molpy_engine.result.store.nodes[long_node.id] = long_node

    pack = fixture.collection.explore("molecular", budget_chars=2_000)
    payload = pack.to_dict()

    assert pack.freshness["overall"] == "fresh"
    assert pack.coverage["selected_sources"] == 2
    assert pack.coverage["successful_sources"] == 2
    assert pack.truncated is True
    assert pack.omitted["hits"] + pack.omitted["details"] > 0
    assert pack.used_chars == len(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    assert pack.used_chars <= pack.budget_chars
    assert pack.provenance["type"] == "molcrafts_context_pack"
    assert any(
        action.get("capability_id") == "@molpack/pack"
        for action in pack.suggested_actions
    )


def test_explore_budget_hard_maximum(fixture):
    with pytest.raises(ValueError, match=str(MAX_CONTEXT_BUDGET)):
        fixture.collection.explore("molecular", budget_chars=MAX_CONTEXT_BUDGET + 1)


def test_info_uses_registry_duck_type(fixture):
    info = fixture.collection.info()

    assert info["registry"] == {"item_count": 2}
    assert info["coverage"] == {"source_count": 2, "available_sources": 2}
    assert info["provenance"]["type"] == "collection_inventory"


def test_collection_lifecycle_starts_watchers_and_closes_shared_engine():
    events: list[str] = []

    class Watcher:
        def stop(self):
            events.append("watcher.stop")

    class Engine(FakeEngine):
        config = SimpleNamespace(watch=True)

        def watch(self, spec):
            events.append(f"watch:{spec}")
            return Watcher()

        def close(self):
            events.append("engine.close")

    engine = Engine(FakeQuery("local:hash", []))
    collection = CollectionIndex(
        [
            SourceBinding("one", "/one", engine),
            SourceBinding("two", "/two", engine),
        ],
        FakeRegistry([]),
    )
    collection.start()
    collection.start()
    collection.close()
    collection.close()

    assert events == [
        "watch:/one",
        "watch:/two",
        "watcher.stop",
        "watcher.stop",
        "engine.close",
    ]
