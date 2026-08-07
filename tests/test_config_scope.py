"""What an unconfigured molmcp indexes.

The old default added the current working directory as a source, so every
invocation indexed whatever happened to be around it. On one real install
that pulled in two unrelated repositories, the whole of /private/tmp, a
monorepo root, and a handful of pytest temp directories — 51 source specs
and about 10 GB of cache. Scope is now explicit.
"""

from __future__ import annotations

import json

import pytest

from molmcp import settings as st
from molmcp.config import AppConfig, load_config


@pytest.fixture
def home(tmp_path, monkeypatch):
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setattr(st.Path, "home", staticmethod(lambda: fake))
    return fake


def _write_settings(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class TestWorkspaceIsNotIndexedByDefault:
    def test_cwd_is_not_a_source(self, home, tmp_path):
        config = AppConfig.default(tmp_path)

        assert config.sources == {}

    def test_only_discovered_family_packages_are_indexed(self, home, tmp_path):
        config = AppConfig.default(tmp_path, discovered=[("molpy", "pkg:molpy")])

        assert config.sources == {"molpy": "pkg:molpy"}

    def test_opting_in_restores_the_workspace_source(self, home, tmp_path):
        _write_settings(st.user_settings_path(), {"indexWorkspace": True})

        config = AppConfig.default(tmp_path, settings=st.load_settings())

        assert config.sources == {"workspace": str(tmp_path.resolve())}


class TestSettingsSources:
    def test_configured_sources_are_indexed(self, home, tmp_path):
        _write_settings(
            st.user_settings_path(), {"sources": {"atomiverse": "pkg:atomiverse"}}
        )

        config = AppConfig.default(tmp_path, settings=st.load_settings())

        assert config.sources == {"atomiverse": "pkg:atomiverse"}

    def test_an_explicit_source_overrides_a_discovered_one(self, home, tmp_path):
        _write_settings(st.user_settings_path(), {"sources": {"molpy": "vendor/molpy"}})

        config = AppConfig.default(
            tmp_path,
            discovered=[("molpy", "pkg:molpy")],
            settings=st.load_settings(),
        )

        # A relative spec resolves against the workspace root.
        assert config.sources == {"molpy": str(tmp_path.resolve() / "vendor/molpy")}

    def test_excludes_and_watch_come_from_settings(self, home, tmp_path):
        _write_settings(
            st.user_settings_path(), {"excludes": ["vendor"], "watch": False}
        )

        config = AppConfig.default(tmp_path, settings=st.load_settings())

        assert config.excludes == ("vendor",)
        assert config.watch is False


class TestDuplicateDistributions:
    """The same distribution can appear twice on sys.path.

    A real install produced ``molcrafts-mollog`` and ``molcrafts-mollog-2``
    both pointing at ``pkg:mollog``: one distribution, indexed and searched
    twice on every query.
    """

    def test_a_repeated_spec_is_indexed_once(self, home, tmp_path):
        config = AppConfig.default(
            tmp_path,
            discovered=[("mollog", "pkg:mollog"), ("mollog", "pkg:mollog")],
        )

        assert config.sources == {"mollog": "pkg:mollog"}

    def test_distinct_specs_sharing_a_name_still_both_appear(self, home, tmp_path):
        config = AppConfig.default(
            tmp_path,
            discovered=[("molpy", "pkg:x"), ("molpy", "pkg:y")],
        )

        assert config.sources == {"molpy": "pkg:x", "molpy-2": "pkg:y"}


class TestLoadConfigNoLongerReadsCwd:
    def test_a_stray_molcrafts_json_is_ignored(self, home, tmp_path, monkeypatch):
        """Picking up ./molcrafts.json was the same cwd dependence again."""
        (tmp_path / "molcrafts.json").write_text(
            json.dumps({"schema_version": "2", "sources": {"stray": str(tmp_path)}}),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "molmcp.environment.discover_sources",
            lambda locator=None, **kwargs: _EmptyReport(),
        )

        config = load_config()

        assert "stray" not in config.sources

    def test_an_explicit_config_path_is_still_honoured(self, home, tmp_path):
        path = tmp_path / "custom.json"
        path.write_text(
            json.dumps({"schema_version": "2", "sources": {"project": str(tmp_path)}}),
            encoding="utf-8",
        )

        config = load_config(path)

        assert config.sources == {"project": str(tmp_path.resolve())}


class _EmptyReport:
    def to_dict(self):
        return {}

    sources: tuple = ()
