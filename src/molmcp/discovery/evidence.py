"""EvidenceBuilder — assembles capability answers from the graph.

Turns :class:`DiscoveryQuery` results into the JSON-able payloads the
MCP tools return: capability matches with attached examples/tests/
callers, and full single-symbol detail.
"""

from __future__ import annotations

from pathlib import Path

from .query import DiscoveryQuery
from .schema import Node

_MAX_EXAMPLE_CHARS = 2000
_MAX_SOURCE_CHARS = 12000


def node_brief(node: Node) -> dict:
    """Compact node view for lists."""
    return {
        "qualname": node.qualname,
        "name": node.name,
        "kind": str(node.kind),
        "language": node.language,
        "file": node.file,
        "start_line": node.start_line,
        "end_line": node.end_line,
        "signature": node.signature,
        "summary": node.summary,
    }


def node_detail(node: Node) -> dict:
    """Full node view for ``molmcp_describe_symbol``."""
    detail = node_brief(node)
    detail.update(
        docstring=node.docstring,
        decorators=list(node.decorators),
        bases=list(node.bases),
        visibility=str(node.visibility),
        is_exported=node.is_exported,
        is_async=node.is_async,
        is_abstract=node.is_abstract,
        metadata=dict(node.metadata),
    )
    return detail


def example_view(node: Node) -> dict:
    """View of an ``example`` node, with its code snippet."""
    code = str(node.metadata.get("code", ""))
    if len(code) > _MAX_EXAMPLE_CHARS:
        code = code[:_MAX_EXAMPLE_CHARS] + "\n... (truncated)"
    return {
        "qualname": node.qualname,
        "file": node.file,
        "lines": [node.start_line, node.end_line],
        "source": node.metadata.get("source", "docstring"),
        "code": code,
    }


def read_source(root_dir: Path, node: Node) -> str:
    """Read a node's source span from disk (best-effort)."""
    path = Path(root_dir) / node.file
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"<source unavailable: {exc}>"
    snippet = "\n".join(lines[node.start_line - 1 : node.end_line])
    if len(snippet) > _MAX_SOURCE_CHARS:
        snippet = snippet[:_MAX_SOURCE_CHARS] + "\n... (truncated)"
    return snippet


class EvidenceBuilder:
    """Builds capability/evidence payloads from a :class:`DiscoveryQuery`."""

    def __init__(self, query: DiscoveryQuery) -> None:
        self.query = query

    def find_capability(self, task: str, max_results: int) -> dict:
        hits = self.query.search(task, limit=max_results)
        matches = []
        for rank, node in enumerate(hits, 1):
            matches.append(
                {
                    "rank": rank,
                    "node": node_brief(node),
                    "signature": node.signature,
                    "summary": node.summary,
                    "examples": [
                        example_view(e)
                        for e in self.query.examples_of(node.qualname, limit=3)
                    ],
                    "tests": [
                        node_brief(t)
                        for t in self.query.tests_of(node.qualname, limit=5)
                    ],
                    "callers": [
                        node_brief(c)
                        for c in self.query.callers(node.qualname, limit=6)
                    ],
                }
            )
        payload: dict = {
            "query": task,
            "match_count": len(matches),
            "matches": matches,
        }
        if not matches:
            payload["unresolved_hint"] = (
                "No symbols matched. Try molmcp_outline to see the module "
                "structure, or different keywords."
            )
        return payload

    def describe(
        self, qualname: str, include_source: bool, root_dir: Path | None
    ) -> dict | None:
        node = self.query.get_node(qualname)
        if node is None:
            return None
        detail = node_detail(node)
        detail["examples"] = [
            example_view(e)
            for e in self.query.examples_of(qualname, limit=5)
        ]
        detail["tests"] = [
            node_brief(t) for t in self.query.tests_of(qualname, limit=10)
        ]
        detail["caller_count"] = len(self.query.callers(qualname, limit=500))
        detail["callee_count"] = len(self.query.callees(qualname, limit=500))
        if include_source and root_dir is not None:
            detail["source"] = read_source(root_dir, node)
        return detail
