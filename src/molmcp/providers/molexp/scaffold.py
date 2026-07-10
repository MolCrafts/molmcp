"""Idempotent workspace scaffold helpers for MolexpProvider tools.

All mutations are create-or-get via molexp public API. Never executes
runs, sweeps, or science workflows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def materialize_workspace(
    path: str | Path, *, name: str = "workspace"
) -> dict[str, Any]:
    """Create or open a Workspace at *path* (idempotent)."""
    from molexp.workspace import Workspace

    root = Path(path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    ws = Workspace(root, name=name)
    ws.materialize()
    return {
        "path": str(root),
        "name": ws.name,
        "id": getattr(ws, "id", ws.name),
        "materialized": True,
    }


def add_project(workspace: str | Path, name: str) -> dict[str, Any]:
    """``ws.add_project(name)`` — idempotent on slug."""
    from molexp.workspace import Workspace

    ws = Workspace(Path(workspace).expanduser().resolve())
    ws.materialize()
    project = ws.add_project(name)
    return {"project_id": project.id, "name": project.name, "path": str(project.path)}


def add_experiment(
    workspace: str | Path,
    project_id: str,
    name: str,
) -> dict[str, Any]:
    """``project.add_experiment(name)`` — idempotent on slug."""
    from molexp.workspace import Workspace

    ws = Workspace(Path(workspace).expanduser().resolve())
    project = ws.get_project(project_id)
    experiment = project.add_experiment(name)
    return {
        "project_id": project.id,
        "experiment_id": experiment.id,
        "name": experiment.name,
        "path": str(experiment.path),
    }


def list_experiments(workspace: str | Path, project_id: str) -> list[dict[str, Any]]:
    """List experiments under a project (read-only)."""
    from molexp.workspace import Workspace

    ws = Workspace(Path(workspace).expanduser().resolve())
    project = ws.get_project(project_id)
    return [
        {"experiment_id": e.id, "name": e.name, "path": str(e.path)}
        for e in project.list_experiments()
    ]


def create_run(
    workspace: str | Path,
    project_id: str,
    experiment_id: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Scaffold ``add_run(params=…)`` only — leaves the run pending."""
    from molexp.workspace import Workspace

    ws = Workspace(Path(workspace).expanduser().resolve())
    experiment = ws.get_project(project_id).get_experiment(experiment_id)
    run = experiment.add_run(params=params or {})
    return {
        "project_id": project_id,
        "experiment_id": experiment_id,
        "run_id": run.id,
        "status": run.status,
        "params": dict(run.parameters),
        "executed": False,
    }


def validate_workflow_source(source: str) -> dict[str, Any]:
    """Compile-only check of a WorkflowCompiler decorator source snippet.

    Expects a string that defines a ``WorkflowCompiler`` named ``wf`` and
    registers tasks, ending ready for ``wf.compile()``. Does **not** run
    task bodies.
    """
    from molexp.workflow import WorkflowCompiler

    namespace: dict[str, Any] = {"WorkflowCompiler": WorkflowCompiler}
    try:
        exec(source, namespace)  # noqa: S102 — intentional compile-only sandbox for trusted agent code
    except Exception as exc:  # noqa: BLE001 — surface any compile/exec error
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "compiled": False}

    wf = namespace.get("wf")
    if wf is None:
        for value in namespace.values():
            if isinstance(value, WorkflowCompiler):
                wf = value
                break
    if not isinstance(wf, WorkflowCompiler):
        return {
            "ok": False,
            "error": (
                "source must define WorkflowCompiler instance as 'wf' or assign one"
            ),
            "compiled": False,
        }
    try:
        compiled = wf.compile()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "compiled": False}
    name = getattr(compiled, "name", None) or getattr(wf, "name", "")
    return {"ok": True, "compiled": True, "name": name, "error": None}
