"""``molpy`` MCP provider — read-only structure-file + compute-catalog inspector.

The three tools ``list_readers``, ``list_compute_ops``, and
``inspect_structure`` are documented in :mod:`.provider`; this module
exists to keep the provider layout uniform across the
``molmcp.providers`` package (every provider is a subpackage with its
class re-exported at the top level).
"""

from .provider import MolpyProvider

__all__ = ["MolpyProvider"]
