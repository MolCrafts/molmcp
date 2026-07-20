from __future__ import annotations

import json

import pytest

from molmcp import CollectionIndex, Registry, create_server, runtime
from molmcp.config import AppConfig, RegistrySourceConfig
from molmcp.discovery.config import DEFAULT_EXCLUDES
from molmcp.registry import RegistryConflictError


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


def test_file_registry_cannot_escape_configured_namespace(tmp_path, monkeypatch):
    manifest = tmp_path / "molcrafts.registry.json"
    manifest.write_text(
        json.dumps({"schema_version": "1", "items": [_concept("@molexp/run")]}),
        encoding="utf-8",
    )
    config = AppConfig.from_dict(
        {
            "schema_version": "1",
            "registries": [
                {
                    "kind": "file",
                    "location": str(manifest),
                    "namespace": "@molpack",
                }
            ],
        },
        workspace_root=tmp_path,
    )
    monkeypatch.setattr(runtime, "load_installed_manifests", lambda **kwargs: [])
    with pytest.raises(RegistryConflictError, match="foreign registry id"):
        runtime.build_registry(config)


def test_registry_expected_digest_mismatch_fails_closed(tmp_path, monkeypatch):
    manifest = tmp_path / "molcrafts.registry.json"
    manifest.write_text(
        json.dumps({"schema_version": "1", "items": [_concept("@molpack/pack")]}),
        encoding="utf-8",
    )
    config = AppConfig.from_dict(
        {
            "schema_version": "1",
            "registries": [
                {
                    "kind": "file",
                    "location": str(manifest),
                    "namespace": "@molpack",
                    "expected_digest": "0" * 64,
                }
            ],
        },
        workspace_root=tmp_path,
    )
    monkeypatch.setattr(runtime, "load_installed_manifests", lambda **kwargs: [])
    with pytest.raises(ValueError, match="does not match expected_digest"):
        runtime.build_registry(config)


def test_url_registry_is_https_non_redirecting_and_secret_safe(monkeypatch):
    raw = json.dumps({"schema_version": "1", "items": []}).encode()
    captured: dict[str, object] = {}

    class Headers:
        @staticmethod
        def get_content_type():
            return "application/json"

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            captured["read_size"] = size
            return raw

    class Opener:
        def open(self, request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["timeout"] = timeout
            return Response()

    monkeypatch.setenv("REGISTRY_TOKEN", "super-secret")
    monkeypatch.setattr(runtime.urllib.request, "build_opener", lambda *args: Opener())
    source = RegistrySourceConfig(
        kind="url",
        location="https://registry.example/{namespace}/manifest.json",
        namespace="@molpack",
        headers={"Authorization": "Bearer ${REGISTRY_TOKEN}"},
    )
    loaded = runtime._load_url_manifest(source)
    assert loaded.source == "https://registry.example/molpack/manifest.json"
    assert captured["authorization"] == "Bearer super-secret"
    assert "super-secret" not in repr(loaded)


@pytest.mark.parametrize(
    "location", ["http://example.test/x", "file:///tmp/x", "https://u:p@host/x"]
)
def test_direct_remote_loader_rejects_unsafe_urls(location):
    with pytest.raises(ValueError, match="HTTPS URL"):
        runtime._load_url_manifest(RegistrySourceConfig(kind="url", location=location))


def test_remote_redirects_are_rejected():
    with pytest.raises(ValueError, match="redirects are not allowed"):
        runtime._RejectRedirects().redirect_request(
            None, None, 302, "Found", {}, "https://other.example/manifest.json"
        )


def test_custom_excludes_extend_safety_defaults(tmp_path):
    config = AppConfig.from_dict(
        {"schema_version": "1", "excludes": ["generated"]},
        workspace_root=tmp_path,
    )
    collection = runtime.build_collection(config, Registry())
    excludes = collection.sources[0].engine.config.excludes
    assert set(DEFAULT_EXCLUDES).issubset(excludes)
    assert "generated" in excludes


def test_explicit_config_is_not_ignored_with_injected_collection(tmp_path, monkeypatch):
    monkeypatch.setenv("MOLMCP_TOKEN", "secret")
    config = AppConfig.from_dict(
        {
            "schema_version": "1",
            "server": {"auth_token_env": "MOLMCP_TOKEN"},
        },
        workspace_root=tmp_path,
    )
    server = create_server(
        collection=CollectionIndex([], Registry()),
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
            "schema_version": "1",
            "server": {"auth_token_env": "MOLMCP_TOKEN"},
        },
        workspace_root=tmp_path,
    )
    server = create_server(
        collection=CollectionIndex([], Registry()),
        config=config,
        discover_entry_points=False,
    )
    assert await server.auth.verify_token("secret") is not None
    assert await server.auth.verify_token("wrong") is None
