"""``molq`` MCP provider — job-store dashboard + opt-in single-job submit.

Tools are documented in :mod:`.provider`. This package layout matches
other first-party providers (``molexp``, …): a subpackage with the
class re-exported at the top level.
"""

from __future__ import annotations

from .provider import MolqProvider

__all__ = ["MolqProvider"]
