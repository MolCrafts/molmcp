"""``molmcp`` CLI — run the MCP server or drive the discovery engine."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys

from .server import create_server

# Installed MolCrafts packages discovery defaults to when no --source is
# given. Filtered to whatever is importable in the active environment.
_DEFAULT_PACKAGES = ("molpy", "molpack", "molrs", "molq", "molexp")


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
        "discovery tools and any registered domain providers.",
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
        description="Inspect the discovery engine without an MCP client.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    idx = sub.add_parser("index", help="Index a source and print a summary.")
    idx.add_argument("source", help="Source spec (path / pkg: / github:).")

    qry = sub.add_parser("query", help="Search symbols in a source.")
    qry.add_argument("source", help="Source spec.")
    qry.add_argument("text", help="Search text.")
    qry.add_argument("--kind", default=None, help="Filter by node kind.")
    qry.add_argument("--limit", type=int, default=20, help="Max results.")

    out = sub.add_parser("outline", help="Print a source's structure.")
    out.add_argument("source", help="Source spec.")
    out.add_argument("--path", default=None, help="Narrow to a file/subtree.")

    dmp = sub.add_parser("dump", help="Dump a source's graph as JSON.")
    dmp.add_argument("source", help="Source spec.")
    dmp.add_argument("--output", default=None, help="Write JSON to a file.")

    cln = sub.add_parser(
        "clean", help="Prune old cached snapshots (or wipe with --all)."
    )
    cln.add_argument(
        "--all",
        action="store_true",
        help="Remove the entire discovery cache instead of pruning.",
    )
    return p


def _discovery_main(argv: list[str]) -> int:
    from .discovery import DiscoveryConfig, DiscoveryEngine

    args = _build_discovery_parser().parse_args(argv)
    config = DiscoveryConfig()
    engine = DiscoveryEngine(config)

    if args.command == "clean":
        if args.all:
            if config.cache_dir.exists():
                shutil.rmtree(config.cache_dir)
                print(f"removed {config.cache_dir}")
            else:
                print(f"nothing to clean ({config.cache_dir} does not exist)")
            return 0
        result = engine.cache.evict()
        print(f"pruned {result['removed_count']} snapshot(s)")
        for snapshot_id in result["removed"]:
            print(f"  - {snapshot_id}")
        return 0

    if args.command == "index":
        result = engine.index(args.source, force=True)
        print(f"snapshot:  {result.snapshot.snapshot_id}")
        print(f"files:     {result.file_count}")
        print(f"nodes:     {result.node_count}")
        print(f"edges:     {result.edge_count}")
        print(f"cache:     {engine.cache.snapshot_dir(result.snapshot.snapshot_id)}")
        return 0

    if args.command == "query":
        query = engine.query(args.source)
        results = query.search(args.text, kind=args.kind, limit=args.limit)
        if not results:
            print("no matches")
        for node in results:
            print(f"{node.kind:10} {node.qualname}  ({node.file}:{node.start_line})")
            if node.summary:
                print(f"           {node.summary}")
        query.store.close()
        return 0

    if args.command == "outline":
        query = engine.query(args.source)
        outline = query.outline(path=args.path)
        for module in outline["modules"]:
            print(f"{module['kind']}: {module['qualname']}  ({module['file']})")
            for symbol in module["symbols"]:
                print(f"  {symbol['kind']:10} {symbol['name']}")
                for member in symbol.get("members", []):
                    print(f"    {member['kind']:10} {member['name']}")
        query.store.close()
        return 0

    if args.command == "dump":
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
            print(f"wrote {args.output}")
        else:
            print(text)
        return 0

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
