"""``create_server`` factory — the main public entry point of molmcp."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Iterable

from fastmcp import FastMCP

from .discovery.provider import DiscoveryProvider
from .middleware import (
    MissingAnnotationsError,
    PathSafetyMiddleware,
    ResponseLimitMiddleware,
    validate_tool_annotations,
)
from .provider import Provider, discover_providers

if TYPE_CHECKING:
    from .discovery import DiscoveryConfig

logger = logging.getLogger(__name__)


def create_server(
    name: str = "molmcp",
    *,
    discovery_sources: Iterable[str] | None = None,
    discovery_config: "DiscoveryConfig | None" = None,
    providers: Iterable[Provider] | None = None,
    discover_entry_points: bool = True,
    provider_names: set[str] | None = None,
    enable_path_safety: bool = True,
    enable_response_limit: bool = True,
    response_limit_bytes: int = 256 * 1024,
    validate_annotations: bool = True,
    instructions: str | None = None,
) -> FastMCP:
    """Build a fully configured FastMCP server.

    Args:
        name: Server name advertised to MCP clients.
        discovery_sources: Source specs the discovery engine may index —
            local paths, ``pkg:<name>`` for installed packages, or
            ``github:owner/repo[@ref]``. Empty/None disables discovery.
        discovery_config: Optional :class:`DiscoveryConfig` for the
            engine (cache directory, limits, ...).
        providers: Explicit Provider instances to register, in order.
            They run after auto-discovered providers.
        discover_entry_points: If True, auto-discover providers via the
            ``molmcp.providers`` entry point group.
        provider_names: When set, restrict auto-discovered providers to
            those whose ``name`` is in this set. ``None`` means no filter.
            Explicit ``providers=`` are never filtered.
        enable_path_safety: Mount :class:`PathSafetyMiddleware`.
        enable_response_limit: Mount :class:`ResponseLimitMiddleware`.
        response_limit_bytes: Per-response truncation threshold.
        validate_annotations: After all providers register, ensure every
            tool exposes ``readOnlyHint`` or ``destructiveHint``. Raises
            :class:`MissingAnnotationsError` on violation.
        instructions: Server-level instructions string sent to clients.

    Returns:
        Ready-to-run :class:`fastmcp.FastMCP` instance.
    """
    sources = list(discovery_sources) if discovery_sources else []

    mcp = FastMCP(
        name,
        instructions=instructions
        or _default_instructions(sources, providers, discover_entry_points),
    )

    if enable_path_safety:
        mcp.add_middleware(PathSafetyMiddleware())
    if enable_response_limit:
        mcp.add_middleware(ResponseLimitMiddleware(max_bytes=response_limit_bytes))

    if sources:
        DiscoveryProvider(sources, discovery_config).register(mcp)

    auto: list[Provider] = list(discover_providers()) if discover_entry_points else []
    if provider_names is not None:
        auto = [p for p in auto if p.name in provider_names]
    explicit: list[Provider] = list(providers) if providers else []
    seen: set[str] = set()

    for prov in auto + explicit:
        if prov.name in seen:
            logger.warning("Skipping duplicate provider %r", prov.name)
            continue
        seen.add(prov.name)
        try:
            prov.register(mcp)
        except Exception as exc:
            if prov in explicit:
                raise
            logger.warning(
                "Skipping auto-discovered provider %r: %s: %s",
                prov.name,
                type(exc).__name__,
                exc,
            )

    if validate_annotations:
        warnings = validate_tool_annotations(mcp, strict=False)
        if warnings:
            raise MissingAnnotationsError(
                "Tool annotation validation failed:\n  - " + "\n  - ".join(warnings)
            )

    return mcp


def _default_instructions(
    sources: list[str],
    providers: Iterable[Provider] | None,
    discover: bool,
) -> str:
    parts = ["molmcp server."]
    if sources:
        parts.append("Graph-indexed discovery sources: " + ", ".join(sources) + ".")
        parts.append(
            "Use molmcp_outline to see structure, molmcp_find_capability to "
            "discover capabilities, then molmcp_search_symbols / "
            "molmcp_describe_symbol / molmcp_relations to drill in. Resolve "
            "every name from a prior tool result — never guess."
        )
    if providers or discover:
        parts.append("Domain tools provided by registered providers.")
    return " ".join(parts)
