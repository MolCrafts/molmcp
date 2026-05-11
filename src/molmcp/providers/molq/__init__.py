"""``molq`` MCP provider — read-only window onto the local molq jobs DB.

The single tool ``molq_list_jobs`` is documented in :mod:`.provider`;
this module exists to keep the provider layout uniform across the
``molmcp.providers`` package (every provider is a subpackage with its
class re-exported at the top level).
"""

from .provider import MolqProvider

__all__ = ["MolqProvider"]
