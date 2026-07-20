"""Provider protocol — the contract for downstream MCP plugins."""

from __future__ import annotations

import importlib.metadata
import logging
import re
from typing import Protocol, runtime_checkable

from fastmcp import FastMCP

PROVIDER_ENTRY_POINT_GROUP = "molmcp.providers"
PROVIDER_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
RESERVED_PROVIDER_NAMES = frozenset({"molcrafts"})

logger = logging.getLogger(__name__)


@runtime_checkable
class Provider(Protocol):
    """A unit of MCP functionality that can be registered onto a FastMCP server.

    Implementations must expose:

    * ``name`` — short identifier used as the mount prefix (e.g. ``"molpy"``).
      Tools registered by the provider become ``<name>_<tool>`` to avoid
      collisions across providers.
    * ``register(mcp)`` — called once at server-build time. The provider
      should attach tools, resources, and prompts to ``mcp``.

    Providers SHOULD set ``ToolAnnotations`` (at minimum ``readOnlyHint``)
    on every tool. The default :class:`AnnotationsValidator` middleware
    will reject the server at startup otherwise.
    """

    name: str

    def register(self, mcp: FastMCP) -> None: ...


def discover_providers(
    *, failures: list[dict[str, str]] | None = None
) -> list[Provider]:
    """Enumerate Provider instances declared via the ``molmcp.providers`` entry point.

    Each entry point must resolve to a class; the class is instantiated with
    no arguments. Providers raising during instantiation are logged and skipped.
    """
    discovered: list[Provider] = []
    try:
        eps = importlib.metadata.entry_points(group=PROVIDER_ENTRY_POINT_GROUP)
    except TypeError:
        eps = importlib.metadata.entry_points().get(  # type: ignore[attr-defined]
            PROVIDER_ENTRY_POINT_GROUP, []
        )

    for ep in eps:
        try:
            cls = ep.load()
            instance = cls()
        except Exception as e:
            logger.warning("Failed to load Provider %r: %s", ep.name, e)
            if failures is not None:
                failures.append(
                    {
                        "entry_point": ep.name,
                        "phase": "load",
                        "error_type": type(e).__name__,
                    }
                )
            continue
        if not isinstance(instance, Provider):
            logger.warning(
                "Entry point %r resolved to %r which does not implement Provider",
                ep.name,
                type(instance).__name__,
            )
            if failures is not None:
                failures.append(
                    {
                        "entry_point": ep.name,
                        "phase": "contract",
                        "error_type": "InvalidProvider",
                    }
                )
            continue
        if instance.name != ep.name:
            logger.warning(
                "Entry point %r resolved to provider namespace %r; skipping",
                ep.name,
                instance.name,
            )
            if failures is not None:
                failures.append(
                    {
                        "entry_point": ep.name,
                        "phase": "authority",
                        "error_type": "NamespaceMismatch",
                    }
                )
            continue
        discovered.append(instance)
    return discovered
