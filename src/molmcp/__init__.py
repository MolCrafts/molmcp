"""MolMCP — MolCrafts registry, code intelligence, and LLM context plane."""

from __future__ import annotations

from .collection import CollectionIndex, ContextPack, SearchHit, SourceBinding
from .config import AppConfig, ConfigurationError, load_config
from .mcp_provider import MolCraftsContextProvider
from .provider import PROVIDER_ENTRY_POINT_GROUP, Provider, discover_providers
from .registry import (
    CAPABILITY_ENTRY_POINT_GROUP,
    CatalogItemV1,
    ExecutableCapabilityV1,
    Registry,
)
from .server import create_server

__version__ = "0.3.0"

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
    "Provider",
    "Registry",
    "SearchHit",
    "SourceBinding",
    "__version__",
    "create_server",
    "discover_providers",
    "load_config",
]
