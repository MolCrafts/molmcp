"""First-party MCP providers for the MolCrafts ecosystem.

Provider scope is deliberately tight: per ``docs/provider-design.md``,
a tool earns a slot only if it answers something an agent **cannot**
derive by reading the upstream package's source via
:class:`molmcp.IntrospectionProvider`. That leaves stateful queries
(local DBs, filesystem-resident workspace state) — everything else
should be discovered through introspection and called via Python /
the upstream CLI.

Currently shipped:

* :class:`MolqProvider` — queries ``~/.molq/jobs.db`` and ``~/.ssh/config``.
* :class:`MolexpProvider` — queries a ``workspace.json``-rooted molexp
  workspace catalog.

Both providers are *lazy facades* — importing them does not require
their domain dep; that probe happens at :meth:`register` time so the
user gets a clear ``RuntimeError`` (with the install command) only if
the provider is actually registered without its dep.

Third parties writing their own MCP plugins should use the
``molmcp.providers`` entry-point group; auto-discovery in
:func:`molmcp.discover_providers` is unchanged.
"""

from .molexp import MolexpProvider
from .molq import MolqProvider

__all__ = [
    "MolexpProvider",
    "MolqProvider",
]
