"""MolexpProvider scaffold + navigation tools (agent-code-loop-04)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Source package root for AST non-executor check
_PROVIDER_PKG = (
    Path(__file__).resolve().parents[2] / "src" / "molmcp" / "providers" / "molexp"
)


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    return tmp_path / "ws"


def test_materialize_workspace_is_idempotent(workspace_path: Path) -> None:
    from molmcp.providers.molexp.scaffold import materialize_workspace

    first = materialize_workspace(workspace_path, name="lab")
    second = materialize_workspace(workspace_path, name="lab")
    assert first["path"] == second["path"]
    assert (workspace_path / "workspace.json").is_file() or (
        workspace_path / "meta.yaml"
    ).is_file()


def test_add_project_and_experiment_idempotent_on_slug(workspace_path: Path) -> None:
    from molmcp.providers.molexp.scaffold import (
        add_experiment,
        add_project,
        materialize_workspace,
    )

    materialize_workspace(workspace_path)
    p1 = add_project(workspace_path, "Demo Project")
    p2 = add_project(workspace_path, "Demo Project")
    assert p1["project_id"] == p2["project_id"]
    e1 = add_experiment(workspace_path, p1["project_id"], "YY Scan")
    e2 = add_experiment(workspace_path, p1["project_id"], "YY Scan")
    assert e1["experiment_id"] == e2["experiment_id"]
    # single directory
    projects = list((workspace_path / "projects").iterdir())
    assert len([d for d in projects if d.is_dir()]) == 1


def test_list_experiments_is_read_only(workspace_path: Path) -> None:
    from molmcp.providers.molexp.scaffold import (
        add_experiment,
        add_project,
        list_experiments,
        materialize_workspace,
    )

    materialize_workspace(workspace_path)
    proj = add_project(workspace_path, "p")
    add_experiment(workspace_path, proj["project_id"], "e1")
    before = list(
        (workspace_path / "projects" / proj["project_id"] / "experiments").iterdir()
    )
    rows = list_experiments(workspace_path, proj["project_id"])
    after = list(
        (workspace_path / "projects" / proj["project_id"] / "experiments").iterdir()
    )
    assert len(rows) == 1
    assert rows[0]["experiment_id"] == "e1"
    assert len(before) == len(after)


def test_create_run_does_not_execute(workspace_path: Path) -> None:
    from molmcp.providers.molexp.scaffold import (
        add_experiment,
        add_project,
        create_run,
        materialize_workspace,
    )

    materialize_workspace(workspace_path)
    proj = add_project(workspace_path, "p")
    exp = add_experiment(workspace_path, proj["project_id"], "e")
    row = create_run(
        workspace_path,
        proj["project_id"],
        exp["experiment_id"],
        params={"x": 1.0},
    )
    assert row["executed"] is False
    assert row["status"] in {"pending", "succeeded", "failed", "cancelled", "running"}
    # pending is the expected scaffold state
    assert row["status"] == "pending"


def test_validate_workflow_compile_only() -> None:
    from molmcp.providers.molexp.scaffold import validate_workflow_source

    source = """
from molexp.workflow import WorkflowCompiler
wf = WorkflowCompiler(name="yy")

@wf.task
def yy_score(x: float = 0.0) -> float:
    return x * x
"""
    result = validate_workflow_source(source)
    assert result["ok"] is True
    assert result["compiled"] is True

    bad = validate_workflow_source("raise RuntimeError('nope')")
    assert bad["ok"] is False


def test_check_layout_reports_ok_workspace(workspace_path: Path) -> None:
    from molmcp.providers.molexp.layout import validate_workspace
    from molmcp.providers.molexp.scaffold import (
        add_experiment,
        add_project,
        materialize_workspace,
    )

    materialize_workspace(workspace_path)
    proj = add_project(workspace_path, "demo")
    add_experiment(workspace_path, proj["project_id"], "yy-scan")
    findings = validate_workspace(workspace_path)
    assert findings.items == []


def test_provider_modules_never_execute_science() -> None:
    """AC-004: no RunSet.execute / execute_run / aexecute_run in provider package."""
    for path in _PROVIDER_PKG.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "execute":
                raise AssertionError(f"{path.name}: forbidden .execute attribute")
            if isinstance(node, ast.Name) and node.id in {
                "execute_run",
                "aexecute_run",
            }:
                raise AssertionError(f"{path.name}: forbidden {node.id}")
        for token in ("execute_run", "aexecute_run", "RunSet.execute"):
            assert token not in text, f"{path.name} contains {token}"


@pytest.mark.asyncio
async def test_provider_registers_scaffold_tools() -> None:
    from fastmcp import FastMCP

    from molmcp.providers.molexp import MolexpProvider

    mcp = FastMCP("test-molexp")
    MolexpProvider().register(mcp)
    listed = await mcp.list_tools()
    names = {t.name for t in listed}
    expected = {
        "list_projects",
        "list_experiments",
        "list_runs",
        "workspace_layout",
        "check_layout",
        "materialize_workspace",
        "add_project",
        "add_experiment",
        "create_run",
        "validate_workflow",
    }
    assert expected.issubset(names)
