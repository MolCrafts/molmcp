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
* :class:`LammpsProvider` — knowledge navigator over docs.lammps.org
  (alias tables, howto registry, script linter, error matcher). LAMMPS
  is a C++ binary with a DSL, so introspection cannot reach it; the
  navigator stays pure-function over in-memory tables.
* :class:`MolpyProvider` — runtime-discovered catalog over
  ``molpy.compute`` / ``molpy.io`` plus a structure-file reader
  executor. Catalog entries are walked from live module contents at
  call-time — no hardcoded class lists.
* :class:`MolpackProvider` — runtime-discovered restraint catalog plus
  a ``.inp`` script-execution shim around ``molpack.load_script``.

All providers are *lazy facades* — importing them does not require
their domain dep (where one exists); that probe happens at
:meth:`register` time so the user gets a clear ``RuntimeError`` (with
the install command) only if the provider is actually registered
without its dep.

Third parties writing their own MCP plugins should use the
``molmcp.providers`` entry-point group; auto-discovery in
:func:`molmcp.discover_providers` is unchanged.
"""

from .lammps import LammpsProvider
from .molexp import MolexpProvider
from .molpack import MolpackProvider
from .molpy import MolpyProvider
from .molq import MolqProvider

__all__ = [
    "LammpsProvider",
    "MolexpProvider",
    "MolpackProvider",
    "MolpyProvider",
    "MolqProvider",
]
