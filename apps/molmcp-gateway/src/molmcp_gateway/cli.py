"""CLI for running the molmcp gateway.

Optionally mounts an additional ``introspection`` namespace exposing
molmcp's source-introspection tools for the configured ``--import-root``
packages. Defaults to ``molpy`` and ``molexp``.
"""

from __future__ import annotations

import argparse

from molmcp import create_server

from .config import DEFAULT_IMPORT_ROOTS
from .server import mcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="molmcp-gateway",
        description=(
            "Run the MolCrafts MCP gateway server. Aggregates the "
            "molpy, molexp, and lammps plugins behind one endpoint."
        ),
    )
    parser.add_argument(
        "--transport",
        "-t",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", "-p", type=int, default=8787)
    parser.add_argument(
        "--import-root",
        action="append",
        default=[],
        help=(
            "Additional Python package whose source to expose via the "
            "introspection mount. Repeatable."
        ),
    )
    parser.add_argument(
        "--no-default-import-roots",
        action="store_true",
        help="Do not expose the default introspection roots: molpy, molexp.",
    )
    parser.add_argument(
        "--no-introspection",
        action="store_true",
        help="Skip the introspection mount entirely.",
    )
    return parser


def _resolve_import_roots(args: argparse.Namespace) -> tuple[str, ...]:
    if args.no_introspection:
        return ()
    roots: list[str] = []
    if not args.no_default_import_roots:
        roots.extend(DEFAULT_IMPORT_ROOTS)
    roots.extend(args.import_root)
    seen: set[str] = set()
    out: list[str] = []
    for r in roots:
        normalized = r.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return tuple(out)


def _maybe_mount_introspection(args: argparse.Namespace) -> None:
    roots = _resolve_import_roots(args)
    if not roots:
        return
    introspection_mcp = create_server(
        name="molmcp-introspection",
        import_roots=roots,
        providers=[],
        discover_entry_points=False,
        validate_annotations=False,
    )
    mcp.mount(introspection_mcp, namespace="introspection")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _maybe_mount_introspection(args)
    kwargs: dict[str, object] = {"transport": args.transport}
    if args.transport != "stdio":
        kwargs["host"] = args.host
        kwargs["port"] = args.port
    mcp.run(**kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
