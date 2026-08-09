"""`molmcp config` — the CLI half of the settings surface.

Verb shape follows ``claude config``: list / get / set / add / remove.
The scope default is the one deliberate departure — writes land in the
user file unless ``--project`` is passed, because a plane server's working
directory belongs to whichever MCP client launched it.
"""

from __future__ import annotations

import json

import pytest

from molmcp import cli
from molmcp import settings as st


@pytest.fixture
def home(tmp_path, monkeypatch):
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setattr(st.Path, "home", staticmethod(lambda: fake))
    return fake


def _user_settings() -> dict:
    path = st.user_settings_path()
    return json.loads(path.read_text()) if path.is_file() else {}


class TestConfigScope:
    def test_set_writes_the_user_file_by_default(self, home, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)

        assert cli.main(["config", "set", "indexWorkspace", "true"]) == 0

        assert _user_settings() == {"indexWorkspace": True}

    def test_project_flag_writes_beside_the_project(self, home, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)

        assert cli.main(["config", "set", "--project", "indexWorkspace", "true"]) == 0

        assert _user_settings() == {}
        written = st.project_settings_path(tmp_path)
        assert json.loads(written.read_text()) == {"indexWorkspace": True}

    def test_local_flag_writes_the_untracked_override(
        self, home, monkeypatch, tmp_path
    ):
        monkeypatch.chdir(tmp_path)

        assert cli.main(["config", "set", "--local", "indexWorkspace", "true"]) == 0

        written = st.project_settings_path(tmp_path, local=True)
        assert json.loads(written.read_text()) == {"indexWorkspace": True}


class TestConfigVerbs:
    def test_list_reports_the_resolved_settings_and_their_layers(
        self, home, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.chdir(tmp_path)
        cli.main(["config", "set", "sources.molpy", "pkg:molpy"])
        capsys.readouterr()

        assert cli.main(["config", "list"]) == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload["sources"] == {"molpy": "pkg:molpy"}
        assert str(st.user_settings_path()) in payload["layers"]

    def test_get_reads_one_key(self, home, monkeypatch, tmp_path, capsys):
        monkeypatch.chdir(tmp_path)
        cli.main(["config", "set", "sources.molpy", "pkg:molpy"])
        capsys.readouterr()

        assert cli.main(["config", "get", "sources.molpy"]) == 0

        assert json.loads(capsys.readouterr().out) == "pkg:molpy"

    def test_get_an_unset_key_is_null_not_an_error(
        self, home, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.chdir(tmp_path)

        assert cli.main(["config", "get", "cacheDir"]) == 0

        assert json.loads(capsys.readouterr().out) is None

    def test_add_appends_to_a_list(self, home, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)

        cli.main(["config", "add", "excludes", "vendor"])
        cli.main(["config", "add", "excludes", "*.min.js"])

        assert _user_settings()["excludes"] == ["vendor", "*.min.js"]

    def test_remove_drops_a_source(self, home, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        cli.main(["config", "set", "sources.molpy", "pkg:molpy"])

        assert cli.main(["config", "remove", "sources.molpy"]) == 0

        assert _user_settings() == {"sources": {}}


class TestConfigErrors:
    def test_an_unknown_key_is_rejected_with_the_known_ones(
        self, home, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.chdir(tmp_path)

        assert cli.main(["config", "set", "indexWorkspaces", "true"]) == 2

        err = capsys.readouterr().err
        assert err.startswith("molmcp:")
        assert "indexWorkspace" in err

    def test_a_non_boolean_for_a_boolean_key_is_rejected(
        self, home, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.chdir(tmp_path)

        assert cli.main(["config", "set", "indexWorkspace", "maybe"]) == 2

        assert "boolean" in capsys.readouterr().err

    def test_removing_an_absent_key_is_reported(
        self, home, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.chdir(tmp_path)

        assert cli.main(["config", "remove", "sources.nope"]) == 2

        assert capsys.readouterr().err.startswith("molmcp:")
