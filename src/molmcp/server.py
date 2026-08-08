"""Build one MCP plane server — never a multi-provider mega-server."""

from __future__ import annotations

import hmac
import logging
import os
from collections.abc import Iterable
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
from mcp.types import ToolAnnotations

from .collection import CollectionIndex
from .config import AppConfig, load_config
from .mcp_provider import MolCraftsContextProvider
from .middleware import (
    MissingAnnotationsError,
    PathSafetyMiddleware,
    ResponseLimitMiddleware,
    assert_plane_tool_names,
    validate_tool_annotations,
)
from .planes import list_plane_infos, route_task
from .provider import (
    PROVIDER_NAME_PATTERN,
    Provider,
    discover_providers,
)
from .runtime import build_collection

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def create_plane(
    plane: str,
    *,
    collection: CollectionIndex | None = None,
    config: AppConfig | str | Path | None = None,
    provider: Provider | None = None,
    providers: Iterable[Provider] | None = None,
    discover_entry_points: bool = True,
    enable_path_safety: bool = True,
    enable_response_limit: bool = True,
    response_limit_bytes: int = 256 * 1024,
    validate_annotations: bool = True,
    instructions: str | None = None,
) -> FastMCP:
    """Build a **single-plane** FastMCP server.

    Args:
        plane: Plane id (``catalog``, ``molcrafts``, or a provider name such
            as ``molvis``). This becomes the MCP server name clients see.
        collection: Injected discovery collection (tests / embedding).
            Required only for ``molcrafts`` when *config* is not used.
        config: ``molcrafts.json`` or :class:`AppConfig`. Used by ``molcrafts``
            for indexing; ignored by pure provider planes unless *collection*
            is built from it.
        provider: Explicit provider instance for provider planes (tests).
        providers: Deprecated alias for a single-item explicit provider list;
            if more than one is passed, raises — multi-provider servers are gone.
        discover_entry_points: Load the matching ``molmcp.providers`` entry
            point when *provider* is not injected.
        enable_path_safety / enable_response_limit / response_limit_bytes:
            Middleware toggles.
        validate_annotations: Fail startup if tools lack ToolAnnotations.
        instructions: Override default plane instructions string.

    Raises:
        ValueError: Unknown plane, multi-provider request, or name contract
            violation.
    """
    plane_id = plane.strip().lower()
    if not plane_id:
        raise ValueError("plane id must be non-empty")

    if providers is not None:
        explicit_list = list(providers)
        if len(explicit_list) > 1:
            raise ValueError(
                "multi-provider servers are removed; serve one plane per process"
            )
        if provider is not None and explicit_list:
            raise ValueError("pass provider= or providers=[one], not both")
        if explicit_list:
            provider = explicit_list[0]

    if plane_id == "catalog":
        mcp = _base_server(
            plane_id,
            instructions=instructions or _catalog_instructions(),
            auth=None,
            lifespan=None,
            enable_path_safety=enable_path_safety,
            enable_response_limit=enable_response_limit,
            response_limit_bytes=response_limit_bytes,
        )
        _register_catalog(mcp)
        _validate(mcp, validate_annotations, plane_id=plane_id)
        return mcp

    if plane_id == "molcrafts":
        app_config, coll = _resolve_collection(collection, config)
        auth = _environment_auth(app_config) if app_config is not None else None

        @asynccontextmanager
        async def lifespan(_server):
            coll.start()
            try:
                yield {}
            finally:
                coll.close()

        runtime_status: dict[str, object] = {
            "plane": plane_id,
            "transport": (
                app_config.server.transport if app_config is not None else "injected"
            ),
        }
        mcp = _base_server(
            plane_id,
            instructions=instructions or _molcrafts_instructions(),
            auth=auth,
            lifespan=lifespan,
            enable_path_safety=enable_path_safety,
            enable_response_limit=enable_response_limit,
            response_limit_bytes=response_limit_bytes,
        )
        MolCraftsContextProvider(coll, runtime_status).register(mcp)
        _validate(mcp, validate_annotations, plane_id=plane_id)
        return mcp

    # Provider plane — one product, bare tool names, server name = plane id.
    resolved = _resolve_provider(
        plane_id,
        provider=provider,
        discover_entry_points=discover_entry_points,
    )
    app_config = None
    if config is not None:
        app_config = _resolve_config(config)
    auth = _environment_auth(app_config) if app_config is not None else None

    mcp = _base_server(
        plane_id,
        instructions=instructions or _provider_instructions(plane_id),
        auth=auth,
        lifespan=None,
        enable_path_safety=enable_path_safety,
        enable_response_limit=enable_response_limit,
        response_limit_bytes=response_limit_bytes,
    )
    try:
        resolved.register(mcp)
    except Exception:
        logger.exception("Provider plane %r failed to register", plane_id)
        raise
    _validate(mcp, validate_annotations, plane_id=plane_id)
    return mcp


def create_server(
    name: str | None = None,
    *,
    plane: str | None = None,
    **kwargs,
) -> FastMCP:
    """Compatibility wrapper: prefer :func:`create_plane`.

    ``name`` is accepted only as an alias for ``plane`` (historical tests).
    Multi-provider mounting is not supported.
    """
    plane_id = plane or name
    if plane_id is None:
        raise ValueError("create_plane requires plane= (or legacy name=)")
    # Strip kwargs that only applied to the mega-server.
    kwargs.pop("provider_names", None)
    return create_plane(plane_id, **kwargs)


