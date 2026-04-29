"""Tests for ``molmcp-lammps`` CLI."""

from __future__ import annotations

import pytest

pytest.importorskip("molmcp", reason="molcrafts-molmcp not installed")
pytest.importorskip("fastmcp", reason="fastmcp not installed")

from molmcp_lammps.cli import build_parser, main  # noqa: E402


def test_doc_update_dispatches_to_run(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(*, check: bool, version: str) -> int:
        captured["check"] = check
        captured["version"] = version
        return 0

    monkeypatch.setattr(
        "molmcp_lammps._dev.lammps_slugs.run", fake_run
    )
    assert main(["doc", "update", "--check", "--version", "latest"]) == 0
    assert captured == {"check": True, "version": "latest"}


def test_doc_update_defaults_to_stable(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(*, check: bool, version: str) -> int:
        captured["check"] = check
        captured["version"] = version
        return 0

    monkeypatch.setattr(
        "molmcp_lammps._dev.lammps_slugs.run", fake_run
    )
    assert main(["doc", "update"]) == 0
    assert captured == {"check": False, "version": "stable"}


def test_doc_without_action_exits() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["doc"])
