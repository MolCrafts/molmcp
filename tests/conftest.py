"""Shared pytest fixtures for molmcp tests."""

from __future__ import annotations

import json

import pytest

from molmcp import CollectionIndex, SourceBinding, create_server
from molmcp.discovery import DiscoveryConfig
from molmcp.discovery.engine import DiscoveryEngine
from molmcp.registry import Registry


@pytest.fixture
def server(tmp_path):
    """A vNext server with the in-tree fixture package as one collection source."""
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
    return create_server(
        "test",
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
