from __future__ import annotations

import json
from pathlib import Path

from molmcp import CollectionIndex, create_plane, runtime
from molmcp.config import AppConfig, load_config
from molmcp.discovery.config import DEFAULT_EXCLUDES
from molmcp.environment import DiscoveredSource, EnvironmentReport


def _discovery_report() -> EnvironmentReport:
    return EnvironmentReport(
        locator="/envs/foo",
        is_self=False,
        site_paths=(Path("/envs/foo/lib/python3.12/site-packages"),),
        sources=(
            DiscoveredSource(
                name="molpy",
                spec="local:/envs/foo/lib/python3.12/site-packages/molpy",
                identified_by=("entry_point", "keyword"),
                distribution="molpy",
                version="1.2.3",
            ),
        ),
        skipped=("brokenpkg: no importable package directory found",),
        excluded=("moljunk",),
    )


def _load_discovered_config(tmp_path, monkeypatch) -> AppConfig:
    monkeypatch.chdir(tmp_path)
    report = _discovery_report()
    monkeypatch.setattr(
        "molmcp.environment.discover_sources", lambda locator=None, **kwargs: report
    )
    return load_config()


def _concept(identifier: str) -> dict:
    namespace = identifier.split("/", 1)[0].removeprefix("@")
    return {
        "schema_version": "1",
        "id": identifier,
        "kind": "concept",
        "title": "Example",
        "summary": "Example catalog item.",
        "package": namespace,
        "package_version": "1.2.3",
        "tags": [],
        "aliases": [],
        "examples": [],
        "provenance": {
            "source_uri": f"https://example.test/{namespace}",
            "revision": "abc123",
            "declarer": namespace,
        },
    }


def test_custom_excludes_extend_safety_defaults(tmp_path):
    config = AppConfig.from_dict(
        {"schema_version": "2", "excludes": ["generated"]},
        workspace_root=tmp_path,
    )
    collection = runtime.build_collection(config)
    excludes = collection.sources[0].engine.config.excludes
    assert set(DEFAULT_EXCLUDES).issubset(excludes)
    assert "generated" in excludes


def test_explicit_config_is_not_ignored_with_injected_collection(tmp_path, monkeypatch):
    monkeypatch.setenv("MOLMCP_TOKEN", "secret")
    config = AppConfig.from_dict(
        {
            "schema_version": "2",
            "server": {"auth_token_env": "MOLMCP_TOKEN"},
        },
        workspace_root=tmp_path,
    )
    server = create_plane(
        "molcrafts",
        collection=CollectionIndex([]),
        config=config,
        discover_entry_points=False,
    )
    assert server.auth is not None


async def test_environment_token_verifier_accepts_only_current_secret(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MOLMCP_TOKEN", "secret")
    config = AppConfig.from_dict(
        {
            "schema_version": "2",
            "server": {"auth_token_env": "MOLMCP_TOKEN"},
        },
        workspace_root=tmp_path,
    )
    server = create_plane(
        "molcrafts",
        collection=CollectionIndex([]),
        config=config,
        discover_entry_points=False,
    )
    assert await server.auth.verify_token("secret") is not None
    assert await server.auth.verify_token("wrong") is None


def test_build_collection_metadata_carries_discovery(tmp_path, monkeypatch):
    config = _load_discovered_config(tmp_path, monkeypatch)
    collection = runtime.build_collection(config)
    assert collection.metadata["discovery"] == _discovery_report().to_dict()


def test_info_configuration_surfaces_discovery(tmp_path, monkeypatch):
    config = _load_discovered_config(tmp_path, monkeypatch)
    collection = runtime.build_collection(config)
    discovery = collection.info()["configuration"]["discovery"]
    report = _discovery_report()
    assert discovery["site_paths"] == [str(path) for path in report.site_paths]
    identified = {
        source["name"]: source["identified_by"] for source in discovery["sources"]
    }
    assert identified["molpy"] == ["entry_point", "keyword"]
    assert discovery["skipped"] == list(report.skipped)
    assert discovery["excluded"] == list(report.excluded)


def test_config_summary_includes_secret_free_discovery(tmp_path, monkeypatch):
    config = _load_discovered_config(tmp_path, monkeypatch)
    text = runtime.config_summary(config)
    summary = json.loads(text)
    assert "discovery" in summary
    assert summary["discovery"]["sources"][0]["identified_by"] == [
        "entry_point",
        "keyword",
    ]
    lowered = text.lower()
    assert "secret" not in lowered
    assert "password" not in lowered
    assert "token" not in lowered
