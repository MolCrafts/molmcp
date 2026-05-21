"""DiscoveryEngine — the MCP-free facade over the discovery pipeline.

Resolves a source spec, extracts and resolves its graph, persists it to
a snapshot-keyed cache, and answers queries. Re-indexing is incremental:
an :class:`ExtractCache` lets unchanged files skip the analyzer.
"""

from __future__ import annotations

import importlib.metadata
import time
from dataclasses import dataclass, field

from .cache import ExtractCache, FreshnessTracker, SnapshotCache
from .cache.freshness import ChangeSet
from .config import DiscoveryConfig
from .extract import Extractor
from .query import DiscoveryQuery
from .resolve import Resolver
from .schema import ANALYZER_VERSION, SCHEMA_VERSION, CodeGraph, FileRecord
from .source import Snapshot, SourceResolver
from .store import GraphStore

try:
    ENGINE_VERSION = importlib.metadata.version("molcrafts-molmcp")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover
    ENGINE_VERSION = "0+unknown"


@dataclass(slots=True)
class IndexResult:
    """Outcome of an :meth:`DiscoveryEngine.index` / ``refresh`` call."""

    snapshot: Snapshot
    graph: CodeGraph
    cached: bool
    extract_stats: dict = field(default_factory=dict)
    changes: ChangeSet | None = None

    @property
    def node_count(self) -> int:
        return len(self.graph.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.graph.edges)

    @property
    def file_count(self) -> int:
        return len(self.graph.files)


class DiscoveryEngine:
    """Indexes source specs into snapshot-cached code graphs."""

    def __init__(self, config: DiscoveryConfig | None = None) -> None:
        self.config = config or DiscoveryConfig()
        self.resolver = SourceResolver(self.config)
        self.cache = SnapshotCache(self.config)
        self.extract_cache = ExtractCache(
            self.cache.extract_db_path(), ANALYZER_VERSION
        )
        self.extractor = Extractor(self.extract_cache)

    def resolve(self, spec: str) -> Snapshot:
        """Resolve a spec to an immutable snapshot (no indexing)."""
        return self.resolver.resolve(spec)

    def index(self, spec: str, *, force: bool = False) -> IndexResult:
        """Index ``spec``, reusing a cached snapshot when possible."""
        snapshot = self.resolver.resolve(spec)
        if not force and self._cache_is_valid(snapshot.snapshot_id):
            graph = self.load_graph(snapshot.snapshot_id)
            return IndexResult(snapshot=snapshot, graph=graph, cached=True)
        graph = self._build(snapshot)
        self._persist(snapshot, graph)
        return IndexResult(
            snapshot=snapshot,
            graph=graph,
            cached=False,
            extract_stats=dict(self.extractor.stats),
        )

    def refresh(self, spec: str) -> IndexResult:
        """Force a re-index and report what changed since the last one."""
        previous_files = self._previous_files(spec)
        snapshot = self.resolver.resolve(spec)
        changes = (
            FreshnessTracker.changes(previous_files, list(snapshot.files))
            if previous_files is not None
            else None
        )
        graph = self._build(snapshot)
        self._persist(snapshot, graph)
        return IndexResult(
            snapshot=snapshot,
            graph=graph,
            cached=False,
            extract_stats=dict(self.extractor.stats),
            changes=changes,
        )

    def get_graph(self, spec: str) -> CodeGraph:
        """Index ``spec`` if needed and return its graph."""
        return self.index(spec).graph

    def query(self, spec: str, *, force: bool = False) -> DiscoveryQuery:
        """Index ``spec`` if needed and return a query handle over it."""
        result = self.index(spec, force=force)
        store = GraphStore(self.cache.graph_db_path(result.snapshot.snapshot_id))
        return DiscoveryQuery(store, snapshot=result.snapshot)

    def load_graph(self, snapshot_id: str) -> CodeGraph:
        """Load a previously indexed snapshot's graph from cache."""
        store = GraphStore(self.cache.graph_db_path(snapshot_id))
        if not store.exists():
            raise FileNotFoundError(
                f"no cached graph for snapshot {snapshot_id!r}"
            )
        try:
            return store.load_graph()
        finally:
            store.close()

    def close(self) -> None:
        self.extract_cache.close()

    # -- internals ---------------------------------------------------

    def _build(self, snapshot: Snapshot) -> CodeGraph:
        graph = self.extractor.extract(snapshot)
        return Resolver().resolve(graph)

    def _cache_is_valid(self, snapshot_id: str) -> bool:
        if not self.cache.has(snapshot_id):
            return False
        manifest = self.cache.read_manifest(snapshot_id) or {}
        return manifest.get("schema_version") == SCHEMA_VERSION

    def _previous_files(self, spec: str) -> list[FileRecord] | None:
        ref = self.cache.read_ref(spec)
        if not ref:
            return None
        snapshot_id = ref.get("snapshot_id")
        if not snapshot_id:
            return None
        db_path = self.cache.graph_db_path(snapshot_id)
        if not db_path.is_file():
            return None
        store = GraphStore(db_path)
        try:
            return store.files()
        finally:
            store.close()

    def _persist(self, snapshot: Snapshot, graph: CodeGraph) -> None:
        indexed_at = time.time()
        store = GraphStore(self.cache.graph_db_path(snapshot.snapshot_id))
        store.create(
            graph,
            meta={
                "snapshot_id": snapshot.snapshot_id,
                "schema_version": SCHEMA_VERSION,
                "engine_version": ENGINE_VERSION,
                "indexed_at": indexed_at,
            },
        )
        manifest = {
            "snapshot_id": snapshot.snapshot_id,
            "origin": snapshot.origin,
            "spec": snapshot.spec,
            "ref": snapshot.ref,
            "commit": snapshot.commit,
            "indexed_at": indexed_at,
            "schema_version": SCHEMA_VERSION,
            "engine_version": ENGINE_VERSION,
            "file_count": len(graph.files),
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "unresolved_count": len(graph.unresolved),
        }
        self.cache.write_manifest(snapshot.snapshot_id, manifest)
        self.cache.write_ref(
            snapshot.spec,
            {
                "spec": snapshot.spec,
                "snapshot_id": snapshot.snapshot_id,
                "indexed_at": indexed_at,
            },
        )
        self.cache.evict()
