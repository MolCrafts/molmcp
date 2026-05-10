"""``create_server`` factory — the main public entry point of molmcp."""

from __future__ import annotations

import logging
from typing import Iterable

from fastmcp import FastMCP

from .introspection import IntrospectionProvider
from .middleware import (
    MissingAnnotationsError,
    PathSafetyMiddleware,
    ResponseLimitMiddleware,
    validate_tool_annotations,
)
from .provider import Provider, discover_providers

logger = logging.getLogger(__name__)


def create_server(
    name: str = "molmcp",
    *,
    import_roots: Iterable[str] | None = None,
    providers: Iterable[Provider] | None = None,
    discover_entry_points: bool = True,
    enable_path_safety: bool = True,
    enable_response_limit: bool = True,
    response_limit_bytes: int = 256 * 1024,
    validate_annotations: bool = True,
    instructions: str | None = None,
) -> FastMCP:
    """Build a fully configured FastMCP server.

    Args:
        name: Server name advertised to MCP clients.
        import_roots: Top-level package names whose source the built-in
            :class:`IntrospectionProvider` may read. Empty/None disables it.
        providers: Explicit Provider instances to register, in order. They
            run after auto-discovered providers.
        discover_entry_points: If True, auto-discover providers via the
            ``molmcp.providers`` entry point group.
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
    mcp = FastMCP(
        name,
        instructions=instructions
        or _default_instructions(import_roots, providers, discover_entry_points),
    )

    if enable_path_safety:
        mcp.add_middleware(PathSafetyMiddleware())
    if enable_response_limit:
        mcp.add_middleware(ResponseLimitMiddleware(max_bytes=response_limit_bytes))

    roots = list(import_roots) if import_roots else []
    if roots:
        IntrospectionProvider(roots).register(mcp)

    auto: list[Provider] = list(discover_providers()) if discover_entry_points else []
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
                prov.name, type(exc).__name__, exc,
            )

    if validate_annotations:
        warnings = validate_tool_annotations(mcp, strict=False)
        if warnings:
            raise MissingAnnotationsError(
                "Tool annotation validation failed:\n  - " + "\n  - ".join(warnings)
            )

    return mcp


def _default_instructions(
    import_roots: Iterable[str] | None,
    providers: Iterable[Provider] | None,
    discover: bool,
) -> str:
    parts = ["molmcp server."]
    if import_roots:
        parts.append(
            "Source-introspection tools available for: "
            + ", ".join(import_roots)
            + "."
        )
    if providers or discover:
        parts.append("Domain tools provided by registered providers.")
    parts.append(
        "Use list_modules / list_symbols / get_source to discover the API."
    )
    return " ".join(parts)