def _base_server(
    name: str,
    *,
    instructions: str,
    auth: TokenVerifier | None,
    lifespan,
    enable_path_safety: bool,
    enable_response_limit: bool,
    response_limit_bytes: int,
) -> FastMCP:
    mcp_kwargs: dict = {"instructions": instructions, "auth": auth}
    if lifespan is not None:
        mcp_kwargs["lifespan"] = lifespan
    mcp = FastMCP(name, **mcp_kwargs)
    if enable_path_safety:
        mcp.add_middleware(PathSafetyMiddleware())
    if enable_response_limit:
        mcp.add_middleware(ResponseLimitMiddleware(max_bytes=response_limit_bytes))
    return mcp


def _register_catalog(mcp: FastMCP) -> None:
    @mcp.tool(annotations=_READ_ONLY)
    def list_planes() -> dict[str, object]:
        """List MCP planes this install can serve (connect only what you need).

        Each row has ``id``, ``serve_command``, ``when_to_connect``, and
        ``tools_hint``. There is no mega-server — one process per plane.
        """
        planes = [p.to_dict() for p in list_plane_infos()]
        return {
            "ok": True,
            "planes": planes,
            "model": "multi-link-on-demand",
            "hint": (
                "Configure separate MCP server entries per plane. "
                "Start with catalog + the planes route() returns."
            ),
        }

    @mcp.tool(annotations=_READ_ONLY)
    def route(task: str) -> dict[str, object]:
        """Which plane(s) to connect for *task* (routing only — no science).

        Returns plane ids and ``molmcp serve <id>`` commands. Connect those
        MCP links on demand; do not invent domain MCP tools for chemistry APIs.
        """
        return route_task(task)


def _resolve_collection(
    collection: CollectionIndex | None,
    config: AppConfig | str | Path | None,
) -> tuple[AppConfig | None, CollectionIndex]:
    if collection is not None:
        app_config = _resolve_config(config) if config is not None else None
        return app_config, collection
    app_config = _resolve_config(config)
    return app_config, build_collection(app_config)


def _resolve_provider(
    plane_id: str,
    *,
    provider: Provider | None,
    discover_entry_points: bool,
) -> Provider:
    if provider is not None:
        if provider.name != plane_id:
            raise ValueError(
                f"provider.name {provider.name!r} does not match plane {plane_id!r}"
            )
        if not PROVIDER_NAME_PATTERN.fullmatch(provider.name):
            raise ValueError(
                f"provider name must match ^[a-z][a-z0-9-]*$: {provider.name!r}"
            )
        return provider
    if not discover_entry_points:
        raise ValueError(
            f"provider plane {plane_id!r} requires provider= when "
            "discover_entry_points=False"
        )
    failures: list[dict[str, str]] = []
    found = {p.name: p for p in discover_providers(failures=failures)}
    if plane_id not in found:
        available = ", ".join(sorted(found)) or "(none)"
        detail = ""
        if failures:
            detail = "; load failures: " + ", ".join(
                f"{f.get('entry_point')}:{f.get('error_type')}" for f in failures
            )
        raise ValueError(
            f"unknown provider plane {plane_id!r}; available: {available}{detail}"
        )
    return found[plane_id]


def _resolve_config(config: AppConfig | str | Path | None) -> AppConfig:
    if isinstance(config, AppConfig):
        return config
    return load_config(config)


def _validate(
    mcp: FastMCP,
    validate_annotations: bool,
    *,
    plane_id: str,
) -> None:
    # Always enforce bare tool names (no molexp_molexp_* / plane_tool prefix).
    assert_plane_tool_names(mcp, plane_id)
    if not validate_annotations:
        return
    warnings = validate_tool_annotations(mcp, strict=False)
    if warnings:
        raise MissingAnnotationsError(
            "Tool annotation validation failed:\n  - " + "\n  - ".join(warnings)
        )


def _catalog_instructions() -> str:
    return (
        "MolCrafts MCP catalog plane — multi-link on-demand bootstrap.\n"
        "1) list_planes — which product planes exist and how to serve them\n"
        "2) route(task) — which plane(s) to connect for a user task\n"
        "Connect only those MCP servers. Science APIs are never tools here; "
        "use the molcrafts plane to discover symbols, molvis to draw, etc."
    )


def _molcrafts_instructions() -> str:
    return (
        "MolCrafts knowledge plane (OKF-style pages). "
        "Codegraph is an index — do not treat scores as truth.\n"
        "1) packages — package directory; choose sources\n"
        "2) outline(source, path?) — module tree\n"
        "3) open(ref) — symbol page before coding\n"
        "4) compose(task|refs) — budgeted multi-page pack\n"
        "search/suggest are index helpers. "
        "ok=false / SYMBOL_NOT_FOUND → do not invent the API.\n"
        "knowledgeScope scopes packages/outline/open/search/compose."
    )


def _provider_instructions(plane_id: str) -> str:
    return (
        f"MolCrafts '{plane_id}' plane — one product, one MCP connection.\n"
        "Tools are session/runtime primitives only. "
        "Do not expect science methods as MCP tools; discover them on the "
        "molcrafts plane and invoke via agent Python or molvis exec.\n"
        f"Server name is '{plane_id}' so client tool ids look like "
        f"'{plane_id}__<tool>'."
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


__all__ = ["create_plane", "create_server"]
