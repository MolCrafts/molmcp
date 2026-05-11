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
from typing import Any
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


def _recording_workspace() -> tuple[_FakeWorkspace, dict[str, Any]]:
    """A workspace whose ``catalog.query_runs`` records the kwargs it sees.

    Used to assert that the provider forwards the right filter arguments
    instead of just observing the post-filter row list.
    """
    captured: dict[str, Any] = {}

    class _RecordingWorkspace(_FakeWorkspace):
        @property
        def catalog(self):
            return SimpleNamespace(
                _load=lambda: self._catalog_data,
                query_runs=lambda **kw: (captured.update(kw), [])[1],
            )

    return _RecordingWorkspace(), captured


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


class TestProtocolAnnotations:
    def test_tools_are_closed_world(self):
        server = _build_server(_FakeWorkspace())
        for tool in _list_tools(server):
            ann = getattr(tool, "annotations", None)
            assert ann is not None, f"{tool.name!r} missing annotations"
            assert getattr(ann, "openWorldHint", True) is False, (
                f"{tool.name!r} not marked closed-world"
            )


class TestSerializeHelpers:
    def test_coerce_status_none_to_empty_string(self):
        from molmcp.providers.molexp.provider import _coerce_status

        assert _coerce_status(None) == ""

    def test_coerce_status_passes_through_string(self):
        from molmcp.providers.molexp.provider import _coerce_status

        assert _coerce_status("running") == "running"

    def test_coerce_status_stringifies_non_string(self):
        from molmcp.providers.molexp.provider import _coerce_status

        assert _coerce_status(42) == "42"

    def test_project_for_experiment_returns_none_for_missing_id(self):
        from molmcp.providers.molexp.provider import _project_for_experiment

        ws = _FakeWorkspace()
        assert _project_for_experiment(ws, None) is None
        assert _project_for_experiment(ws, "") is None

    def test_project_for_experiment_returns_none_for_unknown_experiment(self):
        from molmcp.providers.molexp.provider import _project_for_experiment

        ws = _FakeWorkspace()
        assert _project_for_experiment(ws, "exp-not-here") is None

    def test_project_for_experiment_resolves_via_catalog(self):
        from molmcp.providers.molexp.provider import _project_for_experiment

        ws = _FakeWorkspace()
        ws._catalog_data["experiments"] = {"exp-1": {"project_id": "p-9"}}
        assert _project_for_experiment(ws, "exp-1") == "p-9"


class TestEnrichedRunRow:
    """``_enriched_run_row`` joins catalog rows with on-disk parameters."""

    def test_uses_inline_parameters_when_present(self):
        from molmcp.providers.molexp.provider import _enriched_run_row

        ws = _FakeWorkspace()
        row = _enriched_run_row(
            ws,
            {
                "run_id": "r1",
                "project_id": "p1",
                "experiment_id": "e1",
                "status": "running",
                "parameters": {"seed": 42},
                "created_at": 1.0,
                "finished_at": None,
                "config_hash": "abc",
            },
        )
        assert row["parameters"] == {"seed": 42}
        assert row["status"] == "running"
        assert row["config_hash"] == "abc"

    def test_falls_back_to_disk_run_parameters(self):
        """When catalog ``parameters`` is empty, walk project→experiment→run."""
        from molmcp.providers.molexp.provider import _enriched_run_row

        ws = _FakeWorkspace()
        run = SimpleNamespace(parameters={"temperature": 300})
        experiment = SimpleNamespace(get_run=lambda rid: run if rid == "r1" else None)
        project = SimpleNamespace(
            get_experiment=lambda eid: experiment if eid == "e1" else None
        )
        ws._projects["p1"] = project

        row = _enriched_run_row(
            ws,
            {
                "run_id": "r1",
                "project_id": "p1",
                "experiment_id": "e1",
                "status": None,
                "parameters": {},
            },
        )
        assert row["parameters"] == {"temperature": 300}
        # _coerce_status maps None → ""
        assert row["status"] == ""

    def test_resolves_missing_project_id_via_catalog(self):
        from molmcp.providers.molexp.provider import _enriched_run_row

        ws = _FakeWorkspace()
        ws._catalog_data["experiments"] = {"e1": {"project_id": "p1"}}
        row = _enriched_run_row(
            ws,
            {
                "run_id": "r1",
                "experiment_id": "e1",
                "status": "succeeded",
                "parameters": {"x": 1},
            },
        )
        assert row["project_id"] == "p1"


