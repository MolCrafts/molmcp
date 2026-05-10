"""``molexp`` MCP provider — minimal stateful queries over a molexp workspace.

Scope is deliberately narrow: anything an agent could derive by reading
``molexp``'s source via :class:`molmcp.IntrospectionProvider` does **not**
belong here. This provider exists only because the agent cannot read the
runtime contents of ``workspace.json`` and the catalog DB from source.
Per ``docs/provider-design.md``, a tool earns a slot only if all four
conditions hold (stable signature, read-only, every-session frequency,
single-shot answer).

Tools:

* ``molexp_list_projects`` — top-level navigation.
* ``molexp_list_runs`` — query runs by scope, joining catalog rows
  with per-run parameters.

Everything else (``list_experiments``, ``get_run``, ``get_metrics``,
``get_asset_text``) was deliberately dropped — agents that need those
should introspect ``molexp`` and read run dirs / call APIs directly.

Workspace resolution (in order):

1. The ``workspace`` argument passed to the constructor.
2. The ``MOLEXP_WORKSPACE`` environment variable.
3. The current working directory if it contains ``workspace.json``.

Heavy molexp imports stay inside :meth:`register` and tool bodies so the
provider remains cheap to instantiate (e.g. for ``--print-config``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from molexp.workspace import Workspace


_ALLOWED_SCOPES = {"workspace", "project", "experiment"}
_WORKSPACE_ENV_VAR = "MOLEXP_WORKSPACE"


def _open_workspace(path: str | Path) -> Workspace:
    from molexp.workspace import Workspace

    resolved = Path(path).resolve()
    return Workspace(root=resolved)


def _coerce_status(value: Any) -> str:
    return str(value) if value is not None else ""


def _project_for_experiment(
    workspace: Workspace, experiment_id: str | None
) -> str | None:
    """Resolve project_id for an experiment via the workspace catalog."""
    if not experiment_id:
        return None
    catalog_data = workspace.catalog._load()  # noqa: SLF001 — read-only join
    experiments = catalog_data.get("experiments") or {}
    entry = experiments.get(experiment_id)
    if isinstance(entry, dict):
        return entry.get("project_id")
    return None


def _enriched_run_row(
    workspace: Workspace, entry: dict[str, Any]
) -> dict[str, Any]:
    """Catalog row + on-disk parameters as a single flat dict.

    Run catalog rows store ``experiment_id`` but not ``project_id``;
    we resolve the latter via the experiments section.
    """
    parameters: dict[str, Any] = dict(entry.get("parameters") or {})
    experiment_id = entry.get("experiment_id")
    run_id = entry.get("run_id")
    project_id = entry.get("project_id") or _project_for_experiment(
        workspace, experiment_id
    )
    if not parameters and project_id and experiment_id and run_id:
        project = workspace.get_project(project_id)
        if project is not None:
            experiment = project.get_experiment(experiment_id)
            if experiment is not None:
                run = experiment.get_run(run_id)
                if run is not None:
                    parameters = dict(getattr(run, "parameters", {}) or {})
    return {
        "run_id": run_id,
        "project_id": project_id,
        "experiment_id": experiment_id,
        "status": _coerce_status(entry.get("status")),
        "parameters": parameters,
        "created_at": entry.get("created_at"),
        "finished_at": entry.get("finished_at"),
        "config_hash": entry.get("config_hash"),
    }


class MolexpProvider:
    """Provider for molexp domain tools.

    Args:
        workspace: Workspace handle, path-like, or ``None`` to defer
            resolution until :meth:`register` runs (uses
            ``MOLEXP_WORKSPACE`` or CWD).
    """

    name = "molexp"

    def __init__(
        self,
        workspace: "Workspace | str | Path | None" = None,
    ) -> None:
        self._workspace_arg = workspace
        self._cached_workspace: Workspace | None = None

    def _get_workspace(self) -> Workspace:
        if self._cached_workspace is None:
            self._cached_workspace = self._resolve_workspace()
        return self._cached_workspace

    def _resolve_workspace(self) -> Workspace:
        from molexp.workspace import Workspace

        arg = self._workspace_arg
        if isinstance(arg, Workspace):
            return arg
        if arg is not None:
            return _open_workspace(arg)

        env_path = os.environ.get(_WORKSPACE_ENV_VAR)
        if env_path:
            return _open_workspace(env_path)

        cwd = Path.cwd()
        if (cwd / "workspace.json").is_file():
            return _open_workspace(cwd)

        raise RuntimeError(
            "MolexpProvider could not resolve a workspace. Pass one to the "
            "constructor, set the MOLEXP_WORKSPACE environment variable, or "
            "run from a directory containing workspace.json."
        )

    def register(self, mcp: "FastMCP") -> None:
        """Register molexp domain tools on the host MCP server."""

        try:
            import molexp  # noqa: F401 — eager probe; surface the missing dep
        except ImportError as exc:
            raise RuntimeError(
                "MolexpProvider requires the 'molcrafts-molexp' package. "
                "Install with: pip install molcrafts-molexp"
            ) from exc

        from mcp.types import ToolAnnotations

        read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

        @mcp.tool(annotations=read_only)
        def molexp_list_projects() -> list[dict[str, Any]]:
            """Enumerate projects in the workspace."""
            workspace = self._get_workspace()
            return [
                {
                    "id": p.id,
                    "name": getattr(p.metadata, "name", p.id),
                    "description": getattr(p.metadata, "description", "") or "",
                }
                for p in workspace.list_projects()
            ]

        @mcp.tool(annotations=read_only)
        def molexp_list_runs(
            scope_kind: Literal["workspace", "project", "experiment"],
            scope_id: str = "",
            status: str | None = None,
            limit: int = 500,
        ) -> list[dict[str, Any]]:
            """Query runs by scope.

            Args:
                scope_kind: ``workspace``, ``project``, or ``experiment``.
                scope_id: Project id (when ``scope_kind='project'``),
                    experiment id (when ``'experiment'``), or empty string
                    (when ``'workspace'``).
                status: Optional status filter.
                limit: Maximum rows to return. Default 500.
            """
            if scope_kind not in _ALLOWED_SCOPES:
                return [{"error": f"Unknown scope_kind '{scope_kind}'"}]

            workspace = self._get_workspace()
            catalog = workspace.catalog
            if scope_kind == "experiment":
                rows = catalog.query_runs(
                    experiment_id=scope_id or None,
                    status=status,
                    limit=limit,
                )
            else:
                rows = catalog.query_runs(status=status, limit=limit)

            out: list[dict[str, Any]] = []
            for row in rows:
                if scope_kind == "project" and row.get("project_id") != scope_id:
                    continue
                out.append(_enriched_run_row(workspace, row))
                if len(out) >= limit:
                    break
            return out
