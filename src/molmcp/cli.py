"""Plane-oriented MolMCP CLI — one MCP process per product plane."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client_config import render_client
from .config import AppConfig, ConfigurationError, load_config
from .planes import known_plane_ids, list_plane_infos, route_task
from .registry import ManifestError, load_manifest
from .runtime import build_collection, build_registry
from .server import create_plane


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="molmcp",
        description=(
            "MolCrafts multi-plane MCP: one product domain per connection. "
            "Default: enable all planes in the client; use --disable / --enable."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser(
        "serve",
        help="Start one MCP plane (required plane id).",
    )
    _config_argument(serve)
    serve.add_argument(
        "plane",
        help=(
            "Plane to serve: catalog | molcrafts | <provider> "
            "(run `molmcp planes` for the list)."
        ),
    )
    serve.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=None,
        help="Override the transport from molcrafts.json.",
    )
    serve.add_argument("--host", default=None, help="Override the HTTP bind host.")
    serve.add_argument("--port", type=int, default=None, help="Override the HTTP port.")
    serve.add_argument(
        "--no-discover",
        action="store_true",
        help="Do not load molmcp.providers entry points (provider planes need inject).",
    )

    planes = commands.add_parser(
        "planes",
        help="List connectable MCP planes (on-demand multi-link catalog).",
    )
    planes.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )

    route = commands.add_parser(
        "route",
        help="Suggest which plane(s) a task will use (routing hint only).",
    )
    route.add_argument("task", help="User task description.")

    client = commands.add_parser(
        "client",
        help=(
            "Emit host MCP config. Default: all planes enabled; "
            "use --disable / --enable to toggle."
        ),
    )
    client.add_argument(
        "host",
        choices=["grok", "claude"],
        help="Target host config format.",
    )
    client.add_argument(
        "--enable",
        action="append",
        default=[],
        metavar="PLANE",
        help="Enable a plane (after --disable). Repeatable.",
    )
    client.add_argument(
        "--disable",
        action="append",
        default=[],
        metavar="PLANE",
        help="Disable a plane. Repeatable. Default is all enabled.",
    )
    client.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write to this path (default: print to stdout).",
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
    parser.add_argument(
        "--env",
        metavar="LOCATOR",
        default=None,
        help=(
            "Python environment to auto-discover MolCrafts packages from: a "
            "virtualenv root, a python executable, or a site-packages directory "
            "(default: the current environment)."
        ),
    )


def _load(args: argparse.Namespace) -> AppConfig:
    return load_config(args.config, env_locator=args.env)


def _emit(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def _optional(values: list[str]) -> list[str] | None:
    return values or None


def _serve(args: argparse.Namespace) -> int:
    plane = args.plane.strip().lower()
    known = known_plane_ids()
    # Allow serving any discovered provider even if not in the static meta table.
    if plane not in known and plane not in {p.name for p in _discover_safe()}:
        raise ConfigurationError(
            f"unknown plane {plane!r}. Run `molmcp planes` for the catalog."
        )

    config = _load(args) if plane == "molcrafts" else None
    # Provider planes may still load config for HTTP auth settings.
    if plane not in {"catalog", "molcrafts"}:
        try:
            config = _load(args)
        except ConfigurationError:
            config = None
        except FileNotFoundError:
            config = None

    server = create_plane(
        plane,
        config=config,
        discover_entry_points=not args.no_discover,
    )
    transport = args.transport or (
        config.server.transport if config is not None else "stdio"
    )
    kwargs: dict[str, Any] = {"transport": transport}
    if transport == "stdio":
        kwargs["show_banner"] = False
        kwargs["log_level"] = "ERROR"
    else:
        host = args.host or (config.server.host if config is not None else "127.0.0.1")
        port = args.port or (config.server.port if config is not None else 8787)
        auth_env = config.server.auth_token_env if config is not None else None
        if host not in {"127.0.0.1", "::1", "localhost"} and not auth_env:
            raise ConfigurationError(
                "non-loopback streamable HTTP requires server.auth_token_env"
            )
        kwargs.update(host=host, port=port)
    server.run(**kwargs)
    return 0


def _discover_safe():
    from .provider import discover_providers

    return discover_providers()


def _planes(args: argparse.Namespace) -> int:
    planes = [p.to_dict() for p in list_plane_infos()]
    payload = {
        "ok": True,
        "model": "multi-plane-default-all",
        "planes": planes,
        "hint": (
            "Default: enable every plane in the client. "
            "molmcp client grok                  # all on\n"
            "molmcp client grok --disable molq   # all except molq\n"
            "molmcp client grok --disable molq --enable molq  # re-enable"
        ),
    }
    if args.json:
        _emit(payload)
        return 0
    print("MolCrafts MCP planes (default: all enabled in client):\n")
    for row in planes:
        print(f"  {row['id']:12}  {row['serve_command']}")
        print(f"               {row['purpose']}")
        print(f"               when: {row['when_to_connect']}")
        if row.get("tools_hint"):
            print(f"               tools: {', '.join(row['tools_hint'])}")
        print()
    print(payload["hint"])
    return 0


def _route(args: argparse.Namespace) -> int:
    _emit(route_task(args.task))
    return 0


def _client(args: argparse.Namespace) -> int:
    toggle, text = render_client(
        args.host,
        enable=args.enable,
        disable=args.disable,
    )
    if args.output is not None:
        path = args.output.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(
            f"wrote {path}  enabled={list(toggle.enabled)}  "
            f"disabled={list(toggle.disabled)}",
            file=sys.stderr,
        )
        return 0
    # stderr summary so piping stdout stays clean
    print(
        f"# enabled: {', '.join(toggle.enabled)}"
        + (f"  # disabled: {', '.join(toggle.disabled)}" if toggle.disabled else ""),
        file=sys.stderr,
    )
    sys.stdout.write(text)
    return 0


def _collection(args: argparse.Namespace):
    config = _load(args)
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
    config = _load(args)
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
        arguments = ["planes"]
    parser = _build_parser()
    args = parser.parse_args(arguments)
    handlers = {
        "serve": _serve,
        "planes": _planes,
        "route": _route,
        "client": _client,
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
