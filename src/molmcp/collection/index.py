"""Federated registry and source-graph retrieval.

``CollectionIndex`` keeps source databases isolated and combines only ranked
results.  Registry records and source symbols remain distinct evidence types:
in particular, source nodes are never inferred to be executable.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path
from typing import Any

from .models import ContextPack, SearchHit, SourceBinding

DEFAULT_CONTEXT_BUDGET = 16_000
MAX_CONTEXT_BUDGET = 32_000
_RRF_K = 60
_SEARCH_OVERSAMPLE = 3
_CONTEXT_LIMIT = 12
_RELIABLE_RELATION_PROVENANCE = frozenset({"resolved", "scip"})


@dataclass(slots=True)
class _RankedCandidate:
    hit: SearchHit
    score: float
    best_rank: int
    best_channel_order: int
    channels: set[str]


@dataclass(slots=True)
class _SearchReport:
    hits: list[SearchHit]
    queries: dict[str, Any]
    source_states: dict[str, dict[str, Any]]
    unresolved: list[dict[str, Any]]
    registry_status: str


class CollectionIndex:
    """Search a registry and any number of isolated discovery sources.

    The registry is intentionally duck typed.  It may expose ``search``,
    ``get``, ``list_items``, and ``info`` without inheriting any MolMCP class.
    """

    def __init__(
        self,
        sources: Iterable[SourceBinding] | Mapping[str, SourceBinding] = (),
        registry: Any | None = None,
        *,
        rrf_k: int = _RRF_K,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        bindings = list(sources.values() if isinstance(sources, Mapping) else sources)
        by_name: dict[str, SourceBinding] = {}
        for binding in bindings:
            if not isinstance(binding, SourceBinding):
                raise TypeError("sources must contain SourceBinding objects")
            if binding.name in by_name:
                raise ValueError(f"duplicate source name: {binding.name!r}")
            by_name[binding.name] = binding
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        self._sources = dict(sorted(by_name.items()))
        self.registry = registry
        self.rrf_k = rrf_k
        self.metadata = _jsonable(dict(metadata or {}))
        self._watchers: list[Any] = []
        self._lifecycle_errors: list[dict[str, str]] = []
        self._started = False
        self._closed = False

    @property
    def sources(self) -> tuple[SourceBinding, ...]:
        """Bindings in deterministic source-name order."""

        return tuple(self._sources.values())

    def start(self) -> None:
        """Start configured source watchers once for server-lifecycle use."""

        if self._started:
            return
        if self._closed:
            raise RuntimeError("collection is closed")
        self._started = True
        for binding in self.sources:
            config = getattr(binding.engine, "config", None)
            if not bool(getattr(config, "watch", False)):
                continue
            watch = getattr(binding.engine, "watch", None)
            if not callable(watch) or binding.spec.startswith("github:"):
                continue
            try:
                self._watchers.append(watch(binding.spec))
            except Exception as exc:  # noqa: BLE001 - isolate source startup
                self._lifecycle_errors.append(
                    {
                        "source": binding.name,
                        "phase": "watch_start",
                        "error": _error_text(exc),
                    }
                )

    def close(self) -> None:
        """Stop watchers and close each distinct source engine exactly once."""

        if self._closed:
            return
        self._closed = True
        for watcher in reversed(self._watchers):
            stop = getattr(watcher, "stop", None)
            if callable(stop):
                stop()
        self._watchers.clear()
        engines: dict[int, Any] = {
            id(binding.engine): binding.engine for binding in self.sources
        }
        for engine in engines.values():
            close = getattr(engine, "close", None)
            if callable(close):
                close()

    def search(
        self,
        query: str,
        *,
        kinds: Sequence[str] | None = None,
        namespaces: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
        limit: int = 20,
    ) -> list[SearchHit]:
        """Search the full collection unless explicit filters are supplied.

        A failing source contributes no candidates but cannot prevent healthy
        sources or the registry from returning results.
        """

        report = self._search_report(
            query,
            kinds=kinds,
            namespaces=namespaces,
            sources=sources,
            limit=limit,
        )
        self._close_queries(report.queries.values())
        return report.hits

    def describe(
        self,
        ref: str,
        *,
        include_source: bool = False,
        include_examples: bool = True,
    ) -> dict[str, Any] | None:
        """Describe an exact registry ID or stable symbol reference."""

        if ref.startswith("@"):
            try:
                return self._describe_registry(ref)
            except ValueError:
                return None
        try:
            binding, tail = self._parse_symbol_ref(ref)
        except ValueError:
            return None
        query = binding.open_query()
        try:
            current_snapshot = self._snapshot_id(binding, query)
            prefix = f"{current_snapshot}:"
            if not tail.startswith(prefix):
                return None
            node_id = tail[len(prefix) :]
            node = self._node_for_id(query, node_id)
            if node is None:
                return None
            return self._symbol_detail(
                binding,
                query,
                node,
                ref,
                include_source=include_source,
                include_examples=include_examples,
            )
        finally:
            self._close_query(query)

    def explore(
        self,
        task: str,
        *,
        namespaces: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
        budget_chars: int = DEFAULT_CONTEXT_BUDGET,
    ) -> ContextPack:
        """Build a deterministic, bounded evidence package for ``task``."""

        if not task.strip():
            raise ValueError("task must not be empty")
        if not 1 <= budget_chars <= MAX_CONTEXT_BUDGET:
            raise ValueError(f"budget_chars must be between 1 and {MAX_CONTEXT_BUDGET}")

        report = self._search_report(
            task,
            namespaces=namespaces,
            sources=sources,
            limit=_CONTEXT_LIMIT,
        )
        try:
            details: list[dict[str, Any]] = []
            for hit in report.hits:
                detail = self._detail_for_hit(hit, report.queries)
                if detail is None:
                    report.unresolved.append(
                        {
                            "kind": "evidence",
                            "ref": hit.ref,
                            "reason": "the ranked result could not be described",
                        }
                    )
                    continue
                if "error" in detail:
                    report.unresolved.append(
                        {
                            "kind": "evidence",
                            "ref": hit.ref,
                            "reason": str(detail["error"]),
                        }
                    )
                details.append(detail)
            selected_names = self._selected_source_names(sources)
            freshness = self._freshness(report.source_states)
            coverage = {
                "selected_sources": len(selected_names),
                "successful_sources": sum(
                    state["status"] == "ok" for state in report.source_states.values()
                ),
                "failed_sources": sum(
                    state["status"] == "error"
                    for state in report.source_states.values()
                ),
                "registry": report.registry_status,
                "sources": report.source_states,
            }
            if not report.hits:
                report.unresolved.append(
                    {
                        "kind": "task",
                        "ref": task,
                        "reason": "no registry items or source symbols matched",
                    }
                )

            return self._fit_context(
                task=task,
                filters={
                    "namespaces": list(namespaces) if namespaces is not None else None,
                    "sources": list(sources) if sources is not None else None,
                },
                hits=report.hits,
                details=details,
                freshness=freshness,
                coverage=coverage,
                unresolved=report.unresolved,
                budget_chars=budget_chars,
            )
        finally:
            self._close_queries(report.queries.values())

    def info(self) -> dict[str, Any]:
        """Return collection inventory, freshness, and source availability."""

        states: dict[str, dict[str, Any]] = {}
        for binding in self.sources:
            try:
                query = binding.open_query()
                try:
                    states[binding.name] = self._source_state(binding, query)
                finally:
                    self._close_query(query)
            except Exception as exc:  # noqa: BLE001 - source isolation boundary
                states[binding.name] = {
                    "status": "error",
                    "spec": binding.spec,
                    "namespace": binding.namespace,
                    "snapshot": None,
                    "freshness": "unknown",
                    "error": _error_text(exc),
                }
        registry_info: Any = None
        if self.registry is not None:
            method = getattr(self.registry, "info", None)
            if callable(method):
                try:
                    registry_info = _jsonable(method())
                except Exception as exc:  # noqa: BLE001 - registry isolation boundary
                    registry_info = {"status": "error", "error": _error_text(exc)}
            else:
                registry_info = {"status": "available"}
        return {
            "workspace": self.metadata.get("workspace_root"),
            "sources": states,
            "registry": registry_info,
            "freshness": self._freshness(states),
            "coverage": {
                "source_count": len(states),
                "available_sources": sum(
                    state["status"] == "ok" for state in states.values()
                ),
            },
            "configuration": self.metadata,
            "warnings": list(self._lifecycle_errors),
            "provenance": {
                "type": "collection_inventory",
                "source_count": len(states),
            },
        }

    @staticmethod
    def _close_query(query: Any) -> None:
        close = getattr(query, "close", None)
        if callable(close):
            close()
            return
        store = getattr(query, "store", None)
        store_close = getattr(store, "close", None)
        if callable(store_close):
            store_close()

    @classmethod
    def _close_queries(cls, queries: Iterable[Any]) -> None:
        for query in queries:
            cls._close_query(query)

    # -- federated search -------------------------------------------

    def _search_report(
        self,
        query: str,
        *,
        kinds: Sequence[str] | None = None,
        namespaces: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
        limit: int = 20,
    ) -> _SearchReport:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be positive")
        kind_filter = _normalize_filter(kinds)
        namespace_filter = _normalize_filter(namespaces)
        selected_names = self._selected_source_names(sources)
        pool_limit = max(limit * _SEARCH_OVERSAMPLE, limit)

        channels: list[tuple[str, list[SearchHit]]] = []
        unresolved: list[dict[str, Any]] = []
        registry_status = "not_configured" if self.registry is None else "unavailable"
        if self.registry is not None:
            try:
                registry_hits = self._registry_search(
                    query,
                    kinds=kind_filter,
                    namespaces=namespace_filter,
                    limit=pool_limit,
                )
                channels.append(("registry", registry_hits))
                registry_status = "available"
            except Exception as exc:  # noqa: BLE001 - registry isolation boundary
                unresolved.append(
                    {
                        "kind": "registry",
                        "ref": "registry",
                        "reason": _error_text(exc),
                    }
                )

        queries: dict[str, Any] = {}
        states: dict[str, dict[str, Any]] = {}
        for name in selected_names:
            binding = self._sources[name]
            if (
                namespace_filter is not None
                and binding.namespace not in namespace_filter
            ):
                states[name] = {
                    "status": "filtered",
                    "spec": binding.spec,
                    "namespace": binding.namespace,
                    "snapshot": None,
                    "freshness": "unknown",
                }
                continue
            try:
                source_query = binding.open_query()
                snapshot = self._snapshot_id(binding, source_query)
                queries[name] = source_query
                states[name] = self._source_state(binding, source_query)
                nodes = self._query_search(
                    source_query,
                    query,
                    kinds=kind_filter,
                    limit=pool_limit,
                )
                hits = [
                    self._symbol_hit(binding, source_query, snapshot, node)
                    for node in nodes
                ]
                channels.append((f"source:{name}", hits))
            except Exception as exc:  # noqa: BLE001 - source isolation boundary
                states[name] = {
                    "status": "error",
                    "spec": binding.spec,
                    "namespace": binding.namespace,
                    "snapshot": None,
                    "freshness": "unknown",
                    "error": _error_text(exc),
                }
                unresolved.append(
                    {
                        "kind": "source",
                        "ref": name,
                        "reason": _error_text(exc),
                    }
                )

        return _SearchReport(
            hits=self._rrf(channels, limit),
            queries=queries,
            source_states=states,
            unresolved=unresolved,
            registry_status=registry_status,
        )

    def _rrf(
        self, channels: list[tuple[str, list[SearchHit]]], limit: int
    ) -> list[SearchHit]:
        fused: dict[str, _RankedCandidate] = {}
        for channel_order, (channel, hits) in enumerate(channels):
            seen: set[str] = set()
            for rank, hit in enumerate(hits, 1):
                if hit.ref in seen:
                    continue
                seen.add(hit.ref)
                contribution = 1.0 / (self.rrf_k + rank)
                current = fused.get(hit.ref)
                if current is None:
                    fused[hit.ref] = _RankedCandidate(
                        hit=hit,
                        score=contribution,
                        best_rank=rank,
                        best_channel_order=channel_order,
                        channels={channel},
                    )
                    continue
                current.score += contribution
                current.best_rank = min(current.best_rank, rank)
                current.best_channel_order = min(
                    current.best_channel_order, channel_order
                )
                current.channels.add(channel)
        ranked = sorted(
            fused.values(),
            key=lambda candidate: (
                -candidate.score,
                candidate.best_rank,
                candidate.best_channel_order,
                candidate.hit.ref,
            ),
        )
        return [
            replace(
                candidate.hit,
                score=round(candidate.score, 12),
                score_channel="rrf",
                matched_channels=tuple(sorted(candidate.channels)),
            )
            for candidate in ranked[:limit]
        ]

    # -- adapters ---------------------------------------------------

    def _registry_search(
        self,
        query: str,
        *,
        kinds: set[str] | None,
        namespaces: set[str] | None,
        limit: int,
    ) -> list[SearchHit]:
        method = getattr(self.registry, "search", None)
        if not callable(method):
            raise TypeError("registry must expose search(query, ...)")
        results = _call_supported(
            method,
            query,
            kinds=sorted(kinds) if kinds is not None else None,
            namespaces=sorted(namespaces) if namespaces is not None else None,
            limit=limit,
        )
        hits: list[SearchHit] = []
        for result in results or ():
            item, channel = _unwrap_registry_result(result)
            data = _object_mapping(item)
            item_id = str(data.get("id") or getattr(item, "id", ""))
            if not item_id.startswith("@"):
                continue
            kind = str(data.get("kind") or getattr(item, "kind", ""))
            namespace = _registry_namespace(item_id)
            if kinds is not None and kind not in kinds:
                continue
            if namespaces is not None and namespace not in namespaces:
                continue
            execution_status = self._registry_execution_status(item_id, kind)
            executable = execution_status == "ready"
            provenance = _jsonable(data.get("provenance", {}))
            if not isinstance(provenance, dict):
                provenance = {"value": provenance}
            hits.append(
                SearchHit(
                    ref=item_id,
                    kind=kind,
                    namespace=namespace,
                    title=str(data.get("title") or item_id),
                    summary=_optional_text(data.get("summary")),
                    executable=executable,
                    executable_capability_id=item_id if executable else None,
                    execution_status=execution_status,
                    score_channel=channel,
                    provenance=provenance,
                    freshness=str(data.get("freshness") or "unknown"),
                )
            )
        return hits

    def _query_search(
        self,
        query_handle: Any,
        text: str,
        *,
        kinds: set[str] | None,
        limit: int,
    ) -> list[Any]:
        method = getattr(query_handle, "search", None)
        if not callable(method):
            raise TypeError("source query must expose search(query, ...)")
        single_kind = (
            next(iter(kinds)) if kinds is not None and len(kinds) == 1 else None
        )
        nodes = _call_supported(method, text, kind=single_kind, limit=limit)
        filtered = [
            node
            for node in nodes or ()
            if kinds is None or str(getattr(node, "kind", "")) in kinds
        ]
        return filtered[:limit]

    def _symbol_hit(
        self,
        binding: SourceBinding,
        query: Any,
        snapshot: str,
        node: Any,
    ) -> SearchHit:
        node_id = str(getattr(node, "id"))
        ref = _symbol_ref(binding.name, snapshot, node_id)
        file = str(getattr(node, "file", ""))
        start_line = int(getattr(node, "start_line", 0))
        end_line = int(getattr(node, "end_line", start_line))
        return SearchHit(
            ref=ref,
            kind=str(getattr(node, "kind", "symbol")),
            namespace=binding.namespace,
            source=binding.name,
            snapshot=snapshot,
            title=str(
                getattr(node, "qualname", None)
                or getattr(node, "name", None)
                or node_id
            ),
            summary=_optional_text(getattr(node, "summary", None)),
            signature=_optional_text(getattr(node, "signature", None)),
            executable=False,
            executable_capability_id=None,
            provenance={
                "type": "code_graph",
                "node_id": node_id,
                "language": str(getattr(node, "language", "unknown")),
            },
            freshness=str(getattr(query, "freshness", "unknown")),
            span={
                "file": file,
                "start_line": start_line,
                "end_line": end_line,
            },
        )

    # -- describe/context ------------------------------------------

    def _describe_registry(self, ref: str) -> dict[str, Any] | None:
        if self.registry is None:
            return None
        method = getattr(self.registry, "get", None)
        if not callable(method):
            raise TypeError("registry must expose get(ref)")
        try:
            item = method(ref)
        except (KeyError, LookupError):
            return None
        if item is None:
            return None
        data = _object_mapping(item)
        kind = str(data.get("kind", ""))
        execution_status = self._registry_execution_status(ref, kind)
        executable = execution_status == "ready"
        data.update(
            {
                "ref": ref,
                "executable": executable,
                "executable_capability_id": ref if executable else None,
                "execution_status": execution_status,
                "freshness": str(data.get("freshness") or "unknown"),
            }
        )
        record_info = getattr(self.registry, "record_info", None)
        if callable(record_info):
            data["observed_origin"] = _jsonable(record_info(ref))
        return _jsonable(data)

    def _registry_execution_status(self, ref: str, kind: str) -> str:
        if kind != "executable":
            return "not_executable"
        method = getattr(self.registry, "execution_status", None)
        if callable(method):
            return str(method(ref))
        # Duck-typed registries predate the trust-status extension; treating
        # their explicit executable records as ready preserves adapter utility.
        return "ready"

    def _detail_for_hit(
        self, hit: SearchHit, queries: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        if hit.ref.startswith("@"):
            try:
                return self._describe_registry(hit.ref)
            except Exception as exc:  # noqa: BLE001 - evidence is best effort
                return {"ref": hit.ref, "error": _error_text(exc)}
        if hit.source is None or hit.source not in queries:
            return None
        query = queries[hit.source]
        node_id = str(hit.provenance.get("node_id", ""))
        node = self._node_for_id(query, node_id)
        if node is None:
            return None
        return self._symbol_detail(
            self._sources[hit.source],
            query,
            node,
            hit.ref,
            include_source=True,
            include_examples=True,
        )

    def _symbol_detail(
        self,
        binding: SourceBinding,
        query: Any,
        node: Any,
        ref: str,
        *,
        include_source: bool,
        include_examples: bool,
    ) -> dict[str, Any]:
        detail = _node_mapping(node)
        detail.update(
            {
                "ref": ref,
                "source": binding.name,
                "source_name": binding.name,
                "snapshot": self._snapshot_id(binding, query),
                "freshness": str(getattr(query, "freshness", "unknown")),
                "executable": False,
                "executable_capability_id": None,
                "provenance": {
                    "type": "code_graph",
                    "node_id": str(getattr(node, "id", "")),
                    "language": str(getattr(node, "language", "unknown")),
                },
            }
        )
        qualname = str(getattr(node, "qualname", ""))
        if include_examples:
            detail["examples"] = self._related_nodes(query, "examples_of", qualname, 3)
        detail["tests"] = self._related_nodes(query, "tests_of", qualname, 5)
        detail["conventions"] = self._related_nodes(
            query, "conventions_for", qualname, 3
        )
        detail["relationships"] = {
            "callers": self._reliable_pairs(query, "callers_pairs", qualname, 6),
            "callees": self._reliable_pairs(query, "callees_pairs", qualname, 6),
        }
        if include_source:
            detail["source_code"] = self._read_source(query, node)
        return _jsonable(detail)

    def _related_nodes(
        self, query: Any, method_name: str, qualname: str, limit: int
    ) -> list[dict[str, Any]]:
        method = getattr(query, method_name, None)
        if not callable(method):
            return []
        try:
            nodes = _call_supported(method, qualname, limit=limit)
        except Exception:  # noqa: BLE001 - optional evidence channel
            return []
        return [_node_mapping(node) for node in (nodes or ())]

    def _reliable_pairs(
        self, query: Any, method_name: str, qualname: str, limit: int
    ) -> list[dict[str, Any]]:
        method = getattr(query, method_name, None)
        if not callable(method):
            return []
        try:
            pairs = _call_supported(method, qualname, limit=limit)
        except Exception:  # noqa: BLE001 - optional evidence channel
            return []
        results = []
        for node, edge in pairs or ():
            provenance = str(getattr(edge, "provenance", ""))
            if provenance not in _RELIABLE_RELATION_PROVENANCE:
                continue
            results.append(
                {
                    "node": _node_mapping(node),
                    "edge": {
                        "kind": str(getattr(edge, "kind", "")),
                        "provenance": provenance,
                        "file": getattr(edge, "file", None),
                        "line": getattr(edge, "line", None),
                    },
                }
            )
        return results

    def _read_source(self, query: Any, node: Any) -> str:
        snapshot = getattr(query, "snapshot", None)
        root = getattr(snapshot, "root_dir", None)
        if root is None:
            return "<source unavailable>"
        path = Path(root) / str(getattr(node, "file", ""))
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return f"<source unavailable: {exc}>"
        start = max(int(getattr(node, "start_line", 1)) - 1, 0)
        end = max(int(getattr(node, "end_line", start + 1)), start + 1)
        return "\n".join(lines[start:end])

    def _node_for_id(self, query: Any, node_id: str) -> Any | None:
        store = getattr(query, "store", None)
        getter = getattr(store, "get_node", None)
        if callable(getter):
            return getter(node_id)
        try:
            _, qualname, _ = node_id.rsplit("#", 2)
        except ValueError:
            return None
        getter = getattr(query, "get_node", None)
        if not callable(getter):
            return None
        node = getter(qualname)
        if node is not None and str(getattr(node, "id", "")) == node_id:
            return node
        return None

    # -- identity, diagnostics, budgeting ---------------------------

    def _selected_source_names(self, sources: Sequence[str] | None) -> list[str]:
        if sources is None:
            return list(self._sources)
        from molmcp.guide import resolve_source_alias

        selected: list[str] = []
        unknown: list[str] = []
        for raw in sources:
            name = str(raw)
            if name in self._sources:
                selected.append(name)
                continue
            resolved = resolve_source_alias(name, self._sources)
            if resolved is not None:
                selected.append(resolved)
            else:
                unknown.append(name)
        selected = list(dict.fromkeys(selected))
        if unknown:
            raise ValueError(f"unknown sources: {', '.join(sorted(set(unknown)))}")
        return sorted(selected)

    def _snapshot_id(self, binding: SourceBinding, query: Any) -> str:
        snapshot = getattr(query, "snapshot", None)
        value = getattr(snapshot, "snapshot_id", None) or binding.snapshot
        if not value:
            raise ValueError(
                f"source {binding.name!r} did not provide a snapshot identity"
            )
        return str(value)

    def _source_state(self, binding: SourceBinding, query: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "spec": binding.spec,
            "namespace": binding.namespace,
            "snapshot": self._snapshot_id(binding, query),
            "freshness": str(getattr(query, "freshness", "unknown")),
        }

    def _parse_symbol_ref(self, ref: str) -> tuple[SourceBinding, str]:
        source_name, separator, tail = ref.partition("@")
        if (
            not separator
            or source_name not in self._sources
            or not tail
            or tail.count("#") < 2
        ):
            raise ValueError(f"invalid or unknown symbol ref: {ref!r}")
        return self._sources[source_name], tail

    def _freshness(self, states: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        per_source = {
            name: str(state.get("freshness", "unknown"))
            for name, state in states.items()
        }
        values = set(per_source.values())
        if "stale" in values:
            overall = "stale"
        elif "pending" in values:
            overall = "pending"
        elif not values or "unknown" in values:
            overall = "unknown"
        else:
            overall = "fresh"
        return {"overall": overall, "sources": per_source}

    def _fit_context(
        self,
        *,
        task: str,
        filters: dict[str, Any],
        hits: list[SearchHit],
        details: list[dict[str, Any]],
        freshness: dict[str, Any],
        coverage: dict[str, Any],
        unresolved: list[dict[str, Any]],
        budget_chars: int,
    ) -> ContextPack:
        kept_hits: list[SearchHit] = []
        kept_details: list[dict[str, Any]] = []
        omitted = {"hits": 0, "details": 0}

        def build(*, truncated: bool, used_chars: int = 0) -> ContextPack:
            warnings = _context_warnings(freshness, coverage)
            return ContextPack(
                task=task,
                filters=filters,
                hits=tuple(kept_hits),
                details=tuple(kept_details),
                freshness=freshness,
                coverage=coverage,
                truncated=truncated,
                unresolved=tuple(unresolved),
                omitted=dict(omitted),
                warnings=warnings,
                suggested_actions=_suggested_actions(kept_hits),
                provenance={
                    "type": "molcrafts_context_pack",
                    "retrieval": "reciprocal_rank_fusion",
                },
                budget_chars=budget_chars,
                used_chars=used_chars,
            )

        # Compact anchors have priority over expanded details.
        for index, hit in enumerate(hits):
            kept_hits.append(hit)
            if (
                _json_size(build(truncated=False, used_chars=budget_chars))
                > budget_chars
            ):
                kept_hits.pop()
                omitted["hits"] = len(hits) - index
                break
        if omitted["hits"]:
            # Details for omitted anchors would be unusable.
            allowed_refs = {hit.ref for hit in kept_hits}
            details = [
                detail for detail in details if detail.get("ref") in allowed_refs
            ]

        clipped = False
        for index, detail in enumerate(details):
            kept_details.append(detail)
            if (
                _json_size(build(truncated=False, used_chars=budget_chars))
                <= budget_chars
            ):
                continue
            kept_details.pop()
            remaining = budget_chars - _json_size(
                build(truncated=True, used_chars=budget_chars)
            )
            compact, was_clipped = _compact_detail(detail, max(remaining, 0))
            if compact is not None:
                kept_details.append(compact)
                clipped = was_clipped
            omitted["details"] = len(details) - index - (1 if compact else 0)
            break

        truncated = bool(omitted["hits"] or omitted["details"] or clipped)
        pack = build(truncated=truncated)
        used = _json_size(pack)
        pack = replace(pack, used_chars=used)
        # Account for the digit width of ``used_chars`` itself.
        for _ in range(3):
            actual = _json_size(pack)
            if actual == pack.used_chars:
                break
            pack = replace(pack, used_chars=actual)
        return pack


def _normalize_filter(values: Sequence[str] | None) -> set[str] | None:
    if values is None:
        return None
    return {str(value) for value in values}


def _symbol_ref(source: str, snapshot: str, node_id: str) -> str:
    return f"{source}@{snapshot}:{node_id}"


def _registry_namespace(item_id: str) -> str | None:
    if not item_id.startswith("@") or "/" not in item_id:
        return None
    return item_id[1:].split("/", 1)[0]


def _optional_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _error_text(exc: Exception) -> str:
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def _context_warnings(
    freshness: Mapping[str, Any], coverage: Mapping[str, Any]
) -> tuple[str, ...]:
    warnings: list[str] = []
    overall = str(freshness.get("overall", "unknown"))
    if overall != "fresh":
        warnings.append(f"collection freshness is {overall}")
    failed = int(coverage.get("failed_sources", 0))
    if failed:
        warnings.append(f"{failed} selected source(s) failed during retrieval")
    if coverage.get("registry") != "available":
        warnings.append(f"registry status is {coverage.get('registry', 'unknown')}")
    return tuple(warnings)


def _suggested_actions(hits: Sequence[SearchHit]) -> tuple[dict[str, Any], ...]:
    actions: list[dict[str, Any]] = []
    for hit in hits[:5]:
        if hit.executable:
            actions.append(
                {
                    "action": "handoff_to_molexp",
                    "capability_id": hit.ref,
                }
            )
        else:
            actions.append({"action": "describe", "ref": hit.ref})
    return tuple(actions)


def _call_supported(method: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a duck-typed method with only keyword arguments it accepts."""

    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return method(*args, **kwargs)
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if not accepts_kwargs:
        kwargs = {
            key: value for key, value in kwargs.items() if key in signature.parameters
        }
    return method(*args, **kwargs)


