"""Strict project configuration for the MolMCP vNext application layer."""

from __future__ import annotations

import ipaddress
import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CONFIG_SCHEMA_VERSION = "1"
DEFAULT_CONFIG_NAME = "molcrafts.json"
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_HEADER_RE = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9._~-]* )?\$\{([A-Za-z_][A-Za-z0-9_]*)\}$"
)
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_NAMESPACE_RE = re.compile(r"^@[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
_SOURCE_NAME_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_PROVIDER_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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
class RegistrySourceConfig:
    """One installed, file-backed, or remote registry source."""

    kind: str
    location: str | None = None
    namespace: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    expected_digest: str | None = None
    search_only: bool = False

    @classmethod
    def from_dict(cls, data: object, index: int) -> RegistrySourceConfig:
        where = f"registries[{index}]"
        if not isinstance(data, dict):
            raise ConfigurationError(f"{where} must be an object")
        _reject_unknown(
            data,
            {
                "kind",
                "location",
                "namespace",
                "headers",
                "expected_digest",
                "search_only",
            },
            where,
        )
        kind = _require_string(data.get("kind"), f"{where}.kind")
        if kind not in {"installed", "file", "url"}:
            raise ConfigurationError(
                f"{where}.kind must be one of installed, file, url"
            )
        location_raw = data.get("location")
        location = (
            _require_string(location_raw, f"{where}.location")
            if location_raw is not None
            else None
        )
        if kind in {"file", "url"} and location is None:
            raise ConfigurationError(f"{where}.location is required for {kind}")
        if kind == "installed" and location is not None:
            raise ConfigurationError(f"{where}.location is forbidden for installed")
        namespace_raw = data.get("namespace")
        namespace = (
            _require_string(namespace_raw, f"{where}.namespace")
            if namespace_raw is not None
            else None
        )
        if namespace is not None and _NAMESPACE_RE.fullmatch(namespace) is None:
            raise ConfigurationError(
                f"{where}.namespace must be a valid '@namespace' reference"
            )
        headers_raw = data.get("headers", {})
        if not isinstance(headers_raw, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in headers_raw.items()
        ):
            raise ConfigurationError(f"{where}.headers must map strings to strings")
        if headers_raw and kind != "url":
            raise ConfigurationError(f"{where}.headers are only valid for url sources")
        for name, value in headers_raw.items():
            if _HEADER_NAME_RE.fullmatch(name) is None:
                raise ConfigurationError(f"{where}.headers contains invalid name")
            if _SECRET_HEADER_RE.fullmatch(value) is None:
                raise ConfigurationError(
                    f"{where}.headers.{name} must reference one environment variable"
                )
        if kind == "url" and location is not None:
            _validate_registry_url(location, where)
        digest_raw = data.get("expected_digest")
        expected_digest = (
            _require_string(digest_raw, f"{where}.expected_digest")
            if digest_raw is not None
            else None
        )
        if (
            expected_digest is not None
            and _SHA256_RE.fullmatch(expected_digest) is None
        ):
            raise ConfigurationError(
                f"{where}.expected_digest must be a lowercase SHA-256 digest"
            )
        if expected_digest is not None and kind == "installed":
            raise ConfigurationError(
                f"{where}.expected_digest is not valid for installed sources"
            )
        search_only_raw = data.get(
            "search_only", kind == "url" and expected_digest is None
        )
        if not isinstance(search_only_raw, bool):
            raise ConfigurationError(f"{where}.search_only must be a boolean")
        if kind == "url" and not search_only_raw and expected_digest is None:
            raise ConfigurationError(
                f"{where} requires expected_digest unless search_only is true"
            )
        return cls(
            kind=kind,
            location=location,
            namespace=namespace,
            headers=dict(headers_raw),
            expected_digest=expected_digest,
            search_only=search_only_raw,
        )


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
    registries: tuple[RegistrySourceConfig, ...] = ()
    providers: frozenset[str] | None = None
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
        discovery: dict[str, Any] | None = None,
    ) -> AppConfig:
        root = Path(workspace_root).expanduser().resolve()
        sources: dict[str, str] = {"workspace": str(root)}
        for name, spec in discovered:
            sources[_dedupe_source_name(name, sources)] = _resolve_source_spec(
                spec, root
            )
        return cls(workspace_root=root, sources=sources, discovery=discovery)

    @classmethod
    def from_dict(cls, data: object, *, workspace_root: str | Path) -> AppConfig:
        if not isinstance(data, dict):
            raise ConfigurationError("configuration root must be an object")
        _reject_unknown(
            data,
            {
                "schema_version",
                "sources",
                "registries",
                "providers",
                "cache_dir",
                "watch",
                "excludes",
                "server",
            },
            "configuration",
        )
        if data.get("schema_version") != CONFIG_SCHEMA_VERSION:
            raise ConfigurationError(
                f"schema_version must be {CONFIG_SCHEMA_VERSION!r}"
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

        registries_raw = data.get("registries", [])
        if not isinstance(registries_raw, list):
            raise ConfigurationError("registries must be an array")
        registries = tuple(
            _resolve_registry_source(RegistrySourceConfig.from_dict(item, index), root)
            for index, item in enumerate(registries_raw)
        )

        providers_raw = data.get("providers")
        providers: frozenset[str] | None
        if providers_raw is None:
            providers = None
        elif isinstance(providers_raw, list) and all(
            isinstance(item, str) and item.strip() for item in providers_raw
        ):
            provider_names = [item.strip() for item in providers_raw]
            if len(set(provider_names)) != len(provider_names):
                raise ConfigurationError("providers must not contain duplicates")
            invalid = [
                name
                for name in provider_names
                if _PROVIDER_NAME_RE.fullmatch(name) is None or name == "molcrafts"
            ]
            if invalid:
                raise ConfigurationError(
                    "providers contains invalid or reserved name(s): "
                    + ", ".join(sorted(invalid))
                )
            providers = frozenset(provider_names)
        else:
            raise ConfigurationError("providers must be an array of names")

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
            registries=registries,
            providers=providers,
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


def _resolve_registry_source(
    source: RegistrySourceConfig, root: Path
) -> RegistrySourceConfig:
    if source.kind != "file" or source.location is None:
        return source
    return RegistrySourceConfig(
        kind=source.kind,
        location=str(_resolve_path(source.location, root)),
        namespace=source.namespace,
        headers=source.headers,
        expected_digest=source.expected_digest,
        search_only=source.search_only,
    )


def load_config(
    path: str | Path | None = None, *, env_locator: str | None = None
) -> AppConfig:
    """Load ``molcrafts.json`` or return a current-workspace default."""
    config_path = Path(path or DEFAULT_CONFIG_NAME).expanduser()
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    if not config_path.is_file():
        if path is not None:
            raise ConfigurationError(f"configuration file not found: {config_path}")
        # Function-level import breaks the config <-> environment cycle:
        # environment.py imports ConfigurationError from this module.
        from .environment import discover_sources

        locator = (
            env_locator if env_locator is not None else os.environ.get("MOLMCP_ENV")
        )
        report = discover_sources(locator)
        return AppConfig.default(
            Path.cwd(),
            discovered=[(source.name, source.spec) for source in report.sources],
            discovery=report.to_dict(),
        )
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


def _validate_registry_url(location: str, where: str) -> None:
    parts = urlsplit(location)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ConfigurationError(
            f"{where}.location must be an HTTPS URL without credentials, query, "
            "or fragment"
        )
    remaining = location.replace("{namespace}", "")
    if "{" in remaining or "}" in remaining:
        raise ConfigurationError(
            f"{where}.location contains an unsupported URL template variable"
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ConfigurationError(f"non-finite JSON number is forbidden: {value}")
