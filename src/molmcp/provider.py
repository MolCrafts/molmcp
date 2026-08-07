"""Provider protocol — the contract for downstream MCP plugins."""

from __future__ import annotations

import importlib.metadata
import logging
import re
from typing import Protocol, runtime_checkable

from fastmcp import FastMCP

PROVIDER_ENTRY_POINT_GROUP = "molmcp.providers"
PROVIDER_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
RESERVED_PROVIDER_NAMES = frozenset({"molcrafts", "catalog"})

logger = logging.getLogger(__name__)


@runtime_checkable
class Provider(Protocol):
    """One product plane's tools, registered onto its own FastMCP server.

    Implementations must expose:

    * ``name`` — plane id and MCP server name (e.g. ``"molvis"``). Clients
      connect with ``molmcp serve <name>``; tool ids become
      ``<name>__<tool>`` at the client (e.g. ``molvis__open``).
    * ``register(mcp)`` — attach **bare** tool names only (``open``, not
      ``molvis_open``). Never mount with a namespace. Startup rejects
      ``{plane}_…`` and ``{plane}_{plane}_…`` (legacy ``molexp_molexp_*``).

    Optional:

    * ``probe()`` — return whether the optional upstream package is importable.
      Missing science deps are **silently omitted** from plane catalogs and
      client configs (not an error). Explicit ``molmcp serve <plane>`` still
      fails loudly if the user asks for an unavailable plane.

    Providers MUST set ``ToolAnnotations`` (at minimum ``read_only_hint``)
    on every tool. Startup validation rejects missing annotations.
    Use snake_case field names (MCP SDK v2 / FastMCP 4).
    """

    name: str

    def register(self, mcp: FastMCP) -> None: ...


def provider_available(provider: Provider) -> bool:
    """True if the plane's optional upstream package is importable.

    Uses ``provider.probe()`` when present; otherwise ``True``. ImportError
    and other probe failures mean *unavailable* (silent skip at catalog time).
    """
    probe = getattr(provider, "probe", None)
    if not callable(probe):
        return True
    try:
        return bool(probe())
    except Exception:
        return False


def discover_providers(
    *,
    failures: list[dict[str, str]] | None = None,
    only_available: bool = False,
) -> list[Provider]:
    """Enumerate Provider instances declared via the ``molmcp.providers`` entry point.

    Each entry point must resolve to a class; the class is instantiated with
    no arguments. Providers raising during instantiation are logged at debug
    and skipped (optional packages missing is normal).

    Args:
        failures: Optional sink for structured load failures.
        only_available: When True, drop providers whose ``probe()`` reports the
            optional upstream package is not installed (silent skip — catalogs
            and client configs use this; tests/explicit serve do not).
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
            # Optional science packages may be absent — not a hard error.
            logger.debug("Skipping Provider %r (load failed): %s", ep.name, e)
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
            logger.debug(
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
            logger.debug(
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
        if only_available and not provider_available(instance):
            logger.debug(
                "Skipping Provider %r (optional package not installed)", ep.name
            )
            if failures is not None:
                failures.append(
                    {
                        "entry_point": ep.name,
                        "phase": "probe",
                        "error_type": "Unavailable",
                    }
                )
            continue
        discovered.append(instance)
    return discovered
