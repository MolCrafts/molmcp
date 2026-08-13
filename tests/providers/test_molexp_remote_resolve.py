"""Host-qualified workspace specs (``Arrhenius:/home/…``) for local MCP tools."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("molexp")


def test_is_host_qualified() -> None:
    from molmcp.providers.molexp.resolve import is_host_qualified

    assert is_host_qualified("Arrhenius:/home/jicli594/work/mace-nve")
    assert is_host_qualified("user@host:/data/ws")
    assert is_host_qualified("login.hpc.example:/scratch/ws")
    assert not is_host_qualified("/home/local/ws")
    assert not is_host_qualified("https://example.com/ws")
    assert not is_host_qualified("C:\\Users\\ws")
    assert not is_host_qualified("")


def test_validate_workspace_local_still_ok(tmp_path: Path) -> None:
    from molexp.workspace import Workspace

    from molmcp.providers.molexp.provider import MolexpProvider

    ws = Workspace(tmp_path / "lab")
    ws.materialize()
    ws.add_project("p").add_experiment("e").add_run(params={"t": 1})

    report = MolexpProvider().validate_workspace(str(ws.resolve()))
    assert report["ok"] is True
    assert report.get("remote") is False
    assert report["error_count"] == 0


def test_list_projects_via_live_workspace(tmp_path: Path) -> None:
    """Scaffold helpers accept an already-open Workspace (remote-safe)."""
    from molexp.workspace import Workspace

    from molmcp.providers.molexp.scaffold import add_project, list_experiments

    ws = Workspace(tmp_path / "lab2")
    ws.materialize()
    out = add_project(ws, "alpha")
    assert out["project_id"] == "alpha"
    exp = list_experiments(ws, "alpha")
    assert exp == []


def test_provider_init_keeps_host_qualified_string() -> None:
    from molmcp.providers.molexp.provider import MolexpProvider

    p = MolexpProvider("Arrhenius:/home/jicli594/work/mace-nve")
    assert p._workspace == "Arrhenius:/home/jicli594/work/mace-nve"
