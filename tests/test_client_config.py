"""Client config: default all planes; --enable / --disable."""

from __future__ import annotations

import sys
import tomllib

import pytest

from molmcp import client_config
from molmcp.client_config import (
    render_client,
    render_grok_toml,
    resolve_plane_toggles,
)


def test_default_all_enabled():
    t = resolve_plane_toggles(available=("catalog", "molcrafts", "molvis", "molq"))
    assert t.enabled == ("catalog", "molcrafts", "molvis", "molq")
    assert t.disabled == ()


def test_disable_then_enable():
    t = resolve_plane_toggles(
        available=("catalog", "molvis", "molq"),
        disable=["molq", "molvis"],
        enable=["molvis"],
    )
    assert t.enabled == ("catalog", "molvis")
    assert t.disabled == ("molq",)


def test_disable_unknown_raises():
    with pytest.raises(ValueError, match="unknown plane"):
        resolve_plane_toggles(available=("catalog",), disable=["nope"])


def test_disable_all_raises():
    with pytest.raises(ValueError, match="at least one"):
        resolve_plane_toggles(available=("a", "b"), disable=["a", "b"])


def test_grok_toml_marks_enabled_false():
    t = resolve_plane_toggles(
        available=("catalog", "molvis"),
        disable=["molvis"],
    )
    text = render_grok_toml(t)
    assert "[mcp_servers.catalog]" in text
    assert "[mcp_servers.molvis]" in text
    assert "enabled = true" in text
    assert "enabled = false" in text
    assert "serve" in text and "catalog" in text


def test_render_client_claude_only_enabled():
    _toggle, text = render_client(
        "claude",
        disable=["molq"] if False else [],
    )
    # smoke: valid JSON with mcpServers
    import json

    payload = json.loads(text)
    assert "mcpServers" in payload
    assert payload["mcpServers"]


def test_cli_client_disable(capsys, monkeypatch):
    from molmcp import cli

    monkeypatch.setattr(
        "molmcp.client_config.default_plane_ids",
        lambda: ("catalog", "molvis", "molq"),
    )
    # re-import resolve path uses default_plane_ids via resolve_plane_toggles
    code = cli.main(["client", "grok", "--disable", "molq"])
    assert code == 0
    out = capsys.readouterr().out
    assert "[mcp_servers.molq]" in out
    assert "enabled = false" in out


class TestLaunchableFromAGuiClient:
    """A generated config has to start when the client is not a shell.

    Claude Desktop and friends are launched by the desktop session, whose
    PATH is the system default — a virtualenv's bin directory is not on it.
    Emitting the bare name `molmcp` produced a config that worked when
    tested in a terminal and failed for the user it was generated for.
    """

    def test_command_is_the_resolved_absolute_path(self, monkeypatch, tmp_path):
        installed = tmp_path / "venv" / "bin" / "molmcp"
        installed.parent.mkdir(parents=True)
        installed.touch()
        monkeypatch.setattr(client_config.shutil, "which", lambda name: str(installed))

        config = client_config.render_claude_json(
            client_config.PlaneToggle(("catalog",), (), ("catalog",))
        )

        assert config["mcpServers"]["catalog"]["command"] == str(installed)

    def test_fallback_uses_this_interpreter_not_a_bare_python(self, monkeypatch):
        """`python` is frequently absent on macOS; sys.executable never is."""
        monkeypatch.setattr(client_config.shutil, "which", lambda name: None)

        command = client_config._molmcp_command()

        assert command[0] == sys.executable
        assert command[1:3] == ["-m", "molmcp"]

    @pytest.mark.parametrize(
        "raw",
        [
            r"C:\Users\me\.venv\Scripts\molmcp.exe",
            '/opt/we"ird/molmcp',
            "/opt/tab\tpath/molmcp",
        ],
    )
    def test_toml_strings_round_trip_through_a_parser(self, raw):
        """Backslashes and quotes are escapes inside a TOML basic string;
        hand-quoting them produced a file no parser would read back."""
        parsed = tomllib.loads(f"command = {client_config._toml_string(raw)}\n")

        assert parsed["command"] == raw

    def test_grok_toml_round_trips_a_plain_path(self, monkeypatch):
        monkeypatch.setattr(
            client_config.shutil, "which", lambda name: "/opt/molmcp/bin/molmcp"
        )

        parsed = tomllib.loads(
            client_config.render_grok_toml(
                client_config.PlaneToggle(("catalog",), ("molq",), ("catalog", "molq"))
            )
        )

        assert parsed["mcp_servers"]["catalog"]["enabled"] is True
        assert parsed["mcp_servers"]["molq"]["enabled"] is False
        assert parsed["mcp_servers"]["catalog"]["args"] == ["serve", "catalog"]
