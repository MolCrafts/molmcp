from __future__ import annotations

import pytest

from molmcp.registry import ManifestError, load_manifest_data
from molmcp.registry import entrypoints as entrypoint_module


def _item(identifier: str) -> dict:
    namespace = identifier.split("/", 1)[0].removeprefix("@")
    return {
        "schema_version": "1",
        "id": identifier,
        "kind": "concept",
        "title": "Item",
        "summary": "Item summary.",
        "package": namespace,
        "package_version": "1.0.0",
        "tags": [],
        "aliases": [],
        "examples": [],
        "provenance": {
            "source_uri": f"https://example.test/{namespace}",
            "revision": "abc123",
            "declarer": namespace,
        },
    }


class EntryPoint:
    def __init__(self, name, manifest, loaded):
        self.name = name
        self.manifest = manifest
        self.loaded = loaded

    def load(self):
        self.loaded.append(self.name)
        return lambda: self.manifest


def test_namespace_filter_loads_only_matching_entry_point(monkeypatch):
    loaded: list[str] = []
    molpack = load_manifest_data(
        {"schema_version": "1", "items": [_item("@molpack/pack")]}
    )
    molpy = load_manifest_data({"schema_version": "1", "items": [_item("@molpy/rdf")]})
    entry_points = [
        EntryPoint("molpy", molpy, loaded),
        EntryPoint("molpack", molpack, loaded),
    ]
    monkeypatch.setattr(
        entrypoint_module.importlib.metadata,
        "entry_points",
        lambda **kwargs: entry_points,
    )
    result = entrypoint_module.load_installed_manifests("@molpack")
    assert result[0].digest == molpack.digest
    assert result[0].items == molpack.items
    assert result[0].source == "entrypoint:molpack"
    assert loaded == ["molpack"]


def test_entry_point_cannot_declare_foreign_namespace(monkeypatch):
    loaded: list[str] = []
    manifest = load_manifest_data(
        {"schema_version": "1", "items": [_item("@molexp/run")]}
    )
    monkeypatch.setattr(
        entrypoint_module.importlib.metadata,
        "entry_points",
        lambda **kwargs: [EntryPoint("molpack", manifest, loaded)],
    )
    with pytest.raises(ManifestError, match="foreign registry id"):
        entrypoint_module.load_installed_manifests()


def test_duplicate_entry_point_names_fail_before_loading(monkeypatch):
    loaded: list[str] = []
    manifest = load_manifest_data(
        {"schema_version": "1", "items": [_item("@molpack/pack")]}
    )
    monkeypatch.setattr(
        entrypoint_module.importlib.metadata,
        "entry_points",
        lambda **kwargs: [
            EntryPoint("molpack", manifest, loaded),
            EntryPoint("molpack", manifest, loaded),
        ],
    )
    with pytest.raises(ManifestError, match="duplicate capability entry-point"):
        entrypoint_module.load_installed_manifests()
    assert loaded == []
