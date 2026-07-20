"""JSON-friendly contracts for collection-wide retrieval.

The collection layer deliberately owns its wire-shaped result types instead of
leaking discovery ``Node`` objects or registry model implementations.  This
keeps the layer independent from MCP and lets registries participate through a
small duck-typed interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceBinding:
    """Bind a collection source name to a discovery engine and source spec.

    ``engine`` is expected to expose ``query(spec)``.  ``snapshot`` exists for
    lightweight/static query adapters; a normal ``DiscoveryQuery`` supplies
    the snapshot itself.
    """

    name: str
    spec: str
    engine: Any
    namespace: str | None = None
    snapshot: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueError("source name must not be empty")
        if "@" in name or ":" in name:
            raise ValueError("source name must not contain '@' or ':'")
        if not self.spec.strip():
            raise ValueError("source spec must not be empty")
        if not callable(getattr(self.engine, "query", None)):
            raise TypeError("source engine must expose query(spec)")
        object.__setattr__(self, "name", name)

    def open_query(self) -> Any:
        """Open the source's discovery query handle."""

        return self.engine.query(self.spec)


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One registry or source-graph retrieval result."""

    ref: str
    kind: str
    title: str
    summary: str | None = None
    namespace: str | None = None
    source: str | None = None
    snapshot: str | None = None
    signature: str | None = None
    executable: bool = False
    executable_capability_id: str | None = None
    execution_status: str = "not_executable"
    score: float = 0.0
    score_channel: str = "rrf"
    matched_channels: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    freshness: str = "unknown"
    span: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "ref": self.ref,
            "kind": self.kind,
            "namespace": self.namespace,
            "source": self.source,
            "snapshot": self.snapshot,
            "title": self.title,
            "summary": self.summary,
            "signature": self.signature,
            "executable": self.executable,
            "executable_capability_id": self.executable_capability_id,
            "execution_status": self.execution_status,
            "score": self.score,
            "score_channel": self.score_channel,
            "matched_channels": list(self.matched_channels),
            "provenance": dict(self.provenance),
            "freshness": self.freshness,
            "span": dict(self.span) if self.span is not None else None,
        }


@dataclass(frozen=True, slots=True)
class ContextPack:
    """Bounded, collection-wide evidence assembled for one task."""

    task: str
    filters: dict[str, Any]
    hits: tuple[SearchHit, ...]
    details: tuple[dict[str, Any], ...]
    freshness: dict[str, Any]
    coverage: dict[str, Any]
    truncated: bool
    unresolved: tuple[dict[str, Any], ...]
    omitted: dict[str, int]
    warnings: tuple[str, ...]
    suggested_actions: tuple[dict[str, Any], ...]
    provenance: dict[str, Any]
    budget_chars: int
    used_chars: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "task": self.task,
            "filters": dict(self.filters),
            "hits": [hit.to_dict() for hit in self.hits],
            "details": [dict(detail) for detail in self.details],
            "freshness": dict(self.freshness),
            "coverage": dict(self.coverage),
            "truncated": self.truncated,
            "unresolved": [dict(item) for item in self.unresolved],
            "omitted": dict(self.omitted),
            "warnings": list(self.warnings),
            "suggested_actions": [dict(item) for item in self.suggested_actions],
            "provenance": dict(self.provenance),
            "budget_chars": self.budget_chars,
            "used_chars": self.used_chars,
        }
