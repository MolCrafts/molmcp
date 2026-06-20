"""``molrs`` MCP provider — read-only compute / I-O catalog + structure inspector.

The five tools ``list_compute_ops``, ``list_neighbor_algos``,
``list_readers``, ``list_writers``, and ``inspect_structure`` are
documented in :mod:`.provider`; this module exists to keep the provider
layout uniform across the ``molmcp.providers`` package (every provider
is a subpackage with its class re-exported at the top level).
"""

from .provider import MolrsProvider

__all__ = ["MolrsProvider"]
