"""Strict project configuration for the MolMCP vNext application layer."""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .settings import Settings, load_settings

CONFIG_SCHEMA_VERSION = "2"
DEFAULT_CONFIG_NAME = "molcrafts.json"
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SOURCE_NAME_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


class ConfigurationError(ValueError):
    """Raised when ``molcrafts.json`` is invalid or unsafe."""


def _reject_unknown(data: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigurationError(f"unknown field(s) in {where}: {', '.join(unknown)}")


def _require_string(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{where} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """Transport settings, including the remote-listen safety gate."""

    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8787
    auth_token_env: str | None = None

    @classmethod
    def from_dict(cls, data: object) -> ServerConfig:
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise ConfigurationError("server must be an object")
        _reject_unknown(data, {"transport", "host", "port", "auth_token_env"}, "server")
        transport = data.get("transport", "stdio")
        if transport not in {"stdio", "streamable-http"}:
            raise ConfigurationError(
                "server.transport must be stdio or streamable-http"
            )
        host = _require_string(data.get("host", "127.0.0.1"), "server.host")
        port = data.get("port", 8787)
        valid_port = (
            isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535
        )
        if not valid_port:
            raise ConfigurationError("server.port must be an integer in 1..65535")
        token_raw = data.get("auth_token_env")
        token = (
            _require_string(token_raw, "server.auth_token_env")
            if token_raw is not None
            else None
        )
        if token is not None and _ENV_NAME_RE.fullmatch(token) is None:
            raise ConfigurationError(
                "server.auth_token_env must be an environment variable name"
            )
        config = cls(transport=transport, host=host, port=port, auth_token_env=token)
        config.validate_remote_policy()
        return config

    def validate_remote_policy(self) -> None:
        if self.transport == "stdio" or _is_loopback(self.host):
            return
        if self.auth_token_env is None:
            raise ConfigurationError(
                "non-loopback streamable HTTP requires server.auth_token_env"
            )


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Resolved MolMCP application configuration."""

    workspace_root: Path
    sources: dict[str, str]
    cache_dir: Path | None = None
    watch: bool = True
    excludes: tuple[str, ...] = ()
    server: ServerConfig = field(default_factory=ServerConfig)
    discovery: dict[str, Any] | None = None

    @classmethod
    def default(
        cls,
        workspace_root: str | Path,
        *,
        discovered: Iterable[tuple[str, str]] = (),
        settings: Settings | None = None,
        discovery: dict[str, Any] | None = None,
    ) -> AppConfig:
        """Resolve the sources to index when nothing was passed explicitly.

        The working directory is **not** one of them. It used to be, which
        made "what does molmcp index" depend on wherever the MCP client
        happened to launch the server: one install had accumulated two
        unrelated repositories, /private/tmp, and a monorepo root this way.
        Set ``indexWorkspace`` to opt back in per project.

        Precedence, lowest first: the workspace opt-in, auto-discovered
        MolCrafts distributions, then sources named in settings.
        """
        root = Path(workspace_root).expanduser().resolve()
        resolved_settings = settings if settings is not None else Settings()
        sources: dict[str, str] = {}
        if resolved_settings.index_workspace:
            sources["workspace"] = str(root)
        # One distribution can be found twice on sys.path (a project venv
        # plus a monorepo one). Both entries resolve to the same spec, so
        # keeping both means indexing and searching it twice per query.
        seen_specs = set(sources.values())
        for name, spec in discovered:
            resolved = _resolve_source_spec(spec, root)
            if resolved in seen_specs:
                continue
            seen_specs.add(resolved)
            sources[_dedupe_source_name(name, sources)] = resolved
        for name, spec in resolved_settings.sources.items():
            sources[name] = _resolve_source_spec(spec, root)
        cache_dir = (
            _resolve_path(resolved_settings.cache_dir, root)
            if resolved_settings.cache_dir
            else None
        )
        return cls(
            workspace_root=root,
            sources=sources,
            cache_dir=cache_dir,
            watch=resolved_settings.watch,
            excludes=resolved_settings.excludes,
            discovery=discovery,
        )

    @classmethod
    def from_dict(cls, data: object, *, workspace_root: str | Path) -> AppConfig:
        if not isinstance(data, dict):
            raise ConfigurationError("configuration root must be an object")
        _reject_unknown(
            data,
            {
                "schema_version",
                "sources",
                "cache_dir",
                "watch",
                "excludes",
                "server",
            },
            "configuration",
        )
        if data.get("schema_version") != CONFIG_SCHEMA_VERSION:
            raise ConfigurationError(
                f"schema_version must be {CONFIG_SCHEMA_VERSION!r} "
                "(v1 mega-server config is not supported; see molmcp planes)"
            )
        root = Path(workspace_root).expanduser().resolve()
        sources_raw = data.get("sources", {"workspace": str(root)})
        if not isinstance(sources_raw, dict) or not sources_raw:
            raise ConfigurationError("sources must be a non-empty object")
        sources: dict[str, str] = {}
        for raw_name, raw_spec in sources_raw.items():
            name = _require_string(raw_name, "source name")
            if _SOURCE_NAME_RE.fullmatch(name) is None:
                raise ConfigurationError(
                    "source names must start with lowercase ASCII and contain only "
                    "lowercase letters, digits, '.', '_' or '-'"
                )
            if name in sources:
                raise ConfigurationError(f"duplicate source name: {name}")
            spec = _require_string(raw_spec, f"sources.{name}")
            sources[name] = _resolve_source_spec(spec, root)

        cache_raw = data.get("cache_dir")
        cache_dir = (
            _resolve_path(_require_string(cache_raw, "cache_dir"), root)
            if cache_raw is not None
            else None
        )
        watch = data.get("watch", True)
        if not isinstance(watch, bool):
            raise ConfigurationError("watch must be a boolean")
        excludes_raw = data.get("excludes", [])
        if not isinstance(excludes_raw, list) or not all(
            isinstance(item, str) and item for item in excludes_raw
        ):
            raise ConfigurationError("excludes must be an array of strings")
        return cls(
            workspace_root=root,
            sources=sources,
            cache_dir=cache_dir,
            watch=watch,
            excludes=tuple(excludes_raw),
            server=ServerConfig.from_dict(data.get("server")),
        )


def _resolve_path(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def _resolve_source_spec(spec: str, root: Path) -> str:
    if spec.startswith(("pkg:", "github:", "local:")):
        return spec
    return str(_resolve_path(spec, root))


def _dedupe_source_name(name: str, taken: dict[str, str]) -> str:
    """Return ``name`` or the minimal ``name-2``/``name-3``/... free of collisions."""
    if name not in taken:
        return name
    suffix = 2
    while f"{name}-{suffix}" in taken:
        suffix += 1
    return f"{name}-{suffix}"


def load_config(
    path: str | Path | None = None, *, env_locator: str | None = None
) -> AppConfig:
    """Resolve configuration from settings, or from an explicit file.

    Scope is owned by ``~/.molmcp/settings.json`` and ``molmcp config``.
    A ``molcrafts.json`` sitting in the working directory is **not** picked
    up any more — auto-loading it reintroduced exactly the cwd dependence
    that made an unconfigured install index the world. Passing ``path``
    explicitly still works.
    """
    if path is None:
        # Function-level import breaks the config <-> environment cycle:
        # environment.py imports ConfigurationError from this module.
        from .environment import discover_sources

        resolved = load_settings(Path.cwd())
        locator = env_locator if env_locator is not None else resolved.python_env
        report = discover_sources(
            locator,
            include=resolved.discover_include,
            exclude=resolved.discover_exclude,
        )
        return AppConfig.default(
            Path.cwd(),
            discovered=[(source.name, source.spec) for source in report.sources],
            settings=resolved,
            discovery=report.to_dict(),
        )
    config_path = Path(path).expanduser()
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    if not config_path.is_file():
        raise ConfigurationError(f"configuration file not found: {config_path}")
    try:
        data = json.loads(
            config_path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except ConfigurationError:
        raise
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"invalid JSON in {config_path}: {exc}") from exc
    return AppConfig.from_dict(data, workspace_root=config_path.parent)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ConfigurationError(f"non-finite JSON number is forbidden: {value}")
