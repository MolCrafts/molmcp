"""``molvis`` MCP provider — live viewer session + exec primitives.

Tools are documented in :mod:`.provider`; the MCP-free half (event
journal, REPL machinery, session registry) lives in :mod:`.session`.
This package layout matches the other first-party providers (``molq``,
``molexp``, …): a subpackage with the class re-exported at the top level.
"""

from __future__ import annotations

from .provider import MolvisProvider

__all__ = ["MolvisProvider"]
