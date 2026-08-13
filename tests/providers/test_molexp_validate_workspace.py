"""``validate_workspace`` returns molexp's agent-facing error report."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("molexp")


def _workspace(tmp_path: Path):
    from molexp.workspace import Workspace

    ws = Workspace(tmp_path / "lab")
    ws.materialize()
    ws.add_project("alpha").add_experiment("sweep").add_run(params={"t": 1})
    return ws


def test_validate_workspace_report_shape(tmp_path: Path) -> None:
    from molmcp.providers.molexp.provider import MolexpProvider

    ws = _workspace(tmp_path)
    (Path(ws.resolve()) / "foreign-output").mkdir()

    provider = MolexpProvider()
    report = provider.validate_workspace(str(ws.resolve()))

    assert report["ok"] is False
    assert report["error_count"] >= 1
    assert report["path"] == report["root"] or report["path"] == str(ws.resolve())
    assert report["is_workspace"] is True
    assert report["next_actions"]
    rules = {v["rule"] for v in report["violations"]}
    assert "layout.stray" in rules
    stray = next(v for v in report["violations"] if v["rule"] == "layout.stray")
    assert stray["hint"]
    assert stray["severity"] == "error"


def test_validate_workspace_conforming_tree_is_ok(tmp_path: Path) -> None:
    from molmcp.providers.molexp.provider import MolexpProvider

    ws = _workspace(tmp_path)
    report = MolexpProvider().validate_workspace(str(ws.resolve()))
    assert report["ok"] is True
    assert report["error_count"] == 0
    assert all(v["severity"] in {"error", "warning"} for v in report["violations"])


def test_check_layout_is_gone() -> None:
    """No dual name — agents must not see a leftover check_layout."""
    from molmcp.providers.molexp.provider import MolexpProvider

    assert not hasattr(MolexpProvider, "check_layout")
