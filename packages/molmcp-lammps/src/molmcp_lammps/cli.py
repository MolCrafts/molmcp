"""CLI for ``molmcp-lammps``.

Default invocation runs the MCP server. The ``doc update`` subcommand
regenerates the bundled slug map from docs.lammps.org — a one-shot
maintenance task the package maintainer runs when LAMMPS releases a
new version with new commands or styles.
"""

from __future__ import annotations

import argparse


def _add_server_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--transport",
        "-t",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", "-p", type=int, default=8787)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="molmcp-lammps",
        description=(
            "Run the molmcp-lammps MCP server, or run developer "
            "maintenance subcommands."
        ),
    )
    _add_server_args(parser)

    subparsers = parser.add_subparsers(dest="command", required=False)

    doc_p = subparsers.add_parser(
        "doc",
        help="Doc-table maintenance (alias map, howto topic list).",
        description="Doc-table maintenance (alias map, howto topic list).",
    )
    doc_subs = doc_p.add_subparsers(dest="doc_action", required=True)

    update_p = doc_subs.add_parser(
        "update",
        help="Refresh the LAMMPS slug map from docs.lammps.org.",
        description=(
            "Scrape docs.lammps.org Sphinx index pages and regenerate "
            "_generated_slugs.py inside the package. Requires network access."
        ),
    )
    update_p.add_argument(
        "--check",
        action="store_true",
        help="Print the diff vs the existing file but do not write.",
    )
    update_p.add_argument(
        "--version",
        default="stable",
        choices=["stable", "latest", "release"],
        help="LAMMPS doc branch to scrape (default: stable).",
    )

    return parser


def _run_doc_update(args: argparse.Namespace) -> int:
    from ._dev.lammps_slugs import run

    return run(check=args.check, version=args.version)


def _run_server(args: argparse.Namespace) -> int:
    from .server import mcp

    kwargs: dict[str, object] = {"transport": args.transport}
    if args.transport != "stdio":
        kwargs["host"] = args.host
        kwargs["port"] = args.port
    mcp.run(**kwargs)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doc":
        if args.doc_action == "update":
            return _run_doc_update(args)
        raise AssertionError(
            f"unhandled doc subcommand: {args.doc_action}"
        )
    return _run_server(args)


if __name__ == "__main__":
    raise SystemExit(main())
