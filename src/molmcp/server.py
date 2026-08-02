"""Build the clean MolMCP vNext FastMCP server."""

from __future__ import annotations

import hmac
import logging
import os
from collections.abc import Iterable
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier

from .collection import CollectionIndex
from .config import AppConfig, load_config
from .mcp_provider import MolCraftsContextProvider
from .middleware import (
    MissingAnnotationsError,
    PathSafetyMiddleware,
    ResponseLimitMiddleware,
    validate_tool_annotations,
)
from .provider import (
    PROVIDER_NAME_PATTERN,
    RESERVED_PROVIDER_NAMES,
    Provider,
    discover_providers,
)
from .runtime import build_collection, build_registry

logger = logging.getLogger(__name__)


def create_server(
    name: str = "molmcp",
    *,
    collection: CollectionIndex | None = None,
    config: AppConfig | str | Path | None = None,
    providers: Iterable[Provider] | None = None,
    discover_entry_points: bool = True,
    provider_names: set[str] | frozenset[str] | None = None,
    enable_path_safety: bool = True,
    enable_response_limit: bool = True,
    response_limit_bytes: int = 256 * 1024,
    validate_annotations: bool = True,
    instructions: str | None = None,
) -> FastMCP:
    """Build the vNext server around a collection and namespaced providers."""
    app_config = (
        _resolve_config(config) if config is not None or collection is None else None
    )
    if collection is None:
        assert app_config is not None
        registry = build_registry(app_config)
        collection = build_collection(app_config, registry)

    auth = _environment_auth(app_config) if app_config is not None else None

    @asynccontextmanager
    async def lifespan(_server):
        collection.start()
        try:
            yield {}
        finally:
            collection.close()

    runtime_status: dict[str, object] = {
        "transport": (
            app_config.server.transport if app_config is not None else "injected"
        ),
        "providers": {
            "configured": (
                sorted(app_config.providers)
                if app_config is not None and app_config.providers is not None
                else None
            ),
            "enabled": [],
            "failed": [],
        },
    }
    mcp = FastMCP(
        name,
        instructions=instructions or _default_instructions(),
        auth=auth,
        lifespan=lifespan,
    )
    if enable_path_safety:
        mcp.add_middleware(PathSafetyMiddleware())
    if enable_response_limit:
        mcp.add_middleware(ResponseLimitMiddleware(max_bytes=response_limit_bytes))

    MolCraftsContextProvider(collection, runtime_status).register(mcp)

    allowed = provider_names
    if allowed is None and app_config is not None:
        allowed = app_config.providers
    provider_failures: list[dict[str, str]] = []
    automatic = (
        list(discover_providers(failures=provider_failures))
        if discover_entry_points
        else []
    )
    if allowed is not None:
        automatic = [provider for provider in automatic if provider.name in allowed]
    explicit = list(providers or ())
    seen: set[str] = set()
    status = runtime_status["providers"]
    assert isinstance(status, dict)
    status["failed"] = provider_failures
    for provider, is_explicit in [(provider, False) for provider in automatic] + [
        (provider, True) for provider in explicit
    ]:
        if not PROVIDER_NAME_PATTERN.fullmatch(provider.name):
            raise ValueError(
                f"provider name must match ^[a-z][a-z0-9-]*$: {provider.name!r}"
            )
        if provider.name in RESERVED_PROVIDER_NAMES:
            raise ValueError(f"reserved provider name: {provider.name}")
        if provider.name in seen:
            raise ValueError(f"duplicate provider name: {provider.name}")
        seen.add(provider.name)
        if _mount_provider(mcp, provider, explicit=is_explicit):
            enabled = status["enabled"]
            assert isinstance(enabled, list)
            enabled.append(provider.name)
        else:
            failed = status["failed"]
            assert isinstance(failed, list)
            failed.append(
                {
                    "entry_point": provider.name,
                    "phase": "register",
                    "error_type": "ProviderRegistrationError",
                }
            )

    if validate_annotations:
        warnings = validate_tool_annotations(mcp, strict=False)
        if warnings:
            raise MissingAnnotationsError(
                "Tool annotation validation failed:\n  - " + "\n  - ".join(warnings)
            )
    return mcp


def _resolve_config(config: AppConfig | str | Path | None) -> AppConfig:
    if isinstance(config, AppConfig):
        return config
    return load_config(config)


def _mount_provider(parent: FastMCP, provider: Provider, *, explicit: bool) -> bool:
    child = FastMCP(f"{provider.name}-provider", on_duplicate="error")
    try:
        provider.register(child)
    except Exception:
        if explicit:
            raise
        logger.exception(
            "Skipping provider %r after registration failure", provider.name
        )
        return False
    parent.mount(child, namespace=provider.name)
    return True


def _default_instructions() -> str:
    return (
        "MolMCP injects knowledge pages into your context (OKF-style). "
        "Codegraph is only an index — do not treat scores as truth.\n"
        "1) molcrafts_packages — read package directory summaries; choose sources\n"
        "2) molcrafts_outline(source=…, path?=) — read module directory page\n"
        "3) molcrafts_open(ref) — inject symbol page before writing code\n"
        "4) molcrafts_compose(task|refs, budget) — multi-page pack when needed\n"
        "search/suggest are index helpers only. "
        "Only executable=true may be handed to Molexp. "
        "ok=false / SYMBOL_NOT_FOUND means do not invent the API.\n"
        "Scope: when MOLMCP_SOURCES is set (comma-separated package names), "
        "packages/outline/open/search/compose are restricted to that allowlist; "
        "out-of-scope sources return SOURCE_NOT_ALLOWED — do not invent those APIs."
    )


class _EnvironmentTokenVerifier(TokenVerifier):
    """Single-secret bearer verification without logging or copying the secret."""

    def __init__(self, environment_name: str) -> None:
        super().__init__(required_scopes=["molmcp"])
        self.environment_name = environment_name

    async def verify_token(self, token: str) -> AccessToken | None:
        expected = os.environ.get(self.environment_name)
        if expected is None or not hmac.compare_digest(token, expected):
            return None
        return AccessToken(
            token=token,
            client_id="molmcp-static-client",
            scopes=["molmcp"],
            claims={"source": "environment"},
        )


def _environment_auth(config: AppConfig) -> TokenVerifier | None:
    environment_name = config.server.auth_token_env
    if environment_name is None:
        return None
    if not os.environ.get(environment_name):
        raise ValueError(
            f"configured bearer token environment variable is unset: {environment_name}"
        )
    return _EnvironmentTokenVerifier(environment_name)
