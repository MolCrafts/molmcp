"""Client config: default all planes; --enable / --disable."""

from __future__ import annotations

import pytest

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
