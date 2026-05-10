"""Tests for ``MolexpProvider`` (slim: list_projects + list_runs).

Per the molmcp design principle — *the plugin is a knowledge surface,
not an execution engine* — these tests do not require ``molexp`` to be
installed. We inject a stub ``molexp`` package into ``sys.modules`` so
the provider's eager import guard and its in-tool imports resolve to a
controlled minimal surface.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("molmcp", reason="molcrafts-molmcp not installed")
pytest.importorskip("fastmcp", reason="fastmcp not installed")


class _FakeWorkspace:
    """Minimal stand-in for ``molexp.workspace.Workspace``.

    The provider's ``_resolve_workspace`` does ``isinstance(arg, Workspace)``
    so the tests need a real class — not a MagicMock — for the
    isinstance check to succeed.
    """

    def __init__(self, root: str | Path | None = None, **_ignored):
        self.root = Path(root) if root is not None else Path("/fake/ws")
        self._projects: dict[str, object] = {}
        self._catalog_data: dict = {"experiments": {}}
        self._catalog_runs: list[dict] = []

    def list_projects(self):
        return list(self._projects.values())

    def get_project(self, project_id: str):
        return self._projects.get(project_id)

    @property
    def catalog(self):
        ws = self
        return SimpleNamespace(
            _load=lambda: ws._catalog_data,
            query_runs=lambda **kw: list(ws._catalog_runs),
        )


@pytest.fixture(autouse=True)
def stub_molexp(monkeypatch):
    """Inject a fake ``molexp`` package tree into sys.modules."""
    molexp = ModuleType("molexp")
    workspace_mod = ModuleType("molexp.workspace")
    workspace_mod.Workspace = _FakeWorkspace

    monkeypatch.setitem(sys.modules, "molexp", molexp)
    monkeypatch.setitem(sys.modules, "molexp.workspace", workspace_mod)
    return SimpleNamespace(Workspace=_FakeWorkspace)


def _build_server(workspace):
    from molmcp import create_server
    from molmcp.providers.molexp import MolexpProvider

    return create_server(
        name="molexp-test",
        providers=[MolexpProvider(workspace)],
        discover_entry_points=False,
        import_roots=None,
    )


def _tool(server, name):
    import asyncio

    tool = asyncio.run(server.get_tool(name))
    if tool is None:
        raise KeyError(name)
    return tool.fn


def _list_tools(server):
    import asyncio

    return asyncio.run(server.list_tools())


def _make_project(*, pid, name="", description=""):
    return SimpleNamespace(
        id=pid,
        metadata=SimpleNamespace(name=name or pid, description=description),
    )


def _populated_workspace():
    """One project + one run row in the catalog."""
    ws = _FakeWorkspace()
    ws._projects["proj-x"] = _make_project(pid="proj-x")
    ws._catalog_data["experiments"] = {"exp-x": {"project_id": "proj-x"}}
    ws._catalog_runs = [
        {
            "run_id": "run-7",
            "experiment_id": "exp-x",
            "project_id": "proj-x",
            "status": "succeeded",
            "parameters": {"temperature": 300, "seed": 7},
            "created_at": 1.0,
            "finished_at": 2.0,
            "config_hash": "abcd",
        }
    ]
    return ws


class TestProtocol:
    def test_implements_molmcp_protocol(self):
        from molmcp import Provider
        from molmcp.providers.molexp import MolexpProvider

        p = MolexpProvider(_FakeWorkspace())
        assert isinstance(p, Provider)
        assert p.name == "molexp"

    def test_register_without_molexp_raises_runtime_error(self, monkeypatch):
        from molmcp.providers.molexp import MolexpProvider

        monkeypatch.setitem(sys.modules, "molexp", None)
        with pytest.raises(RuntimeError, match="molcrafts-molexp"):
            MolexpProvider(_FakeWorkspace()).register(MagicMock())

    def test_tool_set(self):
        """The slim catalog: only molexp_list_projects and molexp_list_runs."""
        server = _build_server(_FakeWorkspace())
        names = {t.name for t in _list_tools(server)}
        assert names == {"molexp_list_projects", "molexp_list_runs"}

    def test_all_tools_have_read_only_annotation(self):
        server = _build_server(_FakeWorkspace())
        for tool in _list_tools(server):
            ann = getattr(tool, "annotations", None)
            assert ann is not None, f"{tool.name!r} missing annotations"
            assert getattr(ann, "readOnlyHint", False) is True, (
                f"{tool.name!r} not marked read-only"
            )


class TestWorkspaceResolution:
    def test_from_env(self, monkeypatch, tmp_path):
        from molmcp.providers.molexp import MolexpProvider

        monkeypatch.setenv("MOLEXP_WORKSPACE", str(tmp_path))
        provider = MolexpProvider()
        resolved = provider._resolve_workspace()
        assert isinstance(resolved, _FakeWorkspace)
        assert resolved.root == tmp_path.resolve()

    def test_failure_raises(self, monkeypatch, tmp_path):
        from molmcp.providers.molexp import MolexpProvider

        monkeypatch.delenv("MOLEXP_WORKSPACE", raising=False)
        monkeypatch.chdir(tmp_path)
        with pytest.raises(RuntimeError, match="MOLEXP_WORKSPACE"):
            MolexpProvider()._resolve_workspace()


class TestMolexpListProjects:
    def test_lists_projects(self):
        ws = _populated_workspace()
        server = _build_server(ws)
        out = _tool(server, "molexp_list_projects")()
        assert any(p["id"] == "proj-x" for p in out)


class TestMolexpListRuns:
    def test_workspace_scope(self):
        ws = _populated_workspace()
        server = _build_server(ws)
        rows = _tool(server, "molexp_list_runs")(scope_kind="workspace")
        assert len(rows) == 1
        row = rows[0]
        assert row["project_id"] == "proj-x"
        assert row["experiment_id"] == "exp-x"
        assert row["parameters"] == {"temperature": 300, "seed": 7}

    def test_rejects_unknown_scope(self):
        ws = _populated_workspace()
        server = _build_server(ws)
        out = _tool(server, "molexp_list_runs")(scope_kind="galaxy")  # type: ignore[arg-type]
        assert isinstance(out, list)
        assert out and "error" in out[0]

    def test_project_scope_filters(self):
        ws = _populated_workspace()
        # add a second run under a different project
        ws._catalog_runs.append(
            {
                "run_id": "run-9",
                "experiment_id": "exp-y",
                "project_id": "proj-y",
                "status": "succeeded",
                "parameters": {},
                "created_at": 3.0,
                "finished_at": 4.0,
                "config_hash": "deadbeef",
            }
        )
        server = _build_server(ws)
        rows = _tool(server, "molexp_list_runs")(
            scope_kind="project", scope_id="proj-x"
        )
        assert {r["run_id"] for r in rows} == {"run-7"}
