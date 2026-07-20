"""Clean MolMCP vNext CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import AppConfig, ConfigurationError, load_config
from .registry import ManifestError, load_manifest
from .runtime import build_collection, build_registry
from .server import create_server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="molmcp",
        description=(
            "MolCrafts capability registry, code intelligence, and MCP context plane."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="Start the MCP server.")
    _config_argument(serve)
    serve.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=None,
        help="Override the transport from molcrafts.json.",
    )
    serve.add_argument("--host", default=None, help="Override the HTTP bind host.")
    serve.add_argument("--port", type=int, default=None, help="Override the HTTP port.")
    serve.add_argument(
        "--no-providers",
        action="store_true",
        help="Disable package-owned molmcp.providers entry points.",
    )

    info = commands.add_parser("info", help="Show registry and index coverage.")
    _config_argument(info)

    search = commands.add_parser("search", help="Search the full collection.")
    _config_argument(search)
    search.add_argument("query")
    search.add_argument("--kind", action="append", default=[])
    search.add_argument("--namespace", action="append", default=[])
    search.add_argument("--source", action="append", default=[])
    search.add_argument("--limit", type=int, default=20)

    explore = commands.add_parser("explore", help="Build a bounded task context pack.")
    _config_argument(explore)
    explore.add_argument("task")
    explore.add_argument("--namespace", action="append", default=[])
    explore.add_argument("--source", action="append", default=[])
    explore.add_argument("--budget-chars", type=int, default=16_000)

    index = commands.add_parser("index", help="Index configured sources.")
    _config_argument(index)
    index.add_argument(
        "sources",
        nargs="*",
        metavar="SOURCE_NAME",
        help="Configured source names; omit to index all.",
    )
    index.add_argument("--force", action="store_true")

    registry = commands.add_parser("registry", help="Inspect capability manifests.")
    registry_commands = registry.add_subparsers(dest="registry_command", required=True)
    validate = registry_commands.add_parser("validate", help="Validate one manifest.")
    validate.add_argument("manifest", type=Path)
    listing = registry_commands.add_parser(
        "list", help="List configured registry items."
    )
    _config_argument(listing)
    return parser


def _config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to molcrafts.json (default: ./molcrafts.json when present).",
    )


def _load(path: Path | None) -> AppConfig:
    return load_config(path)


def _emit(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def _optional(values: list[str]) -> list[str] | None:
    return values or None


def _serve(args: argparse.Namespace) -> int:
    config = _load(args.config)
    server = create_server(
        config=config,
        discover_entry_points=not args.no_providers,
    )
    transport = args.transport or config.server.transport
    kwargs: dict[str, Any] = {"transport": transport}
    if transport != "stdio":
        host = args.host or config.server.host
        port = args.port or config.server.port
        # Revalidate CLI overrides; an authenticated config must still be used
        # for a non-loopback override.
        if (
            host not in {"127.0.0.1", "::1", "localhost"}
            and not config.server.auth_token_env
        ):
            raise ConfigurationError(
                "non-loopback streamable HTTP requires server.auth_token_env"
            )
        kwargs.update(host=host, port=port)
    server.run(**kwargs)
    return 0


def _collection(args: argparse.Namespace):
    config = _load(args.config)
    registry = build_registry(config)
    return config, build_collection(config, registry)


def _info(args: argparse.Namespace) -> int:
    _, collection = _collection(args)
    _emit(collection.info())
    return 0


def _search(args: argparse.Namespace) -> int:
    _, collection = _collection(args)
    hits = collection.search(
        args.query,
        kinds=_optional(args.kind),
        namespaces=_optional(args.namespace),
        sources=_optional(args.source),
        limit=args.limit,
    )
    _emit({"query": args.query, "results": [hit.to_dict() for hit in hits]})
    return 0


def _explore(args: argparse.Namespace) -> int:
    _, collection = _collection(args)
    pack = collection.explore(
        args.task,
        namespaces=_optional(args.namespace),
        sources=_optional(args.source),
        budget_chars=args.budget_chars,
    )
    _emit(pack.to_dict())
    return 0


def _index(args: argparse.Namespace) -> int:
    _, collection = _collection(args)
    selected = args.sources or [binding.name for binding in collection.sources]
    unknown = sorted(set(selected) - {binding.name for binding in collection.sources})
    if unknown:
        raise ConfigurationError(f"unknown configured sources: {', '.join(unknown)}")
    results: list[dict[str, Any]] = []
    for binding in collection.sources:
        if binding.name not in selected:
            continue
        result = binding.engine.index(binding.spec, force=args.force)
        results.append(
            {
                "source": binding.name,
                "spec": binding.spec,
                "snapshot": result.snapshot.snapshot_id,
                "cached": result.cached,
                "files": result.file_count,
                "nodes": result.node_count,
                "edges": result.edge_count,
            }
        )
    _emit({"indexed": results})
    return 0


def _registry(args: argparse.Namespace) -> int:
    if args.registry_command == "validate":
        manifest = load_manifest(args.manifest)
        _emit(manifest.to_dict())
        return 0
    config = _load(args.config)
    registry = build_registry(config)
    _emit(
        {
            "info": registry.info(),
            "items": [item.to_dict() for item in registry.list_items()],
        }
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        arguments = ["serve"]
    parser = _build_parser()
    args = parser.parse_args(arguments)
    handlers = {
        "serve": _serve,
        "info": _info,
        "search": _search,
        "explore": _explore,
        "index": _index,
        "registry": _registry,
    }
    try:
        return handlers[args.command](args)
    except (ConfigurationError, ManifestError, FileNotFoundError, ValueError) as exc:
        print(f"molmcp: {exc}", file=sys.stderr)
        return 2


__all__ = ["main"]
