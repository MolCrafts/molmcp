"""molmcp discovery engine — graph-based codebase capability discovery.

This package is MCP-free: it can be imported, exercised, and tested
without FastMCP. The MCP interface lives in :mod:`molmcp.discovery.provider`.
"""

from __future__ import annotations

from .config import DiscoveryConfig
from .engine import DiscoveryEngine, IndexResult
from .query import DiscoveryQuery
from .schema import (
    SCHEMA_VERSION,
    CodeGraph,
    Edge,
    EdgeKind,
    FileRecord,
    Node,
    NodeKind,
    Provenance,
    UnresolvedRef,
)
from .source import Snapshot, SourceError

__all__ = [
    "SCHEMA_VERSION",
    "CodeGraph",
    "DiscoveryConfig",
    "DiscoveryEngine",
    "DiscoveryQuery",
    "Edge",
    "EdgeKind",
    "FileRecord",
    "IndexResult",
    "Node",
    "NodeKind",
    "Provenance",
    "Snapshot",
    "SourceError",
    "UnresolvedRef",
]
