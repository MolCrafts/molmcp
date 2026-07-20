"""Application-layer assembly of registries and source collections."""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from .collection import CollectionIndex, SourceBinding
from .config import AppConfig, RegistrySourceConfig
from .discovery import DiscoveryConfig, DiscoveryEngine
from .discovery.config import DEFAULT_EXCLUDES
from .registry import (
    LoadedManifest,
    Registry,
    load_installed_manifests,
    load_manifest,
    loads_manifest,
)

_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_MAX_REMOTE_MANIFEST_BYTES = 4 * 1024 * 1024


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Prevent registry credentials from crossing redirect boundaries."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("registry URL redirects are not allowed")


def build_registry(config: AppConfig) -> Registry:
    """Build a fail-closed registry from installed and configured manifests."""
    registry = Registry()
    manifests: list[tuple[LoadedManifest, str | None, str]] = []
    installed_loaded = False
    for source in config.registries:
        if source.kind == "installed":
            manifests.extend(
                _load_installed(
                    namespace=source.namespace,
                    execution_status=("search_only" if source.search_only else "ready"),
                )
            )
            installed_loaded = True
        elif source.kind == "file":
            manifests.extend(_load_file_source(source))
        elif source.kind == "url":
            manifests.append(_registration(_load_url_manifest(source), source))
        else:  # defensive: AppConfig has already validated this
            raise ValueError(f"unsupported registry source kind: {source.kind}")
    # Installed package manifests are the normal local source of truth.  They
    # participate by default unless an explicit installed entry already did.
    if not installed_loaded:
        manifests.extend(_load_installed())
    registry.register_manifests(manifests)
    return registry


def _load_installed(
    *, namespace: str | None = None, execution_status: str = "ready"
) -> list[tuple[LoadedManifest, str | None, str]]:
    return [
        (manifest, namespace, execution_status)
        for manifest in load_installed_manifests(namespace=namespace)
    ]


def _load_file_source(
    source: RegistrySourceConfig,
) -> list[tuple[LoadedManifest, str | None, str]]:
    assert source.location is not None
    path = Path(source.location)
    if path.is_file():
        return [_registration(load_manifest(path), source)]
    if not path.is_dir():
        raise FileNotFoundError(f"registry source does not exist: {path}")
    manifests = sorted(path.rglob("molcrafts.registry.json"))
    if not manifests:
        raise FileNotFoundError(f"no molcrafts.registry.json found under {path}")
    return [
        _registration(load_manifest(manifest_path), source)
        for manifest_path in manifests
    ]


def _registration(
    manifest: LoadedManifest, source: RegistrySourceConfig
) -> tuple[LoadedManifest, str | None, str]:
    if source.expected_digest is not None and manifest.digest != source.expected_digest:
        raise ValueError("registry manifest digest does not match expected_digest")
    return (
        manifest,
        source.namespace,
        "search_only" if source.search_only else "ready",
    )


def _load_url_manifest(source: RegistrySourceConfig):
    assert source.location is not None
    location = _expand_url_template(source)
    parts = urllib.parse.urlsplit(location)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "registry URL must be an HTTPS URL without credentials, query, or fragment"
        )
    headers = {
        name: _expand_environment(value) for name, value in source.headers.items()
    }
    request = urllib.request.Request(location, headers=headers)
    opener = urllib.request.build_opener(_RejectRedirects())
    with opener.open(request, timeout=15) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"application/json", "text/json", "text/plain"}:
            raise ValueError(
                f"registry URL returned unsupported content type: {content_type}"
            )
        raw = response.read(_MAX_REMOTE_MANIFEST_BYTES + 1)
    if len(raw) > _MAX_REMOTE_MANIFEST_BYTES:
        raise ValueError("registry manifest exceeds 4 MiB")
    return loads_manifest(raw, source=location)


def _expand_url_template(source: RegistrySourceConfig) -> str:
    assert source.location is not None
    location = source.location
    if "{namespace}" in location:
        if source.namespace is None:
            raise ValueError("registry URL template requires a namespace mapping")
        encoded = urllib.parse.quote(source.namespace.removeprefix("@"), safe="")
        location = location.replace("{namespace}", encoded)
    if "{" in location or "}" in location:
        raise ValueError("registry URL contains an unsupported template variable")
    return location


def _expand_environment(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        resolved = os.environ.get(name)
        if resolved is None:
            raise ValueError(
                f"registry credential environment variable is unset: {name}"
            )
        return resolved

    expanded = _ENV_REFERENCE.sub(replace, value)
    if "${" in expanded:
        raise ValueError("invalid environment reference in registry header")
    return expanded


def build_collection(
    config: AppConfig, registry: Registry | None = None
) -> CollectionIndex:
    """Build one collection over every named source in ``config``."""
    discovery = DiscoveryConfig(
        cache_dir=config.cache_dir or DiscoveryConfig().cache_dir,
        excludes=tuple(dict.fromkeys((*DEFAULT_EXCLUDES, *config.excludes))),
        watch=config.watch,
    )
    engine = DiscoveryEngine(discovery)
    bindings = [
        SourceBinding(
            name=name,
            spec=spec,
            engine=engine,
            namespace=name,
            metadata={"configured": True},
        )
        for name, spec in sorted(config.sources.items())
    ]
    return CollectionIndex(
        bindings,
        registry if registry is not None else build_registry(config),
        metadata={
            "workspace_root": str(config.workspace_root),
            "watch": config.watch,
            "configured_providers": (
                sorted(config.providers) if config.providers is not None else None
            ),
            "discovery": config.discovery,
        },
    )


def config_summary(config: AppConfig) -> str:
    """Stable, secret-free configuration text for diagnostics."""
    return json.dumps(
        {
            "workspace_root": str(config.workspace_root),
            "sources": config.sources,
            "registry_count": len(config.registries),
            "providers": sorted(config.providers) if config.providers else None,
            "watch": config.watch,
            "transport": config.server.transport,
            "discovery": config.discovery,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
