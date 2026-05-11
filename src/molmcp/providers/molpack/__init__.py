"""``molpack`` MCP provider — read-only packing-script inspector.

The three tools ``list_restraints``, ``list_formats``, and
``inspect_script`` are documented in :mod:`.provider`; this module
exists to keep the provider layout uniform across the
``molmcp.providers`` package (every provider is a subpackage with its
class re-exported at the top level).
"""

from .provider import MolpackProvider

__all__ = ["MolpackProvider"]
