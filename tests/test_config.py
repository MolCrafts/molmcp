from __future__ import annotations

import json

import pytest

from molmcp.config import AppConfig, ConfigurationError, load_config


def test_default_config_indexes_current_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.sources == {"workspace": str(tmp_path.resolve())}
    assert config.server.transport == "stdio"


def test_loads_and_resolves_relative_paths(tmp_path):
    path = tmp_path / "molcrafts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "sources": {"local": "./repo", "molpy": "pkg:molpy"},
                "registries": [{"kind": "file", "location": "registry.json"}],
                "cache_dir": ".cache/molmcp",
                "providers": ["molexp", "molq"],
            }
        ),
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.sources["local"] == str((tmp_path / "repo").resolve())
    assert config.sources["molpy"] == "pkg:molpy"
    assert config.registries[0].location == str((tmp_path / "registry.json").resolve())
    assert config.cache_dir == (tmp_path / ".cache/molmcp").resolve()
    assert config.providers == frozenset({"molexp", "molq"})


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "1", "unknown": True},
        {"schema_version": "2", "sources": {"x": "."}},
        {"schema_version": "1", "sources": {}},
        {"schema_version": "1", "watch": "yes"},
    ],
)
def test_rejects_invalid_or_unknown_configuration(tmp_path, payload):
    with pytest.raises(ConfigurationError):
        AppConfig.from_dict(payload, workspace_root=tmp_path)


def test_non_loopback_http_requires_auth(tmp_path):
    payload = {
        "schema_version": "1",
        "server": {
            "transport": "streamable-http",
            "host": "0.0.0.0",
        },
    }
    with pytest.raises(ConfigurationError, match="requires server.auth_token_env"):
        AppConfig.from_dict(payload, workspace_root=tmp_path)


def test_non_loopback_http_with_auth_is_valid(tmp_path):
    config = AppConfig.from_dict(
        {
            "schema_version": "1",
            "server": {
                "transport": "streamable-http",
                "host": "0.0.0.0",
                "auth_token_env": "MOLMCP_TOKEN",
            },
        },
        workspace_root=tmp_path,
    )
    assert config.server.auth_token_env == "MOLMCP_TOKEN"


@pytest.mark.parametrize(
    "registry",
    [
        {"kind": "url", "location": "http://example.test/registry.json"},
        {"kind": "url", "location": "file:///tmp/registry.json"},
        {
            "kind": "url",
            "location": "https://user:secret@example.test/registry.json",
        },
        {
            "kind": "url",
            "location": "https://example.test/registry.json#fragment",
        },
        {
            "kind": "url",
            "location": "https://example.test/registry.json?token=secret",
        },
        {
            "kind": "url",
            "location": "https://example.test/{other}/registry.json",
        },
    ],
)
def test_remote_registry_requires_safe_https_url(tmp_path, registry):
    with pytest.raises(ConfigurationError, match="HTTPS URL|template"):
        AppConfig.from_dict(
            {"schema_version": "1", "registries": [registry]},
            workspace_root=tmp_path,
        )


def test_registry_headers_must_be_environment_references(tmp_path):
    with pytest.raises(ConfigurationError, match="environment variable"):
        AppConfig.from_dict(
            {
                "schema_version": "1",
                "registries": [
                    {
                        "kind": "url",
                        "location": "https://example.test/registry.json",
                        "headers": {"Authorization": "Bearer literal-secret"},
                    }
                ],
            },
            workspace_root=tmp_path,
        )


def test_registry_namespace_and_secret_reference_are_strict(tmp_path):
    config = AppConfig.from_dict(
        {
            "schema_version": "1",
            "registries": [
                {
                    "kind": "url",
                    "location": "https://example.test/{namespace}/registry.json",
                    "namespace": "@molpack",
                    "headers": {"Authorization": "Bearer ${MOLMCP_REGISTRY_TOKEN}"},
                }
            ],
        },
        workspace_root=tmp_path,
    )
    assert config.registries[0].namespace == "@molpack"
    assert config.registries[0].search_only is True

    with pytest.raises(ConfigurationError, match="valid '@namespace'"):
        AppConfig.from_dict(
            {
                "schema_version": "1",
                "registries": [
                    {
                        "kind": "file",
                        "location": "registry.json",
                        "namespace": "@Bad Namespace",
                    }
                ],
            },
            workspace_root=tmp_path,
        )


def test_remote_execution_requires_expected_digest(tmp_path):
    with pytest.raises(ConfigurationError, match="requires expected_digest"):
        AppConfig.from_dict(
            {
                "schema_version": "1",
                "registries": [
                    {
                        "kind": "url",
                        "location": "https://example.test/registry.json",
                        "search_only": False,
                    }
                ],
            },
            workspace_root=tmp_path,
        )

    config = AppConfig.from_dict(
        {
            "schema_version": "1",
            "registries": [
                {
                    "kind": "url",
                    "location": "https://example.test/registry.json",
                    "expected_digest": "a" * 64,
                }
            ],
        },
        workspace_root=tmp_path,
    )
    assert config.registries[0].search_only is False


def test_duplicate_config_keys_fail_closed(tmp_path):
    path = tmp_path / "molcrafts.json"
    path.write_text(
        '{"schema_version":"1","watch":true,"watch":false}',
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="duplicate JSON object key"):
        load_config(path)


@pytest.mark.parametrize(
    "payload, match",
    [
        (
            {"schema_version": "1", "providers": ["molq", "molq"]},
            "duplicates",
        ),
        (
            {"schema_version": "1", "providers": ["molcrafts"]},
            "reserved",
        ),
        (
            {"schema_version": "1", "sources": {"Bad Source": "."}},
            "source names",
        ),
        (
            {
                "schema_version": "1",
                "server": {"auth_token_env": "not an env name"},
            },
            "environment variable name",
        ),
    ],
)
def test_names_and_duplicates_fail_closed(tmp_path, payload, match):
    with pytest.raises(ConfigurationError, match=match):
        AppConfig.from_dict(payload, workspace_root=tmp_path)
