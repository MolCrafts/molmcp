"""EvidenceBuilder — assembles capability answers from the graph.

Turns :class:`DiscoveryQuery` results into the JSON-able payloads the
MCP tools return: capability matches with attached examples/tests/
callers, and full single-symbol detail.
"""

from __future__ import annotations

from pathlib import Path

from .query import DiscoveryQuery
from .ranking import RankCandidate, rank_matches, rank_signals
from .schema import Edge, Node, NodeKind

_MAX_EXAMPLE_CHARS = 2000
_MAX_SOURCE_CHARS = 12000
_MAX_CONVENTIONS = 3
_MAX_CONVENTION_CHARS = 1200


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


def convention_view(node: Node) -> dict:
    """View of a ``convention`` node, with its rules text size-capped."""
    rules = "\n".join(str(r) for r in node.metadata.get("rules", []))
    if len(rules) > _MAX_CONVENTION_CHARS:
        rules = rules[:_MAX_CONVENTION_CHARS] + "\n... (truncated)"
    return {
        "id": node.qualname,
        "title": str(node.metadata.get("title", "")),
        "scope": list(node.metadata.get("scope", [])),
        "rules": rules,
        "tags": list(node.metadata.get("tags", [])),
    }


def _caller_view(node: Node, edge: Edge) -> dict:
    """Caller entry: node brief plus the call edge's confidence."""
    view = node_brief(node)
    view["provenance"] = str(edge.provenance)
    via = edge.metadata.get("via")
    if via:
        view["via"] = via
    return view


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
        matches = self._capability_matches(task, max_results)
        implemented = {i["qualname"] for m in matches for i in m["implemented_by"]}
        remaining = max_results - len(matches)
        if remaining > 0:
            matches += self._symbol_matches(task, remaining, exclude=implemented)
        for rank, match in enumerate(matches, 1):
            match["rank"] = rank
            match["conventions"] = self._conventions_block(match["node"]["qualname"])
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

    def _capability_matches(self, task: str, max_results: int) -> list[dict]:
        """Curated capability nodes matching ``task``, ranked first."""
        caps = self.query.search(task, kind=NodeKind.CAPABILITY, limit=max_results)
        matches = []
        for node in caps:
            impls = self.query.implementations(node.qualname, limit=10)
            matches.append(
                {
                    "rank": 0,  # assigned globally across both stages
                    "match_type": "capability",
                    "node": node_brief(node),
                    "signature": node.signature,
                    "summary": node.summary,
                    "implemented_by": [node_brief(i) for i in impls],
                    "examples": [
                        example_view(e)
                        for e in self.query.examples_of(node.qualname, limit=3)
                    ],
                }
            )
        return matches

    def _symbol_matches(
        self,
        task: str,
        max_results: int,
        exclude: set[str] | None = None,
    ) -> list[dict]:
        """FTS recall oversampled, then re-ranked by graph signals."""
        skip = exclude or set()
        hits = [
            n
            for n in self.query.search(task, limit=max_results * 3)
            if n.kind != NodeKind.CAPABILITY and n.qualname not in skip
        ]
        counts = self.query.caller_counts([n.id for n in hits])
        evidence: dict[str, tuple[list[Node], list[Node]]] = {}
        candidates = []
        for fts_rank, node in enumerate(hits):
            examples = self.query.examples_of(node.qualname, limit=3)
            tests = self.query.tests_of(node.qualname, limit=5)
            evidence[node.id] = (examples, tests)
            candidates.append(
                RankCandidate(
                    node=node,
                    fts_rank=fts_rank,
                    caller_count=counts.get(node.id, 0),
                    example_count=len(examples),
                    test_count=len(tests),
                )
            )
        matches = []
        for rank, cand in enumerate(rank_matches(candidates)[:max_results], 1):
            node = cand.node
            examples, tests = evidence[node.id]
            matches.append(
                {
                    "rank": rank,
                    "match_type": "symbol",
                    "node": node_brief(node),
                    "signature": node.signature,
                    "summary": node.summary,
                    "rank_signals": rank_signals(cand),
                    "examples": [example_view(e) for e in examples],
                    "tests": [node_brief(t) for t in tests],
                    "callers": [
                        _caller_view(c, e)
                        for c, e in self.query.callers_pairs(node.qualname, limit=6)
                    ],
                }
            )
        return matches

    def _conventions_block(self, qualname: str) -> list[dict]:
        """Scope-matched conventions for a symbol, capped in count."""
        return [
            convention_view(c)
            for c in self.query.conventions_for(qualname, limit=_MAX_CONVENTIONS)
        ]

    def describe(
        self, qualname: str, include_source: bool, root_dir: Path | None
    ) -> dict | None:
        node = self.query.get_node(qualname)
        if node is None:
            return None
        detail = node_detail(node)
        detail["examples"] = [
            example_view(e) for e in self.query.examples_of(qualname, limit=5)
        ]
        detail["tests"] = [
            node_brief(t) for t in self.query.tests_of(qualname, limit=10)
        ]
        detail["caller_count"] = len(self.query.callers(qualname, limit=500))
        detail["callee_count"] = len(self.query.callees(qualname, limit=500))
        detail["conventions"] = self._conventions_block(node.qualname)
        if include_source and root_dir is not None:
            detail["source"] = read_source(root_dir, node)
        return detail
