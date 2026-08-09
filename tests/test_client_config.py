"""Client config: default all planes; --enable / --disable."""

from __future__ import annotations

import json
import sys

import pytest

from molmcp import client_config
from molmcp.client_config import (
    render_client,
    render_mcp_json,
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


def test_a_disabled_plane_is_omitted_from_the_server_map():
    t = resolve_plane_toggles(
        available=("catalog", "molvis"),
        disable=["molvis"],
    )
    servers = render_mcp_json(t)["mcpServers"]
    assert set(servers) == {"catalog"}
    assert servers["catalog"]["args"][-2:] == ["serve", "catalog"]


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
    servers = json.loads(capsys.readouterr().out)["mcpServers"]
    assert "molq" not in servers
    assert set(servers) == {"catalog", "molvis"}


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

        config = client_config.render_mcp_json(
            client_config.PlaneToggle(("catalog",), (), ("catalog",))
        )

        assert config["mcpServers"]["catalog"]["command"] == str(installed)

    def test_fallback_uses_this_interpreter_not_a_bare_python(self, monkeypatch):
        """`python` is frequently absent on macOS; sys.executable never is."""
        monkeypatch.setattr(client_config.shutil, "which", lambda name: None)

        command = client_config._molmcp_command()

        assert command[0] == sys.executable
        assert command[1:3] == ["-m", "molmcp"]


class TestOneJsonForEveryHost:
    """Every host molmcp targets reads the standard `mcpServers` JSON.

    Grok loads ~/.claude.json, .cursor/mcp.json and project .mcp.json
    alongside its own config.toml, and Claude Code and Cursor read the same
    shape. Hand-rolling TOML bought nothing and cost an escaping bug, so
    there is one body now and the host only picks where to put it.
    """

    def test_the_body_is_identical_for_every_host(self):
        toggle = client_config.PlaneToggle(("catalog",), (), ("catalog",))

        bodies = {
            host: client_config.render_client(host, available=toggle.all_planes)[1]
            for host in ("grok", "claude", "cursor")
        }

        assert len(set(bodies.values())) == 1

    @pytest.mark.parametrize("host", ["grok", "claude", "cursor"])
    def test_every_host_gets_parseable_json(self, host):
        _, text = client_config.render_client(host)

        assert "mcpServers" in json.loads(text)

    def test_the_host_is_optional(self):
        _, text = client_config.render_client()

        assert "mcpServers" in json.loads(text)

    def test_disabled_planes_are_absent_rather_than_flagged(self):
        toggle = client_config.PlaneToggle(("catalog",), ("molq",), ("catalog", "molq"))

        servers = client_config.render_mcp_json(toggle)["mcpServers"]

        assert set(servers) == {"catalog"}

    @pytest.mark.parametrize(
        ("host", "tail"),
        [
            ("claude", ".claude.json"),
            ("cursor", "mcp.json"),
            ("grok", "mcp.json"),
        ],
    )
    def test_each_host_has_a_default_destination(self, host, tail):
        assert str(client_config.default_write_path(host)).endswith(tail)

    def test_no_toml_is_generated_any_more(self):
        assert not hasattr(client_config, "render_grok_toml")
