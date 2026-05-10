"""``molmcp`` CLI — start a server from the command line."""

from __future__ import annotations

import argparse
import importlib.util
import sys

from .server import create_server

# Default introspection roots: every first-party MolCrafts Python package
# the suite knows about. Filtered down at start time to whatever is
# actually importable, so unused packages don't crash startup.
_DEFAULT_IMPORT_ROOTS = ("molpy", "molpack", "molrs", "molq", "molexp")


def _available_default_roots() -> list[str]:
    return [r for r in _DEFAULT_IMPORT_ROOTS if importlib.util.find_spec(r)]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="molmcp",
        description="Start an MCP server exposing source-introspection tools "
        "and any registered domain providers.",
    )
    p.add_argument(
        "--name",
        default="molmcp",
        help="Server name advertised to MCP clients (default: molmcp).",
    )
    p.add_argument(
        "--import-root",
        action="append",
        default=[],
        help="Python package whose source to expose. Repeatable. "
        "When omitted, defaults to whichever of "
        "{molpy, molpack, molrs, molq, molexp} are installed. "
        "Example: --import-root molpy --import-root rdkit",
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = create_server(
        name=args.name,
        import_roots=args.import_root or _available_default_roots() or ["molmcp"],
        discover_entry_points=not args.no_discover,
        validate_annotations=not args.no_validate_annotations,
    )
    kwargs: dict = {"transport": args.transport}
    if args.transport != "stdio":
        kwargs["host"] = args.host
        kwargs["port"] = args.port
    server.run(**kwargs)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