class TestWorkspaceResolutionExtras:
    def test_explicit_path_argument(self, tmp_path):
        from molmcp.providers.molexp import MolexpProvider

        provider = MolexpProvider(workspace=tmp_path)
        ws = provider._resolve_workspace()
        assert isinstance(ws, _FakeWorkspace)
        assert ws.root == tmp_path.resolve()

    def test_existing_workspace_instance_passed_through(self):
        from molmcp.providers.molexp import MolexpProvider

        existing = _FakeWorkspace(root="/preexisting")
        provider = MolexpProvider(workspace=existing)
        assert provider._resolve_workspace() is existing

    def test_cwd_with_workspace_json(self, monkeypatch, tmp_path):
        from molmcp.providers.molexp import MolexpProvider

        monkeypatch.delenv("MOLEXP_WORKSPACE", raising=False)
        (tmp_path / "workspace.json").write_text("{}")
        monkeypatch.chdir(tmp_path)
        ws = MolexpProvider()._resolve_workspace()
        assert isinstance(ws, _FakeWorkspace)
        assert ws.root == tmp_path.resolve()

    def test_workspace_is_cached(self, tmp_path):
        from molmcp.providers.molexp import MolexpProvider

        provider = MolexpProvider(workspace=tmp_path)
        first = provider._get_workspace()
        second = provider._get_workspace()
        assert first is second


class TestMolexpListProjects:
    def test_lists_projects(self):
        ws = _populated_workspace()
        server = _build_server(ws)
        out = _tool(server, "molexp_list_projects")()
        assert any(p["id"] == "proj-x" for p in out)

    def test_empty_workspace_returns_empty_list(self):
        ws = _FakeWorkspace()
        server = _build_server(ws)
        out = _tool(server, "molexp_list_projects")()
        assert out == []

    def test_project_metadata_defaults(self):
        """Projects without explicit name/description still render."""
        ws = _FakeWorkspace()
        ws._projects["bare"] = _make_project(pid="bare")
        server = _build_server(ws)
        out = _tool(server, "molexp_list_projects")()
        row = next(p for p in out if p["id"] == "bare")
        assert row["name"] == "bare"  # falls back to id
        assert row["description"] == ""


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

    def test_experiment_scope_forwards_filter(self):
        """When scope_kind='experiment', the catalog query filters by id."""
        ws, captured = _recording_workspace()
        server = _build_server(ws)
        _tool(server, "molexp_list_runs")(
            scope_kind="experiment", scope_id="exp-zz", status="running", limit=10
        )
        assert captured == {
            "experiment_id": "exp-zz",
            "status": "running",
            "limit": 10,
        }

    def test_experiment_scope_empty_id_treated_as_none(self):
        ws, captured = _recording_workspace()
        server = _build_server(ws)
        _tool(server, "molexp_list_runs")(scope_kind="experiment", scope_id="")
        assert captured["experiment_id"] is None

    def test_workspace_scope_passes_status_to_query(self):
        ws, captured = _recording_workspace()
        server = _build_server(ws)
        _tool(server, "molexp_list_runs")(scope_kind="workspace", status="failed")
        assert captured["status"] == "failed"
        assert "experiment_id" not in captured

    def test_limit_caps_results(self):
        """The post-filter loop honors ``limit`` even when the catalog
        returns more rows."""
        ws = _FakeWorkspace()
        ws._catalog_runs = [
            {
                "run_id": f"r{i}",
                "experiment_id": "e",
                "project_id": "p",
                "status": "ok",
                # Non-empty parameters block the on-disk fallback path
                # so _enriched_run_row does not try to walk the project.
                "parameters": {"i": i},
            }
            for i in range(5)
        ]
        server = _build_server(ws)
        rows = _tool(server, "molexp_list_runs")(
            scope_kind="workspace", limit=2
        )
        assert len(rows) == 2
