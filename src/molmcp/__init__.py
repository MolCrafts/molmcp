"""MolMCP — multi-plane MCP for MolCrafts (one product per connection)."""

from __future__ import annotations

from .client_config import PlaneToggle, resolve_plane_toggles
from .collection import CollectionIndex, ContextPack, SearchHit, SourceBinding
from .config import AppConfig, ConfigurationError, load_config
from .mcp_provider import MolCraftsContextProvider
from .planes import PlaneInfo, known_plane_ids, list_plane_infos, route_task
from .provider import (
    PROVIDER_ENTRY_POINT_GROUP,
    Provider,
    discover_providers,
    provider_available,
)
from .registry import (
    CAPABILITY_ENTRY_POINT_GROUP,
    CatalogItemV1,
    ExecutableCapabilityV1,
    Registry,
)
from .server import create_plane, create_server

__version__ = "0.5.0"

__all__ = [
    "CAPABILITY_ENTRY_POINT_GROUP",
    "AppConfig",
    "CatalogItemV1",
    "CollectionIndex",
    "ConfigurationError",
    "ContextPack",
    "ExecutableCapabilityV1",
    "MolCraftsContextProvider",
    "PROVIDER_ENTRY_POINT_GROUP",
    "PlaneInfo",
    "PlaneToggle",
    "Provider",
    "Registry",
    "SearchHit",
    "SourceBinding",
    "__version__",
    "create_plane",
    "create_server",
    "discover_providers",
    "known_plane_ids",
    "list_plane_infos",
    "load_config",
    "provider_available",
    "resolve_plane_toggles",
    "route_task",
]
