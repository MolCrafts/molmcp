"""CLI for running the molmcp-molexp server standalone."""

from __future__ import annotations

import argparse

from .server import mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="molmcp-molexp")
    parser.add_argument(
        "--transport",
        "-t",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", "-p", type=int, default=8787)
    args = parser.parse_args(argv)
    kwargs: dict[str, object] = {"transport": args.transport}
    if args.transport != "stdio":
        kwargs["host"] = args.host
        kwargs["port"] = args.port
    mcp.run(**kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
