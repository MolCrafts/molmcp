"""Tests for ``MolexpProvider``.

These tests require the optional runtime stack (``molexp``, ``molmcp``,
``fastmcp``). They are skipped when any of those packages is missing.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("molexp", reason="molcrafts-molexp not installed")
pytest.importorskip("molmcp", reason="molcrafts-molmcp not installed")
pytest.importorskip("fastmcp", reason="fastmcp not installed")

from molexp.workspace import Workspace  # noqa: E402

from molmcp_molexp import MolexpProvider  # noqa: E402


def _build_server(workspace_root: Any) -> Any:
    """Build a FastMCP server containing only the MolexpProvider."""
    from molmcp import create_server

    return create_server(
        name="molexp-test",
        providers=[MolexpProvider(workspace_root)],
        discover_entry_points=False,
        import_roots=None,
    )


def _tool(server: Any, name: str) -> Any:
    """Look up a registered FastMCP tool by name and return the wrapped fn."""
    import asyncio

    tool = asyncio.run(server.get_tool(name))
    if tool is None:
        raise KeyError(f"Tool '{name}' not registered")
    return tool.fn


def _list_tools(server: Any) -> list[Any]:
    import asyncio

    return asyncio.run(server.list_tools())


@pytest.fixture
def populated_ws(tmp_path):
    """Workspace with one project, one experiment, one run."""
    ws = Workspace(root=tmp_path, name="MCP Test Lab")
    project = ws.project("proj-x")
    experiment = project.experiment(
        "exp-x",
        workflow_source=None,
        params={"temperature": 300},
    )
    experiment.run(parameters={"temperature": 300, "seed": 7})
    return ws


def test_list_projects_returns_existing(populated_ws):
    server = _build_server(populated_ws.root)
    out = _tool(server, "list_projects")()
    assert any(p["id"] == "proj-x" for p in out)


def test_list_experiments_for_project(populated_ws):
    server = _build_server(populated_ws.root)
    out = _tool(server, "list_experiments")(project_id="proj-x")
    assert len(out) >= 1
    assert any(e["id"] == "exp-x" for e in out)


def test_list_experiments_unknown_project_returns_empty(populated_ws):
    server = _build_server(populated_ws.root)
    assert _tool(server, "list_experiments")(project_id="missing") == []


def test_list_runs_workspace_scope(populated_ws):
    server = _build_server(populated_ws.root)
    rows = _tool(server, "list_runs")(scope_kind="workspace")
    assert len(rows) >= 1
    row = rows[0]
    assert row["project_id"] == "proj-x"
    assert row["experiment_id"] == "exp-x"
    assert "parameters" in row


def test_list_runs_rejects_unknown_scope(populated_ws):
    server = _build_server(populated_ws.root)
    out = _tool(server, "list_runs")(scope_kind="galaxy")  # type: ignore[arg-type]
    assert isinstance(out, list)
    assert out and "error" in out[0]


def test_get_run_returns_status_and_parameters(populated_ws):
    server = _build_server(populated_ws.root)
    runs = list(populated_ws.get_project("proj-x").get_experiment("exp-x").list_runs())
    run_id = runs[0].id
    out = _tool(server, "get_run")(
        project_id="proj-x", experiment_id="exp-x", run_id=run_id
    )
    assert out["run_id"] == run_id
    assert out["status"]
    assert out["parameters"].get("temperature") == 300


def test_get_run_unknown_returns_error(populated_ws):
    server = _build_server(populated_ws.root)
    out = _tool(server, "get_run")(
        project_id="proj-x", experiment_id="exp-x", run_id="missing"
    )
    assert "error" in out


def test_get_metrics_no_data_returns_empty(populated_ws):
    server = _build_server(populated_ws.root)
    runs = list(populated_ws.get_project("proj-x").get_experiment("exp-x").list_runs())
    out = _tool(server, "get_metrics")(
        project_id="proj-x", experiment_id="exp-x", run_id=runs[0].id
    )
    assert out["run_id"] == runs[0].id
    assert out.get("metrics") == {}


def test_get_asset_text_blocks_path_traversal(populated_ws):
    server = _build_server(populated_ws.root)
    runs = list(populated_ws.get_project("proj-x").get_experiment("exp-x").list_runs())
    out = _tool(server, "get_asset_text")(
        project_id="proj-x",
        experiment_id="exp-x",
        run_id=runs[0].id,
        rel_path="../../../etc/passwd",
    )
    assert "error" in out


def test_get_asset_text_missing_file_returns_error(populated_ws):
    server = _build_server(populated_ws.root)
    runs = list(populated_ws.get_project("proj-x").get_experiment("exp-x").list_runs())
    out = _tool(server, "get_asset_text")(
        project_id="proj-x",
        experiment_id="exp-x",
        run_id=runs[0].id,
        rel_path="not-a-real-file.log",
    )
    assert "error" in out


def test_provider_implements_molmcp_protocol(populated_ws):
    """MolexpProvider must satisfy molmcp's runtime-checkable Provider protocol."""
    from molmcp import Provider

    provider = MolexpProvider(populated_ws.root)
    assert isinstance(provider, Provider)
    assert provider.name == "molexp"


def test_workspace_resolution_from_env(populated_ws, monkeypatch):
    """When constructed without args, the provider falls back to MOLEXP_WORKSPACE."""
    monkeypatch.setenv("MOLEXP_WORKSPACE", str(populated_ws.root))
    provider = MolexpProvider()
    resolved = provider._resolve_workspace()
    assert resolved.root == populated_ws.root


def test_workspace_resolution_failure_raises(monkeypatch, tmp_path):
    """No constructor arg, no env var, no workspace.json → clear error."""
    monkeypatch.delenv("MOLEXP_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    provider = MolexpProvider()
    with pytest.raises(RuntimeError, match="MOLEXP_WORKSPACE"):
        provider._resolve_workspace()


def test_all_tools_have_read_only_annotation(populated_ws):
    """molmcp's annotation validator would otherwise reject the server at startup."""
    server = _build_server(populated_ws.root)
    tools = _list_tools(server)
    assert tools, "no tools registered"
    for tool in tools:
        annotations = getattr(tool, "annotations", None)
        assert annotations is not None, f"Tool {tool.name!r} missing annotations"
        assert getattr(annotations, "readOnlyHint", False) is True, (
            f"Tool {tool.name!r} not marked read-only"
        )
