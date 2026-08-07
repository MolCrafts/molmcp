"""Idempotent workspace scaffold helpers for MolexpProvider tools.

All mutations are create-or-get via molexp public API. Never executes
runs, sweeps, or science workflows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: Settings key holding the default workspace path.
_WORKSPACE_SETTING = "molexp.workspace"


def _configured_workspace() -> str:
    """Default workspace from settings, or empty when unset."""
    from molmcp.settings import load_settings

    return str(load_settings(Path.cwd()).molexp.get("workspace", "")).strip()


def materialize_workspace(
    path: str | Path, *, name: str = "workspace"
) -> dict[str, Any]:
    """Create or open a Workspace at *path* (idempotent).

    Refuses to nest a new workspace under the session workspace pointed
    at by ``MOLEXP_WORKSPACE`` (or under a path that already has a
    parent ``workspace.json``). "Create a project" is
    :func:`add_project`, not a nested workspace.
    """
    from molexp.workspace import Workspace

    root = Path(path).expanduser().resolve()
    session = _configured_workspace()
    if session:
        session_root = Path(session).expanduser().resolve()
        if root != session_root and _is_relative_to(root, session_root):
            raise RuntimeError(
                f"refusing to nest a workspace at {root} under the session "
                f"workspace {session_root}. To create a *project*, call "
                f"`add_project(name=…)` with workspace omitted (uses the "
                f"{_WORKSPACE_SETTING} setting) or workspace={session_root!s}. "
                f"Only use `materialize_workspace` when opening a brand-new "
                f"top-level workspace path."
            )
    parent_ws = _nearest_workspace_root(root.parent)
    if parent_ws is not None and parent_ws != root:
        raise RuntimeError(
            f"refusing to nest a workspace at {root} inside existing "
            f"workspace {parent_ws}. Use `add_project` under that "
            f"workspace instead of materialize_workspace."
        )
    root.mkdir(parents=True, exist_ok=True)
    ws = Workspace(root, name=name)
    ws.materialize()
    return {
        "path": str(ws.resolve()),
        "name": ws.name,
        "id": getattr(ws, "id", ws.name),
        "materialized": True,
    }


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _nearest_workspace_root(start: Path) -> Path | None:
    """Walk parents for ``workspace.json`` / OKF ``meta.yaml`` marker."""
    cur = start.resolve()
    for _ in range(32):
        if (cur / "workspace.json").is_file() or (cur / "meta.yaml").is_file():
            # meta.yaml alone is not enough if it's a project/experiment;
            # prefer workspace.json when present, else treat meta as weak.
            if (cur / "workspace.json").is_file():
                return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _folder_path(folder: object) -> str:
    """``Folder.path`` is a method; prefer :meth:`resolve` for a Path."""
    resolve = getattr(folder, "resolve", None)
    if callable(resolve):
        return str(resolve())
    path = getattr(folder, "path", None)
    if callable(path):
        return str(path())
    return str(path)


def add_project(workspace: str | Path, name: str) -> dict[str, Any]:
    """``ws.add_project(name)`` — idempotent on slug."""
    from molexp.workspace import Workspace

    ws = Workspace(Path(workspace).expanduser().resolve())
    ws.materialize()
    project = ws.add_project(name)
    return {
        "project_id": project.id,
        "name": project.name,
        "path": _folder_path(project),
    }


def add_experiment(
    workspace: str | Path,
    project_id: str,
    name: str,
) -> dict[str, Any]:
    """``project.add_experiment(name)`` — idempotent on slug."""
    from molexp.workspace import Workspace

    ws = Workspace(Path(workspace).expanduser().resolve())
    project = _require_project(ws, project_id)
    experiment = project.add_experiment(name)
    return {
        "project_id": project.id,
        "experiment_id": experiment.id,
        "name": experiment.name,
        "path": _folder_path(experiment),
    }


def list_experiments(workspace: str | Path, project_id: str) -> list[dict[str, Any]]:
    """List experiments under a project (read-only)."""
    from molexp.workspace import Workspace

    ws = Workspace(Path(workspace).expanduser().resolve())
    project = _require_project(ws, project_id)
    return [
        {
            "experiment_id": e.id,
            "name": e.name,
            "path": _folder_path(e),
        }
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
    project = _require_project(ws, project_id)
    try:
        experiment = project.get_experiment(experiment_id)
    except Exception as exc:
        available = [e.id for e in project.list_experiments()]
        raise RuntimeError(
            f"experiment {experiment_id!r} not found under project "
            f"{project.id!r} in workspace {ws.resolve()}. "
            f"Available experiments: {available}. "
            f"Call `add_experiment(project_id={project.id!r}, name=…)` first."
        ) from exc
    run = experiment.add_run(params=params or {})
    return {
        "project_id": project.id,
        "experiment_id": experiment.id,
        "run_id": run.id,
        "status": run.status,
        "params": dict(run.parameters),
        "executed": False,
    }


def _require_project(ws: object, project_id: str) -> object:
    """Resolve *project_id* or raise a clean, actionable error (no traceback spam)."""
    get_project = getattr(ws, "get_project")
    list_projects = getattr(ws, "list_projects")
    resolve = getattr(ws, "resolve")
    try:
        return get_project(project_id)
    except Exception:
        available = [p.id for p in list_projects()]
        root = resolve() if callable(resolve) else resolve
        raise RuntimeError(
            f"project {project_id!r} not found in workspace {root}. "
            f"Available projects: {available}. "
            f"Call `add_project(name=…)` first (do NOT materialize a "
            f"nested workspace under this path), or pass the correct "
            f"workspace= absolute path from the session Workspace: line."
        ) from None


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
