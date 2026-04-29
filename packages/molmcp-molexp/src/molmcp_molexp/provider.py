"""``molexp`` MCP provider.

The suite owns molexp's MCP integration. molexp itself ships **no** MCP code
— installing ``molcrafts-mcp-suite`` is the only supported way to expose
molexp through MCP.

Tools (all read-only):

* ``list_projects`` — enumerate projects in the workspace.
* ``list_experiments`` — enumerate experiments for a project.
* ``list_runs`` — query runs by scope (workspace / project / experiment),
  joining catalog rows with per-run parameters.
* ``get_run`` — full metadata for one run.
* ``get_metrics`` — latest values (or full series) for a run's metrics.
* ``get_asset_text`` — fetch the UTF-8 contents of a file under a run
  directory.

Workspace resolution (in order):

1. The ``workspace`` argument passed to the constructor.
2. The ``MOLEXP_WORKSPACE`` environment variable.
3. The current working directory if it contains ``workspace.json``.

When the suite CLI auto-instantiates ``MolexpProvider()`` it relies on
paths 2 or 3.

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

        from mcp.types import ToolAnnotations
        from molexp.plugins.metrics import read_run_metrics as _read_run_metrics

        read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

        @mcp.tool(annotations=read_only)
        def list_projects() -> list[dict[str, Any]]:
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
        def list_experiments(project_id: str) -> list[dict[str, Any]]:
            """Enumerate experiments belonging to a project."""
            workspace = self._get_workspace()
            project = workspace.get_project(project_id)
            if project is None:
                return []
            return [
                {
                    "id": e.id,
                    "name": getattr(e.metadata, "name", e.id),
                    "description": getattr(e.metadata, "description", "") or "",
                    "parameter_space": dict(
                        getattr(e.metadata, "parameter_space", {}) or {}
                    ),
                }
                for e in project.list_experiments()
            ]

        @mcp.tool(annotations=read_only)
        def list_runs(
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

        @mcp.tool(annotations=read_only)
        def get_run(
            project_id: str, experiment_id: str, run_id: str
        ) -> dict[str, Any]:
            """Return full metadata for one run."""
            workspace = self._get_workspace()
            project = workspace.get_project(project_id)
            if project is None:
                return {"error": f"Project '{project_id}' not found"}
            experiment = project.get_experiment(experiment_id)
            if experiment is None:
                return {"error": f"Experiment '{experiment_id}' not found"}
            run = experiment.get_run(run_id)
            if run is None:
                return {"error": f"Run '{run_id}' not found"}
            meta = run.metadata
            created = getattr(meta, "created_at", None)
            finished = getattr(meta, "finished_at", None)
            err = getattr(meta, "error", None)
            return {
                "run_id": run.id,
                "project_id": project_id,
                "experiment_id": experiment_id,
                "status": _coerce_status(run.status),
                "parameters": dict(getattr(run, "parameters", {}) or {}),
                "created_at": created.isoformat() if created else None,
                "finished_at": finished.isoformat() if finished else None,
                "error": (
                    {
                        "type": getattr(err, "type", "Error"),
                        "message": getattr(err, "message", ""),
                    }
                    if err is not None
                    else None
                ),
            }

        @mcp.tool(annotations=read_only)
        def get_metrics(
            project_id: str,
            experiment_id: str,
            run_id: str,
            keys: list[str] | None = None,
            latest_only: bool = True,
            limit: int = 5000,
        ) -> dict[str, Any]:
            """Return metric values for a run.

            Args:
                project_id: Containing project id.
                experiment_id: Containing experiment id.
                run_id: Run identifier.
                keys: Optional restriction to specific metric keys. ``None``
                    returns all available series.
                latest_only: When true (default) returns
                    ``{key: latest_value}``; when false returns full per-key
                    time series records.
                limit: Maximum records to scan.
            """
            workspace = self._get_workspace()
            project = workspace.get_project(project_id)
            if project is None:
                return {"error": f"Project '{project_id}' not found"}
            experiment = project.get_experiment(experiment_id)
            if experiment is None:
                return {"error": f"Experiment '{experiment_id}' not found"}
            run = experiment.get_run(run_id)
            if run is None:
                return {"error": f"Run '{run_id}' not found"}

            result = _read_run_metrics(run.run_dir, limit=limit)
            records = list(result.records)
            if keys:
                wanted = set(keys)
                records = [r for r in records if r.get("k") in wanted]
            if latest_only:
                latest: dict[str, Any] = {}
                for record in records:
                    key = record.get("k")
                    if key is None:
                        continue
                    latest[key] = record.get("v")
                return {"run_id": run.id, "metrics": latest}
            series: dict[str, list[dict[str, Any]]] = {}
            for record in records:
                key = record.get("k")
                if key is None:
                    continue
                series.setdefault(key, []).append(
                    {
                        "step": record.get("s"),
                        "value": record.get("v"),
                        "wall_time": record.get("w"),
                    }
                )
            return {"run_id": run.id, "series": series}

        @mcp.tool(annotations=read_only)
        def get_asset_text(
            project_id: str,
            experiment_id: str,
            run_id: str,
            rel_path: str,
            max_bytes: int = 200_000,
        ) -> dict[str, Any]:
            """Fetch the UTF-8 text of a file under a run directory.

            Args:
                project_id: Containing project id.
                experiment_id: Containing experiment id.
                run_id: Run identifier.
                rel_path: Path relative to ``run_dir`` (e.g.
                    ``executions/exec-…/stdout.log``). ``..`` is rejected
                    (defense-in-depth alongside molmcp's
                    :class:`PathSafetyMiddleware`).
                max_bytes: Maximum bytes to read; the response indicates
                    whether the file was truncated.
            """
            workspace = self._get_workspace()
            project = workspace.get_project(project_id)
            if project is None:
                return {"error": f"Project '{project_id}' not found"}
            experiment = project.get_experiment(experiment_id)
            if experiment is None:
                return {"error": f"Experiment '{experiment_id}' not found"}
            run = experiment.get_run(run_id)
            if run is None:
                return {"error": f"Run '{run_id}' not found"}

            run_dir = Path(run.run_dir).resolve()
            target = (run_dir / rel_path).resolve()
            try:
                target.relative_to(run_dir)
            except ValueError:
                return {"error": "rel_path escapes run directory"}
            if not target.exists() or not target.is_file():
                return {"error": f"File '{rel_path}' not found"}

            data = target.read_bytes()
            truncated = len(data) > max_bytes
            text = data[:max_bytes].decode("utf-8", errors="replace")
            return {
                "path": str(target.relative_to(run_dir)),
                "content": text,
                "size": len(data),
                "truncated": truncated,
            }
