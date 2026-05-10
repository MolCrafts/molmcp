"""``molq`` MCP provider — read-only window onto the local molq jobs DB.

Per ``docs/concepts/provider-design.md``, a tool earns a slot only when
the answer depends on runtime state introspection cannot see *and* the
tool is read-only / idempotent. That leaves exactly one molq query: the
local jobs database. Submission, cancellation, and cleanup are mutating
verbs better served by the ``molq`` CLI itself — agents can invoke the
CLI through their own shell tool.

The provider exposes one tool:

* ``molq_list_jobs`` — list job records from the local store, with
  optional cluster and terminal-state filters.

DB resolution (in order):

1. The ``db_path`` argument passed to the constructor.
2. The ``MOLQ_DB_PATH`` environment variable.
3. molq's default (``~/.molq/jobs.db``).

Heavy molq imports stay inside :meth:`register` and tool bodies so the
provider remains cheap to instantiate.
"""

from __future__ import annotations

import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP


_DB_ENV_VAR = "MOLQ_DB_PATH"


def _serialize(value: Any) -> Any:
    """Best-effort JSON-friendly conversion for molq frozen dataclasses."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {k: _serialize(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int)):
        return enum_value
    return str(value)


def _resolve_db_path(arg: str | Path | None) -> Path | str | None:
    if arg == ":memory:":
        return ":memory:"
    if arg is not None:
        return Path(arg).expanduser()
    env = os.environ.get(_DB_ENV_VAR)
    if env:
        return Path(env).expanduser()
    return None


class MolqProvider:
    """Read-only provider for the molq local jobs database.

    Args:
        db_path: Override for ``~/.molq/jobs.db``. ``":memory:"`` is honored
            for testing.
    """

    name = "molq"

    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
    ) -> None:
        self._db_path_arg = db_path

    def _open_store(self) -> Any:
        from molq.store import JobStore

        db_path = _resolve_db_path(self._db_path_arg)
        return JobStore(db_path=db_path) if db_path is not None else JobStore()

    def register(self, mcp: "FastMCP") -> None:
        try:
            import molq  # noqa: F401 — eager probe; surface the missing dep
        except ImportError as exc:
            raise RuntimeError(
                "MolqProvider requires the 'molcrafts-molq' package. "
                "Install with: pip install molcrafts-molq"
            ) from exc

        from mcp.types import ToolAnnotations

        read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
        provider = self

        @mcp.tool(annotations=read_only)
        def molq_list_jobs(
            cluster_name: str | None = None,
            include_terminal: bool = False,
            limit: int = 200,
        ) -> list[dict[str, Any]]:
            """List job records from the local molq DB.

            Args:
                cluster_name: Restrict to one cluster. ``None`` returns
                    jobs across all clusters in the DB.
                include_terminal: Include terminal states (``succeeded``
                    / ``failed`` / ``cancelled`` / ``timed_out`` /
                    ``lost``). Defaults to ``False``.
                limit: Maximum rows returned (only honored when
                    ``cluster_name`` is ``None``; molq's per-cluster
                    listing has no limit).

            Returns:
                A list of serialized :class:`molq.JobRecord` dicts.
            """
            store = provider._open_store()
            try:
                if cluster_name is not None:
                    records = store.list_records(
                        cluster_name, include_terminal=include_terminal
                    )
                else:
                    records = store.list_all_records(
                        include_terminal=include_terminal, limit=limit
                    )
            finally:
                close = getattr(store, "close", None)
                if callable(close):
                    close()
            return [_serialize(r) for r in records]