def _unwrap_registry_result(result: Any) -> tuple[Any, str]:
    if isinstance(result, Mapping) and "item" in result:
        return result["item"], str(result.get("score_channel") or "registry")
    item = getattr(result, "item", None)
    if item is not None:
        return item, str(getattr(result, "score_channel", "registry"))
    return result, "registry"


def _object_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        try:
            return _jsonable(dumper(mode="json"))
        except TypeError:
            return _jsonable(dumper())
    dumper = getattr(value, "to_dict", None)
    if callable(dumper):
        return _jsonable(dumper())
    if is_dataclass(value):
        return _jsonable(asdict(value))
    keys = (
        "schema_version",
        "id",
        "kind",
        "title",
        "summary",
        "package",
        "package_version",
        "tags",
        "aliases",
        "examples",
        "provenance",
        "invocation",
        "input_schema",
        "output_schema",
        "side_effects",
        "supported_backends",
        "requirements",
        "validators",
        "timeout_seconds",
        "resource_class",
        "freshness",
    )
    return {key: _jsonable(getattr(value, key)) for key in keys if hasattr(value, key)}


def _node_mapping(node: Any) -> dict[str, Any]:
    dumper = getattr(node, "to_dict", None)
    if callable(dumper):
        return _jsonable(dumper())
    keys = (
        "id",
        "kind",
        "name",
        "qualname",
        "language",
        "file",
        "start_line",
        "end_line",
        "signature",
        "docstring",
        "summary",
        "decorators",
        "bases",
        "visibility",
        "is_exported",
        "is_async",
        "is_abstract",
        "metadata",
    )
    return {key: _jsonable(getattr(node, key)) for key in keys if hasattr(node, key)}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if hasattr(value, "value"):
        return _jsonable(value.value)
    return str(value)


def _json_size(pack: ContextPack) -> int:
    return len(
        json.dumps(
            pack.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _compact_detail(
    detail: dict[str, Any], available_chars: int
) -> tuple[dict[str, Any] | None, bool]:
    """Keep identity/signature first, then fit a clipped source snippet."""

    if available_chars <= 0:
        return None, False
    compact = {
        key: detail[key]
        for key in (
            "ref",
            "id",
            "kind",
            "title",
            "qualname",
            "signature",
            "summary",
            "freshness",
            "executable",
            "executable_capability_id",
        )
        if key in detail
    }
    base_size = len(
        json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    if base_size > available_chars:
        return None, False
    source = detail.get("source")
    if not isinstance(source, str) or not source:
        return compact, len(compact) < len(detail)
    room = available_chars - base_size - len(',"source":""') - 24
    if room <= 0:
        return compact, True
    compact["source"] = source[:room]
    if len(source) > room:
        compact["source"] += "\n... (truncated)"
    return compact, True
