"""``molmcp [serve]`` CLI tests — focused on the ``--pkg`` package filter.

``--pkg NAME[,NAME...]`` narrows what the server loads to the chosen
MolCrafts packages: it picks the discovery sources *and* the
entry-point providers that get registered.
"""

from __future__ import annotations

from molmcp import cli, server
from molmcp.cli import main

# -- --pkg value normalization ------------------------------------------


def test_split_pkg_values_comma_and_repeatable():
    # ``--pkg molpy,molexp`` and ``--pkg molpy --pkg molexp`` are equal.
    assert cli._split_pkg_values(["molpy,molexp"]) == ["molpy", "molexp"]
    assert cli._split_pkg_values(["molpy", "molexp"]) == ["molpy", "molexp"]


def test_split_pkg_values_strips_and_dedupes():
    assert cli._split_pkg_values([" molpy , molexp ", "molpy"]) == [
        "molpy",
        "molexp",
    ]


def test_split_pkg_values_drops_empties():
    assert cli._split_pkg_values(["", " ,molpy, "]) == ["molpy"]


# -- source resolution --------------------------------------------------


def test_source_for_package_repo_is_github_only(monkeypatch):
    monkeypatch.setattr(cli, "_is_importable", lambda pkg: True)
    # molnex is a multi-package repo: always GitHub, never pkg:.
    assert cli._source_for_package("molnex") == "github:MolCrafts/molnex"


def test_source_for_package_local_first(monkeypatch):
    monkeypatch.setattr(cli, "_is_importable", lambda pkg: pkg == "molpy")
    assert cli._source_for_package("molpy") == "pkg:molpy"
    assert cli._source_for_package("molexp") == "github:MolCrafts/molexp"


def test_resolve_serve_sources_default(monkeypatch):
    monkeypatch.setattr(cli, "_is_importable", lambda pkg: False)
    assert cli._resolve_serve_sources([], []) == cli._available_default_sources()


def test_resolve_serve_sources_pkg_subset(monkeypatch):
    monkeypatch.setattr(cli, "_is_importable", lambda pkg: False)
    assert cli._resolve_serve_sources(["molpy", "molexp"], []) == [
        "github:MolCrafts/molpy",
        "github:MolCrafts/molexp",
    ]


def test_resolve_serve_sources_explicit_source_wins(monkeypatch):
    # An explicit --source overrides the --pkg-derived default for sources
    # (provider filtering still honors --pkg, asserted separately).
    monkeypatch.setattr(cli, "_is_importable", lambda pkg: False)
    assert cli._resolve_serve_sources(["molpy"], ["/some/path"]) == ["/some/path"]


# -- _serve_main wiring -------------------------------------------------


def _patch_create_server(monkeypatch) -> dict:
    """Capture create_server kwargs; return a fake server that no-ops run()."""
    captured: dict = {}

    class _FakeServer:
        def run(self, **kw):
            captured["run_kwargs"] = kw

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeServer()

    monkeypatch.setattr(cli, "create_server", _fake_create)
    monkeypatch.setattr(cli, "_is_importable", lambda pkg: False)
    return captured


def test_serve_main_pkg_filters_sources_and_providers(monkeypatch):
    captured = _patch_create_server(monkeypatch)
    assert main(["--pkg", "molpy,molexp"]) == 0
    assert captured["discovery_sources"] == [
        "github:MolCrafts/molpy",
        "github:MolCrafts/molexp",
    ]
    assert captured["provider_names"] == {"molpy", "molexp"}


def test_serve_main_no_pkg_means_no_provider_filter(monkeypatch):
    captured = _patch_create_server(monkeypatch)
    assert main([]) == 0
    assert captured["discovery_sources"] == cli._available_default_sources()
    assert captured["provider_names"] is None


def test_serve_main_explicit_source_keeps_pkg_provider_filter(monkeypatch):
    captured = _patch_create_server(monkeypatch)
    assert main(["--pkg", "molpy", "--source", "/repo"]) == 0
    assert captured["discovery_sources"] == ["/repo"]
    assert captured["provider_names"] == {"molpy"}


# -- create_server provider_names filter --------------------------------


class _FakeProvider:
    def __init__(self, name: str):
        self.name = name
        self.registered = False

    def register(self, mcp) -> None:  # noqa: ARG002 — interface shape
        self.registered = True


def _make_server_with_fake_providers(monkeypatch, provs, **kwargs):
    monkeypatch.setattr(server, "discover_providers", lambda: provs)
    return server.create_server(
        discovery_sources=None,
        discover_entry_points=True,
        enable_path_safety=False,
        enable_response_limit=False,
        validate_annotations=False,
        **kwargs,
    )


def test_create_server_provider_names_filters_auto(monkeypatch):
    provs = [_FakeProvider("molpy"), _FakeProvider("molexp"), _FakeProvider("lammps")]
    _make_server_with_fake_providers(monkeypatch, provs, provider_names={"molpy"})
    assert [p.name for p in provs if p.registered] == ["molpy"]


def test_create_server_no_provider_names_registers_all(monkeypatch):
    provs = [_FakeProvider("molpy"), _FakeProvider("molexp")]
    _make_server_with_fake_providers(monkeypatch, provs, provider_names=None)
    assert all(p.registered for p in provs)
