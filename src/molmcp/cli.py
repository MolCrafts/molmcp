"""``molmcp`` CLI — run the MCP server or drive the discovery engine."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from collections import Counter

from .server import create_server

# MolCrafts sources discovery defaults to when no --source is given.
# Each resolves to the locally installed copy (``pkg:``) when importable
# in the active environment (uv / venv), otherwise to the upstream repo
# (``github:``) — so discovery works whether or not a package is
# installed, and core never imports a MolCrafts package.
_GITHUB_OWNER = "MolCrafts"

# Single-package sources: the import name doubles as the GitHub repo name.
_DEFAULT_PACKAGES = ("molpy", "molpack", "molrs", "molq", "molexp")

# Multi-package repos with no single import name — always indexed whole
# from GitHub. molnex ships four packages (molix, molpot, molrep, molzoo),
# so there is no ``molnex`` module to resolve a ``pkg:`` spec against.
_DEFAULT_REPOS = ("molnex",)

_SPEC_HELP = (
    "source spec: a local path, 'pkg:<name>' for an installed package, "
    "or 'github:owner/repo[@ref]'"
)


def _is_importable(pkg: str) -> bool:
    """Whether ``pkg`` is importable in the active environment."""
    try:
        return importlib.util.find_spec(pkg) is not None
    except (ImportError, ValueError):
        return False


def _local_or_github(pkg: str) -> str:
    """Local install spec when ``pkg`` is importable, else its GitHub repo."""
    if _is_importable(pkg):
        return f"pkg:{pkg}"
    return f"github:{_GITHUB_OWNER}/{pkg}"


def _source_for_package(pkg: str) -> str:
    """Discovery source for one default package.

    Multi-package repos (no single import name) are always taken whole
    from GitHub; single packages prefer a local install and fall back to
    their GitHub repo.
    """
    if pkg in _DEFAULT_REPOS:
        return f"github:{_GITHUB_OWNER}/{pkg}"
    return _local_or_github(pkg)


def _available_default_sources() -> list[str]:
    """Default discovery sources: every MolCrafts package, local-first."""
    return [_source_for_package(pkg) for pkg in (*_DEFAULT_PACKAGES, *_DEFAULT_REPOS)]


def _split_pkg_values(raw: list[str]) -> list[str]:
    """Normalize ``--pkg`` values: split on commas, strip, drop empties.

    ``--pkg molpy,molexp`` and ``--pkg molpy --pkg molexp`` are
    equivalent. Order is preserved; duplicates collapse to first use.
    """
    seen: list[str] = []
    for value in raw:
        for token in value.split(","):
            token = token.strip()
            if token and token not in seen:
                seen.append(token)
    return seen


def _resolve_serve_sources(pkgs: list[str], explicit_sources: list[str]) -> list[str]:
    """Discovery sources for ``serve``.

    An explicit ``--source`` wins outright; otherwise ``--pkg`` narrows
    the defaults to the chosen packages; otherwise all defaults load.
    """
    if explicit_sources:
        return explicit_sources
    if pkgs:
        return [_source_for_package(pkg) for pkg in pkgs]
    return _available_default_sources()


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
        "--pkg",
        action="append",
        default=[],
        metavar="NAME[,NAME...]",
        help="Restrict to these MolCrafts packages (repeatable or "
        "comma-separated). Narrows both the default discovery sources and "
        "the entry-point-discovered providers. When omitted, every "
        "package loads. Example: --pkg molpy,molexp.",
    )
    p.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="SPEC",
        help="Discovery source: a local path, 'pkg:<name>' for an "
        "installed package, or 'github:owner/repo[@ref]'. Repeatable. "
        "Overrides the --pkg-derived default for discovery sources only "
        "(provider filtering still honors --pkg). When both are omitted, "
        "defaults to the MolCrafts packages (molpy, molpack, molrs, molq, "
        "molexp, molnex) — each read from a local install when present, "
        "and from GitHub otherwise.",
    )
    p.add_argument(
        "--no-discover",
        action="store_true",
        help="Do not auto-discover providers via the molmcp.providers entry point.",
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
    pkgs = _split_pkg_values(args.pkg)
    server = create_server(
        name=args.name,
        discovery_sources=_resolve_serve_sources(pkgs, args.source),
        discover_entry_points=not args.no_discover,
        provider_names=set(pkgs) or None,
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
        description="Inspect and drive the discovery engine without an MCP client.",
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
    qry.add_argument("--limit", type=int, default=20, help="Max results (default: 20).")

    out = sub.add_parser(
        "outline",
        help="Print a source's structure.",
        description="Print a source's packages/modules mapped to their symbols.",
    )
    out.add_argument("source", metavar="SOURCE", help=_SPEC_HELP)
    out.add_argument("--path", default=None, help="Narrow to a file or subtree.")

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

    lnt = sub.add_parser(
        "lint",
        help="Report discoverability findings for a source.",
        description="Measure a source's discoverability health: "
        "undocumented exported symbols, untested public symbols, and "
        "modules with a high unresolved-reference share. Advisory — "
        "exits 0 even with findings; --strict exits 1 when any exist.",
    )
    lnt.add_argument(
        "source", nargs="?", default=None, metavar="SOURCE", help=_SPEC_HELP
    )
    lnt.add_argument(
        "--pkg",
        action="append",
        default=[],
        metavar="NAME[,NAME...]",
        help="Lint these MolCrafts packages (repeatable or "
        "comma-separated); used when SOURCE is omitted.",
    )
    lnt.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON report.",
    )
    lnt.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when any finding exists (for upstream CI gates).",
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
    sample = next((n for n in graph.nodes if n.kind in ("class", "function")), None)
    sample_ok = True
    sample_line = "  sample search: (skipped — no class/function nodes)"
    if sample is not None:
        hits = DiscoveryQuery(store, snapshot).search(sample.name, limit=10)
        sample_ok = any(h.id == sample.id for h in hits)
        sample_line = (
            f"  sample search: '{sample.name}' -> {'ok' if sample_ok else 'MISMATCH'}"
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
    print(f"  FTS5 index:    {'available' if fts else 'unavailable (LIKE fallback)'}")
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
            print(f"  {node.kind:10} {node.qualname}  ({node.file}:{node.start_line})")
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


def _render_lint_report(source: str, report) -> None:
    """Human-readable lint report: three sections plus counts."""
    print(f"lint {source}")
    print(f"  undocumented exports: {len(report.undocumented_exports)}")
    for node in report.undocumented_exports:
        print(f"    {node.qualname}  ({node.file}:{node.start_line})")
    print(f"  untested public symbols: {len(report.untested_public_symbols)}")
    for node in report.untested_public_symbols:
        print(f"    {node.qualname}  ({node.file}:{node.start_line})")
    print(f"  high-unresolved modules: {len(report.high_unresolved_modules)}")
    for stat in report.high_unresolved_modules:
        print(
            f"    {stat.file}  {stat.unresolved_count}/{stat.total_refs} "
            f"unresolved ({stat.ratio:.0%})"
        )
    if report.total_findings == 0:
        print("  OK — no discoverability findings")


def _cmd_lint(engine, args) -> int:
    """Lint one or more sources; advisory exit unless --strict."""
    from .discovery.lint import lint_graph

    if args.source:
        sources = [args.source]
    else:
        sources = [_source_for_package(p) for p in _split_pkg_values(args.pkg)]
    reports = []
    total_findings = 0
    for spec in sources:
        report = lint_graph(engine.get_graph(spec))
        total_findings += report.total_findings
        reports.append((spec, report))
    if args.json:
        payload = {
            "reports": [
                {"source": spec, **report.to_dict()} for spec, report in reports
            ],
            "total_findings": total_findings,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for spec, report in reports:
            _render_lint_report(spec, report)
    return 1 if args.strict and total_findings > 0 else 0


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
    "lint": _cmd_lint,
    "clean": _cmd_clean,
}


def _discovery_main(argv: list[str]) -> int:
    from .discovery import DiscoveryConfig, DiscoveryEngine
    from .discovery.source import SourceError

    parser = _build_discovery_parser()
    args = parser.parse_args(argv)
    if args.command == "lint" and not args.source and not _split_pkg_values(args.pkg):
        # No implicit default: linting every default source would
        # trigger several GitHub fetches.
        parser.error("lint requires SOURCE or --pkg")
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
