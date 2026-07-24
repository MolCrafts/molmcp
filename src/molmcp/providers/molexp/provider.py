"""``molexp`` MCP provider — workspace navigation + idempotent scaffold.

**Not a science executor.** Scaffold tools create-or-get workspace tree
nodes (materialize / add project / add experiment / seed a pending run).
Layout tools are read-only. Full parameter sweeps, workflow runtime
driving, harvest, and plotting stay in agent-written Python against
the molexp / molplot APIs (see molexp ``examples/agent/code_loop_golden_path.py``).

Provider-design contract:
- Navigation / layout: read-only.
- Scaffold creates: idempotent create-or-get (not arbitrary mutation).
- Never drive run batches or invoke workflow runtime from this package.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP

_WORKSPACE_ENV_VAR = "MOLEXP_WORKSPACE"
_ALLOWED_SCOPES = frozenset({"workspace", "project", "experiment"})


def _open_workspace(path: str | Path):
    from molexp.workspace import Workspace

    return Workspace(Path(path).expanduser().resolve())


def _resolve_workspace(workspace: str | None = None):
    from molexp.workspace import Workspace

    if workspace:
        return Workspace(Path(workspace).expanduser().resolve())
    env_path = os.environ.get(_WORKSPACE_ENV_VAR)
    if env_path:
        return Workspace(Path(env_path).expanduser().resolve())
    cwd = Path.cwd()
    if (cwd / "workspace.json").is_file() or (cwd / "meta.yaml").is_file():
        return Workspace(cwd)
    raise RuntimeError(
        "MolexpProvider could not resolve a workspace. Pass workspace= path, "
        f"set {_WORKSPACE_ENV_VAR}, or run from a directory containing workspace.json."
    )


class MolexpProvider:
    """Provider for molexp domain tools (scaffold + navigation)."""

    name = "molexp"

    def __init__(self, workspace: str | Path | None = None) -> None:
        self._workspace = Path(workspace).expanduser().resolve() if workspace else None

    def _get_workspace(self, workspace: str | None = None):
        if workspace:
            return _open_workspace(workspace)
        if self._workspace is not None:
            return _open_workspace(self._workspace)
        return _resolve_workspace(None)

    def register(self, mcp: FastMCP) -> None:
        try:
            import molexp  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "MolexpProvider requires molexp to be installed in this environment"
            ) from exc

        from mcp.types import ToolAnnotations

        read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
        # Idempotent scaffold (create-or-get) — not a free-form write surface.
        scaffold = ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
        )

        @mcp.tool(annotations=read_only)
        def molexp_list_projects(workspace: str | None = None) -> list[dict[str, Any]]:
            """Enumerate projects in the workspace."""
            ws = self._get_workspace(workspace)
            rows: list[dict[str, Any]] = []
            for p in ws.list_projects():
                rows.append(
                    {
                        "project_id": p.id,
                        "name": p.name,
                        "path": str(p.resolve()),
                    }
                )
            return rows

        @mcp.tool(annotations=read_only)
        def molexp_list_experiments(
            project_id: str,
            workspace: str | None = None,
        ) -> list[dict[str, Any]]:
            """List experiments under a project (read-only)."""
            from .scaffold import list_experiments

            ws = self._get_workspace(workspace)
            return list_experiments(ws.resolve(), project_id)

        @mcp.tool(annotations=read_only)
        def molexp_list_runs(
            scope_kind: Literal["workspace", "project", "experiment"] = "workspace",
            scope_id: str = "",
            status: str | None = None,
            limit: int = 500,
            workspace: str | None = None,
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
                raise ValueError(f"scope_kind must be one of {sorted(_ALLOWED_SCOPES)}")
            ws = self._get_workspace(workspace)
            rows: list[dict[str, Any]] = []
            projects = ws.list_projects()
            if scope_kind == "project":
                projects = [ws.get_project(scope_id)]
            for project in projects:
                experiments = project.list_experiments()
                if scope_kind == "experiment":
                    experiments = [
                        e for e in experiments if e.id == scope_id or e.name == scope_id
                    ]
                for exp in experiments:
                    for run in exp.list_runs():
                        if status is not None and run.status != status:
                            continue
                        rows.append(
                            {
                                "run_id": run.id,
                                "project_id": project.id,
                                "experiment_id": exp.id,
                                "status": run.status,
                                "params": dict(run.parameters),
                            }
                        )
                        if len(rows) >= limit:
                            return rows
            return rows

        @mcp.tool(annotations=read_only)
        def molexp_workspace_layout() -> dict[str, Any]:
            """Canonical molexp workspace on-disk layout contract (OKF)."""
            from .layout import layout_spec

            return layout_spec()

        @mcp.tool(annotations=read_only)
        def molexp_check_layout(path: str) -> dict[str, Any]:
            """Read-only lint of ``path`` against the layout contract."""
            from .layout import validate_workspace

            root = Path(path).expanduser().resolve()
            findings = validate_workspace(root)
            is_ws = (root / "workspace.json").is_file() or (
                root / "meta.yaml"
            ).is_file()
            return {
                "path": str(root),
                "is_workspace": is_ws,
                "ok": len(findings.items) == 0 and is_ws,
                "violations": findings.items,
            }

        def _scaffold_result(fn, *args: Any, **kwargs: Any) -> dict[str, Any]:
            """Run a scaffold helper; return structured errors instead of tracebacks."""
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — surface to the agent cleanly
                return {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }

        @mcp.tool(annotations=scaffold)
        def molexp_materialize_workspace(
            path: str,
            name: str = "workspace",
        ) -> dict[str, Any]:
            """Create or open a top-level molexp Workspace at ``path`` (idempotent).

            Do **not** use this to create a project under the session workspace —
            use ``molexp_add_project`` instead. Nesting is rejected.
            """
            from .scaffold import materialize_workspace

            return _scaffold_result(materialize_workspace, path, name=name)

        @mcp.tool(annotations=scaffold)
        def molexp_add_project(
            name: str,
            workspace: str | None = None,
        ) -> dict[str, Any]:
            """Create-or-get a project under the workspace (idempotent on slug).

            Prefer this (or omit workspace to use MOLEXP_WORKSPACE) when the user
            asks to create a project.
            """
            from .scaffold import add_project

            ws = self._get_workspace(workspace)
            return _scaffold_result(add_project, ws.resolve(), name)

        @mcp.tool(annotations=scaffold)
        def molexp_add_experiment(
            project_id: str,
            name: str,
            workspace: str | None = None,
        ) -> dict[str, Any]:
            """Create-or-get an experiment under a project (idempotent on slug)."""
            from .scaffold import add_experiment

            ws = self._get_workspace(workspace)
            return _scaffold_result(add_experiment, ws.resolve(), project_id, name)

        @mcp.tool(annotations=scaffold)
        def molexp_create_run(
            project_id: str,
            experiment_id: str,
            params: dict[str, Any] | None = None,
            workspace: str | None = None,
        ) -> dict[str, Any]:
            """Scaffold a pending run with params — does not drive the workflow."""
            from .scaffold import create_run

            ws = self._get_workspace(workspace)
            return _scaffold_result(
                create_run, ws.resolve(), project_id, experiment_id, params=params
            )

        @mcp.tool(annotations=read_only)
        def molexp_validate_workflow(source: str) -> dict[str, Any]:
            """Compile-only validation of workflow source (no task bodies run).

            Provide a Python snippet that builds a ``WorkflowCompiler`` as
            ``wf`` (or any ``WorkflowCompiler`` instance) with ``@wf.task``
            registrations. Returns ok/compiled without running science.
            """
            from .scaffold import validate_workflow_source

            return validate_workflow_source(source)
