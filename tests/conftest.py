"""Shared pytest fixtures for molmcp tests.

Provider integration tests require real optional packages (dev deps).
Runtime silent omission of missing science packages lives in
``provider.discover_providers(only_available=True)`` — not in tests.
"""

from __future__ import annotations

import json

import pytest

from molmcp import CollectionIndex, SourceBinding, create_plane
from molmcp.discovery import DiscoveryConfig
from molmcp.discovery.engine import DiscoveryEngine
from molmcp.registry import Registry


@pytest.fixture
def server(tmp_path):
    """A molcrafts-plane server with the in-tree fixture package as one source."""
    engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "discovery-cache"))
    collection = CollectionIndex(
        [
            SourceBinding(
                name="fixture",
                spec="pkg:fixture_pkg",
                engine=engine,
                namespace="fixture",
            )
        ],
        Registry(),
    )
    return create_plane(
        "molcrafts",
        collection=collection,
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
