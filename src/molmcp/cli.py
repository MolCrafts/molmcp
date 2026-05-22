"""``molmcp`` CLI — run the MCP server or drive the discovery engine."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from collections import Counter

from .server import create_server

# Installed MolCrafts packages discovery defaults to when no --source is
# given. Filtered to whatever is importable in the active environment.
_DEFAULT_PACKAGES = ("molpy", "molpack", "molrs", "molq", "molexp")

_SPEC_HELP = (
    "source spec: a local path, 'pkg:<name>' for an installed package, "
    "or 'github:owner/repo[@ref]'"
)


def _available_default_sources() -> list[str]:
    return [
        f"pkg:{pkg}"
        for pkg in _DEFAULT_PACKAGES
        if importlib.util.find_spec(pkg) is not None
    ]


# -- molmcp serve --------------------------------------------------------


def _build_serve_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="molmcp",
        description="Start an MCP server exposing graph-based codebase "
        "discovery tools and any registered domain providers. Run "
        "'molmcp discovery --help' to drive the engine without a client.",
    )
    p.add_argument(
        "--name",
        default="molmcp",
        help="Server name advertised to MCP clients (default: molmcp).",
    )
    p.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="SPEC",
        help="Discovery source: a local path, 'pkg:<name>' for an "
        "installed package, or 'github:owner/repo[@ref]'. Repeatable. "
        "When omitted, defaults to whichever of "
        "{molpy, molpack, molrs, molq, molexp} are installed.",
    )
    p.add_argument(
        "--no-discover",
        action="store_true",
        help="Do not auto-discover providers via the molmcp.providers "
        "entry point.",
    )
    p.add_argument(
        "--no-validate-annotations",
        action="store_true",
        help="Skip startup-time check that all tools have ToolAnnotations.",
    )
    p.add_argument(
        "--transport",
        "-t",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio).",
    )
    p.add_argument("--host", default="127.0.0.1", help="Bind address (HTTP/SSE).")
    p.add_argument("--port", "-p", type=int, default=8787, help="Port (HTTP/SSE).")
    return p


def _serve_main(argv: list[str]) -> int:
    args = _build_serve_parser().parse_args(argv)
    server = create_server(
        name=args.name,
        discovery_sources=args.source or _available_default_sources(),
        discover_entry_points=not args.no_discover,
        validate_annotations=not args.no_validate_annotations,
    )
    kwargs: dict = {"transport": args.transport}
    if args.transport != "stdio":
        kwargs["host"] = args.host
        kwargs["port"] = args.port
    server.run(**kwargs)
    return 0


# -- molmcp discovery ----------------------------------------------------


def _build_discovery_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="molmcp discovery",
        description="Inspect and drive the discovery engine without an "
        "MCP client.",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="SUBCOMMAND")

    idx = sub.add_parser(
        "index",
        help="Index a source and print a summary.",
        description="Index a source into a code graph and print a summary.",
    )
    idx.add_argument("source", metavar="SOURCE", help=_SPEC_HELP)

    ver = sub.add_parser(
        "verify",
        help="Index a source and print a health report.",
        description="Index a source and run a self-check — counts, FTS "
        "status, and a sample query. Exits non-zero if discovery is not "
        "working.",
    )
    ver.add_argument("source", metavar="SOURCE", help=_SPEC_HELP)

    qry = sub.add_parser(
        "query",
        help="Search symbols in a source.",
        description="Full-text search over a source's indexed symbols.",
    )
    qry.add_argument("source", metavar="SOURCE", help=_SPEC_HELP)
    qry.add_argument("text", help="Search text.")
    qry.add_argument(
        "--kind",
        default=None,
        help="Filter by node kind (class, function, method, test, ...).",
    )
    qry.add_argument(
        "--limit", type=int, default=20, help="Max results (default: 20)."
    )

    out = sub.add_parser(
        "outline",
        help="Print a source's structure.",
        description="Print a source's packages/modules mapped to their "
        "symbols.",
    )
    out.add_argument("source", metavar="SOURCE", help=_SPEC_HELP)
    out.add_argument(
        "--path", default=None, help="Narrow to a file or subtree."
    )

    dmp = sub.add_parser(
        "dump",
        help="Dump a source's graph as JSON.",
        description="Dump a source's full code graph (nodes, edges, files, "
        "unresolved references) as JSON.",
    )
    dmp.add_argument("source", metavar="SOURCE", help=_SPEC_HELP)
    dmp.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Write JSON to a file instead of stdout.",
    )

    cln = sub.add_parser(
        "clean",
        help="Prune old cached snapshots (or wipe with --all).",
        description="Prune cached snapshots past the retention limits.",
    )
    cln.add_argument(
        "--all",
        action="store_true",
        help="Remove the entire discovery cache instead of pruning.",
    )
    return p


def _fmt_counter(counter: Counter, top: int = 8) -> str:
    items = counter.most_common(top)
    return ", ".join(f"{kind} {count}" for kind, count in items) or "(none)"


def _cmd_index(engine, args) -> int:
    result = engine.index(args.source, force=True)
    snapshot = result.snapshot
    print(f"indexed {args.source}")
    print(f"  snapshot:  {snapshot.snapshot_id}")
    print(f"  origin:    {snapshot.origin}")
    print(f"  files:     {result.file_count}")
    print(f"  nodes:     {result.node_count}")
    print(f"  edges:     {result.edge_count}")
    print(f"  cache:     {engine.cache.snapshot_dir(snapshot.snapshot_id)}")
    return 0


def _cmd_verify(engine, args) -> int:
    from .discovery import DiscoveryQuery
    from .discovery.store import GraphStore

    print(f"verifying discovery for: {args.source}")
    result = engine.index(args.source, force=True)
    graph = result.graph
    snapshot = result.snapshot

    store = GraphStore(engine.cache.graph_db_path(snapshot.snapshot_id))
    fts = store.fts_available()
    sample = next(
        (n for n in graph.nodes if n.kind in ("class", "function")), None
    )
    sample_ok = True
    sample_line = "  sample search: (skipped — no class/function nodes)"
    if sample is not None:
        hits = DiscoveryQuery(store, snapshot).search(sample.name, limit=10)
        sample_ok = any(h.id == sample.id for h in hits)
        sample_line = (
            f"  sample search: '{sample.name}' -> "
            f"{'ok' if sample_ok else 'MISMATCH'}"
        )
    store.close()

    kinds = Counter(str(n.kind) for n in graph.nodes)
    edges = Counter(str(e.kind) for e in graph.edges)
    print(f"  snapshot:      {snapshot.snapshot_id}")
    print(f"  origin:        {snapshot.origin} (freshness: {result.freshness})")
    print(f"  files:         {result.file_count}")
    print(f"  nodes:         {result.node_count}  [{_fmt_counter(kinds)}]")
    print(f"  edges:         {result.edge_count}  [{_fmt_counter(edges)}]")
    print(f"  unresolved:    {len(graph.unresolved)}")
    print(
        f"  FTS5 index:    "
        f"{'available' if fts else 'unavailable (LIKE fallback)'}"
    )
    print(sample_line)

    problems: list[str] = []
    if result.node_count == 0:
        problems.append("no nodes were extracted")
    if not sample_ok:
        problems.append("search did not return a known symbol")
    if problems:
        print(f"  result:        FAILED — {'; '.join(problems)}")
        return 1
    print("  result:        OK — discovery is working")
    return 0


def _cmd_query(engine, args) -> int:
    query = engine.query(args.source)
    try:
        results = query.search(args.text, kind=args.kind, limit=args.limit)
        print(f"{len(results)} match(es) for {args.text!r} in {args.source}")
        for node in results:
            print(
                f"  {node.kind:10} {node.qualname}  "
                f"({node.file}:{node.start_line})"
            )
            if node.summary:
                print(f"             {node.summary}")
    finally:
        query.store.close()
    return 0


def _cmd_outline(engine, args) -> int:
    query = engine.query(args.source)
    try:
        outline = query.outline(path=args.path)
        print(f"{outline['module_count']} module(s) in {args.source}")
        for module in outline["modules"]:
            print(f"  {module['kind']}: {module['qualname']}  ({module['file']})")
            for symbol in module["symbols"]:
                print(f"    {symbol['kind']:10} {symbol['name']}")
                for member in symbol.get("members", []):
                    print(f"      {member['kind']:10} {member['name']}")
    finally:
        query.store.close()
    return 0


def _cmd_dump(engine, args) -> int:
    graph = engine.get_graph(args.source)
    payload = {
        "nodes": [n.to_dict() for n in graph.nodes],
        "edges": [e.to_dict() for e in graph.edges],
        "files": [f.to_dict() for f in graph.files],
        "unresolved": [u.to_dict() for u in graph.unresolved],
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.output} ({len(graph.nodes)} nodes)")
    else:
        print(text)
    return 0


def _cmd_clean(engine, args) -> int:
    cache_dir = engine.config.cache_dir
    if args.all:
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            print(f"removed {cache_dir}")
        else:
            print(f"nothing to clean ({cache_dir} does not exist)")
        return 0
    summary = engine.cache.evict()
    print(f"pruned {summary['removed_count']} snapshot(s)")
    for snapshot_id in summary["removed"]:
        print(f"  - {snapshot_id}")
    return 0


_DISCOVERY_COMMANDS = {
    "index": _cmd_index,
    "verify": _cmd_verify,
    "query": _cmd_query,
    "outline": _cmd_outline,
    "dump": _cmd_dump,
    "clean": _cmd_clean,
}


def _discovery_main(argv: list[str]) -> int:
    from .discovery import DiscoveryConfig, DiscoveryEngine
    from .discovery.source import SourceError

    args = _build_discovery_parser().parse_args(argv)
    engine = DiscoveryEngine(DiscoveryConfig())
    try:
        return _DISCOVERY_COMMANDS[args.command](engine, args)
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "discovery":
        return _discovery_main(argv[1:])
    if argv and argv[0] == "serve":
        return _serve_main(argv[1:])
    return _serve_main(argv)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
