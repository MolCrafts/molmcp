"""Layered molmcp settings — the control surface for what gets indexed.

Modelled on Claude Code: a user file at ``~/.molmcp/settings.json``, an
optional checked-in project file, and an untracked local override, merged
in that order. Unlike Claude Code the *user* file is the primary surface,
because a plane server is launched by an MCP client whose working
directory is arbitrary.
"""

from __future__ import annotations

import json

import pytest

from molmcp import settings as st


@pytest.fixture
def home(tmp_path, monkeypatch):
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setattr(st.Path, "home", staticmethod(lambda: fake))
    return fake


def _write(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class TestSettingsLocations:
    def test_user_settings_live_under_a_dot_molmcp_home_directory(self, home):
        assert st.user_settings_path() == home / ".molmcp" / "settings.json"

    def test_project_settings_live_beside_the_project(self, home, tmp_path):
        project = tmp_path / "repo"
        assert (
            st.project_settings_path(project) == project / ".molmcp" / "settings.json"
        )
        assert (
            st.project_settings_path(project, local=True)
            == project / ".molmcp" / "settings.local.json"
        )


class TestSettingsMerge:
    def test_missing_files_yield_documented_defaults(self, home, tmp_path):
        loaded = st.load_settings(tmp_path / "repo")

        assert loaded.sources == {}
        assert loaded.index_workspace is False

    def test_project_overrides_user(self, home, tmp_path):
        _write(st.user_settings_path(), {"indexWorkspace": True})
        project = tmp_path / "repo"
        _write(st.project_settings_path(project), {"indexWorkspace": False})

        assert st.load_settings(project).index_workspace is False

    def test_local_overrides_project(self, home, tmp_path):
        project = tmp_path / "repo"
        _write(st.project_settings_path(project), {"indexWorkspace": False})
        _write(st.project_settings_path(project, local=True), {"indexWorkspace": True})

        assert st.load_settings(project).index_workspace is True

    def test_sources_merge_across_layers_rather_than_replacing(self, home, tmp_path):
        _write(st.user_settings_path(), {"sources": {"molpy": "pkg:molpy"}})
        project = tmp_path / "repo"
        _write(st.project_settings_path(project), {"sources": {"local": "./src"}})

        assert st.load_settings(project).sources == {
            "molpy": "pkg:molpy",
            "local": "./src",
        }

    def test_a_later_layer_can_shadow_one_source_name(self, home, tmp_path):
        _write(st.user_settings_path(), {"sources": {"molpy": "pkg:molpy"}})
        project = tmp_path / "repo"
        _write(st.project_settings_path(project), {"sources": {"molpy": "./vendor"}})

        assert st.load_settings(project).sources == {"molpy": "./vendor"}

    def test_excludes_accumulate_across_layers(self, home, tmp_path):
        _write(st.user_settings_path(), {"excludes": ["*.min.js"]})
        project = tmp_path / "repo"
        _write(st.project_settings_path(project), {"excludes": ["vendor"]})

        assert st.load_settings(project).excludes == ("*.min.js", "vendor")

    def test_unreadable_settings_are_reported_not_swallowed(self, home, tmp_path):
        path = st.user_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")

        with pytest.raises(st.SettingsError) as excinfo:
            st.load_settings(tmp_path / "repo")

        assert str(path) in str(excinfo.value)

    def test_unknown_keys_are_rejected_so_typos_do_not_go_silent(self, home, tmp_path):
        _write(st.user_settings_path(), {"indexWorkspaces": True})

        with pytest.raises(st.SettingsError) as excinfo:
            st.load_settings(tmp_path / "repo")

        assert "indexWorkspaces" in str(excinfo.value)


class TestSettingsEdit:
    def test_set_creates_the_file_and_the_directory(self, home):
        st.set_value(st.user_settings_path(), "indexWorkspace", "true")

        assert json.loads(st.user_settings_path().read_text()) == {
            "indexWorkspace": True
        }

    def test_set_a_nested_source_by_dotted_key(self, home):
        st.set_value(st.user_settings_path(), "sources.molpy", "pkg:molpy")

        assert json.loads(st.user_settings_path().read_text()) == {
            "sources": {"molpy": "pkg:molpy"}
        }

    def test_add_appends_to_a_list_valued_key(self, home):
        st.add_value(st.user_settings_path(), "excludes", "vendor")
        st.add_value(st.user_settings_path(), "excludes", "*.min.js")

        assert json.loads(st.user_settings_path().read_text()) == {
            "excludes": ["vendor", "*.min.js"]
        }

    def test_add_is_idempotent(self, home):
        st.add_value(st.user_settings_path(), "excludes", "vendor")
        st.add_value(st.user_settings_path(), "excludes", "vendor")

        assert json.loads(st.user_settings_path().read_text())["excludes"] == ["vendor"]

    def test_remove_drops_a_key(self, home):
        st.set_value(st.user_settings_path(), "sources.molpy", "pkg:molpy")
        st.set_value(st.user_settings_path(), "sources.molvis", "pkg:molvis")

        st.remove_value(st.user_settings_path(), "sources.molpy")

        assert json.loads(st.user_settings_path().read_text()) == {
            "sources": {"molvis": "pkg:molvis"}
        }

    def test_remove_reports_an_absent_key(self, home):
        with pytest.raises(st.SettingsError):
            st.remove_value(st.user_settings_path(), "sources.nope")

    def test_set_rejects_an_unknown_key(self, home):
        with pytest.raises(st.SettingsError):
            st.set_value(st.user_settings_path(), "indexWorkspaces", "true")

    def test_booleans_and_integers_are_parsed_from_the_command_line(self, home):
        st.set_value(st.user_settings_path(), "indexWorkspace", "false")
        st.set_value(st.user_settings_path(), "maxCacheBytes", "1048576")

        data = json.loads(st.user_settings_path().read_text())
        assert data["indexWorkspace"] is False
        assert data["maxCacheBytes"] == 1048576
