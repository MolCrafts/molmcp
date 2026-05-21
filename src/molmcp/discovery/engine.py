"""DiscoveryEngine — the MCP-free facade over the discovery pipeline.

Stage 1 surface: resolve a source spec, extract its graph, persist it to
a snapshot-keyed cache, and load it back. Resolution, querying, and
freshness arrive in later stages.
"""

from __future__ import annotations

import importlib.metadata
import time
from dataclasses import dataclass

from .cache import SnapshotCache
from .config import DiscoveryConfig
from .extract import Extractor
from .query import DiscoveryQuery
from .resolve import Resolver
from .schema import SCHEMA_VERSION, CodeGraph
from .source import Snapshot, SourceResolver
from .store import GraphStore

try:
    ENGINE_VERSION = importlib.metadata.version("molcrafts-molmcp")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover
    ENGINE_VERSION = "0+unknown"


@dataclass(slots=True)
class IndexResult:
    """Outcome of an :meth:`DiscoveryEngine.index` call."""

    snapshot: Snapshot
    graph: CodeGraph
    cached: bool

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
        self.extractor = Extractor()
        self.cache = SnapshotCache(self.config)

    def resolve(self, spec: str) -> Snapshot:
        """Resolve a spec to an immutable snapshot (no indexing)."""
        return self.resolver.resolve(spec)

    def index(self, spec: str, *, force: bool = False) -> IndexResult:
        """Index ``spec``, reusing a cached snapshot when possible."""
        snapshot = self.resolver.resolve(spec)
        if not force and self._cache_is_valid(snapshot.snapshot_id):
            graph = self.load_graph(snapshot.snapshot_id)
            return IndexResult(snapshot=snapshot, graph=graph, cached=True)
        graph = self.extractor.extract(snapshot)
        graph = Resolver().resolve(graph)
        self._persist(snapshot, graph)
        return IndexResult(snapshot=snapshot, graph=graph, cached=False)

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
        return store.load_graph()

    # -- internals ---------------------------------------------------

    def _cache_is_valid(self, snapshot_id: str) -> bool:
        if not self.cache.has(snapshot_id):
            return False
        manifest = self.cache.read_manifest(snapshot_id) or {}
        return manifest.get("schema_version") == SCHEMA_VERSION

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
