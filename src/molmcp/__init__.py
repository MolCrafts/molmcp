"""molmcp — the MCP foundation for the MolCrafts ecosystem."""

from __future__ import annotations

from .helpers import SubprocessResult, fence_untrusted, run_safe
from .introspection import IntrospectionProvider
from .middleware import (
    MissingAnnotationsError,
    PathSafetyMiddleware,
    ResponseLimitMiddleware,
    validate_tool_annotations,
)
from .provider import ENTRY_POINT_GROUP, Provider, discover_providers
from .server import create_server

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "create_server",
    "Provider",
    "IntrospectionProvider",
    "discover_providers",
    "ENTRY_POINT_GROUP",
    "PathSafetyMiddleware",
    "ResponseLimitMiddleware",
    "MissingAnnotationsError",
    "validate_tool_annotations",
    "run_safe",
    "SubprocessResult",
    "fence_untrusted",
]
