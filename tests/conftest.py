"""Shared pytest fixtures for molmcp tests."""

from __future__ import annotations

import json

import pytest

from molmcp import create_server
from molmcp.discovery import DiscoveryConfig


@pytest.fixture
def server(tmp_path):
    """A server with discovery bound to the in-tree fixture_pkg."""
    return create_server(
        "test",
        discovery_sources=["pkg:fixture_pkg"],
        discovery_config=DiscoveryConfig(cache_dir=tmp_path / "discovery-cache"),
        discover_entry_points=False,
    )


async def call(server, tool: str, args: dict | None = None):
    """Helper: invoke ``tool`` and return a Python-friendly result."""
    result = await server.call_tool(tool, args or {})
    if not result.content:
        sc = result.structured_content
        return sc.get("result") if sc else None
    text = result.content[0].text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
