from __future__ import annotations

import json

import pytest

from molmcp.config import (
    _SOURCE_NAME_RE,
    AppConfig,
    ConfigurationError,
    _resolve_source_spec,
    load_config,
)
from molmcp.environment import DiscoveredSource, EnvironmentReport


def _env_report(
    sources=(),
    *,
    locator=None,
    site_paths=(),
    skipped=(),
    excluded=(),
) -> EnvironmentReport:
    return EnvironmentReport(
        locator=locator,
        is_self=locator is None,
        site_paths=tuple(site_paths),
        sources=tuple(sources),
        skipped=tuple(skipped),
        excluded=tuple(excluded),
    )


def test_default_config_indexes_current_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MOLMCP_ENV", raising=False)
    monkeypatch.setattr(
        "molmcp.environment.discover_sources", lambda locator=None: _env_report()
    )
    config = load_config()
    # Scope is explicit now: an empty discovery report yields no sources at
    # all, where this used to silently index the working directory.
    assert config.sources == {}
    assert config.server.transport == "stdio"


def test_loads_and_resolves_relative_paths(tmp_path):
    path = tmp_path / "molcrafts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "2",
                "sources": {"local": "./repo", "molpy": "pkg:molpy"},
                "registries": [{"kind": "file", "location": "registry.json"}],
                "cache_dir": ".cache/molmcp",
            }
        ),
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.sources["local"] == str((tmp_path / "repo").resolve())
    assert config.sources["molpy"] == "pkg:molpy"
    assert config.registries[0].location == str((tmp_path / "registry.json").resolve())
    assert config.cache_dir == (tmp_path / ".cache/molmcp").resolve()


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "2", "unknown": True},
        {"schema_version": "1", "sources": {"x": "."}},
        {"schema_version": "2", "sources": {}},
        {"schema_version": "2", "watch": "yes"},
    ],
)
def test_rejects_invalid_or_unknown_configuration(tmp_path, payload):
    with pytest.raises(ConfigurationError):
        AppConfig.from_dict(payload, workspace_root=tmp_path)


def test_non_loopback_http_requires_auth(tmp_path):
    payload = {
        "schema_version": "2",
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
            "schema_version": "2",
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
            {"schema_version": "2", "registries": [registry]},
            workspace_root=tmp_path,
        )


def test_registry_headers_must_be_environment_references(tmp_path):
    with pytest.raises(ConfigurationError, match="environment variable"):
        AppConfig.from_dict(
            {
                "schema_version": "2",
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
            "schema_version": "2",
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
                "schema_version": "2",
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
                "schema_version": "2",
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
            "schema_version": "2",
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
        '{"schema_version":"2","watch":true,"watch":false}',
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="duplicate JSON object key"):
        load_config(path)


def test_rejects_legacy_providers_field(tmp_path):
    with pytest.raises(ConfigurationError, match="unknown field"):
        AppConfig.from_dict(
            {"schema_version": "2", "providers": ["molq"]},
            workspace_root=tmp_path,
        )


@pytest.mark.parametrize(
    "payload, match",
    [
        (
            {"schema_version": "2", "sources": {"Bad Source": "."}},
            "source names",
        ),
        (
            {
                "schema_version": "2",
                "server": {"auth_token_env": "not an env name"},
            },
            "environment variable name",
        ),
    ],
)
def test_names_and_duplicates_fail_closed(tmp_path, payload, match):
    with pytest.raises(ConfigurationError, match=match):
        AppConfig.from_dict(payload, workspace_root=tmp_path)


def test_no_file_folds_auto_discovered_sources(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg_dir = tmp_path / "molfoo"
    pkg_dir.mkdir()
    report = _env_report(
        sources=(
            DiscoveredSource(
                name="molpy",
                spec="pkg:molpy",
                identified_by=("entry_point",),
                distribution="molpy",
                version="1.0.0",
            ),
            DiscoveredSource(
                name="molfoo",
                spec=f"local:{pkg_dir}",
                identified_by=("keyword",),
                distribution="molfoo",
                version="0.2.0",
            ),
        ),
    )
    monkeypatch.setattr(
        "molmcp.environment.discover_sources", lambda locator=None: report
    )
    config = load_config()
    assert config.sources == {
        "molpy": "pkg:molpy",
        "molfoo": f"local:{pkg_dir}",
    }
    assert config.discovery is not None
    identified = {
        source["name"]: source["identified_by"]
        for source in config.discovery["sources"]
    }
    assert identified["molpy"] == ["entry_point"]
    assert identified["molfoo"] == ["keyword"]


def test_explicit_config_is_not_augmented(tmp_path, monkeypatch):
    path = tmp_path / "molcrafts.json"
    path.write_text(
        json.dumps({"schema_version": "2", "sources": {"project": "."}}),
        encoding="utf-8",
    )
    calls: list[str | None] = []

    def fake(locator=None):
        calls.append(locator)
        return _env_report()

    monkeypatch.setattr("molmcp.environment.discover_sources", fake)
    config = load_config(path)
    assert config.sources == {"project": str(tmp_path.resolve())}
    assert config.discovery is None
    assert calls == []


def test_default_dedupes_discovered_names_colliding_with_workspace(tmp_path):
    from molmcp.settings import Settings

    config = AppConfig.default(
        tmp_path,
        discovered=[("workspace", "pkg:a"), ("workspace", "pkg:b")],
        settings=Settings(index_workspace=True),
    )
    root = str(tmp_path.resolve())
    assert config.sources["workspace"] == root
    assert config.sources["workspace-2"] == "pkg:a"
    assert config.sources["workspace-3"] == "pkg:b"
    assert all(_SOURCE_NAME_RE.fullmatch(name) for name in config.sources)


def test_default_dedupes_mutually_colliding_discovered_names(tmp_path):
    from molmcp.settings import Settings

    config = AppConfig.default(
        tmp_path,
        discovered=[("molpy", "pkg:x"), ("molpy", "pkg:y")],
        settings=Settings(index_workspace=True),
    )
    assert config.sources["workspace"] == str(tmp_path.resolve())
    assert config.sources["molpy"] == "pkg:x"
    assert config.sources["molpy-2"] == "pkg:y"
    assert all(_SOURCE_NAME_RE.fullmatch(name) for name in config.sources)


def test_bad_locator_propagates_configuration_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def fake(locator=None):
        raise ConfigurationError(f"environment locator does not exist: {locator}")

    monkeypatch.setattr("molmcp.environment.discover_sources", fake)
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_config(env_locator="bad")


def test_env_locator_falls_back_to_molmcp_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOLMCP_ENV", "/envs/foo")
    captured: dict[str, str | None] = {}

    def fake(locator=None):
        captured["locator"] = locator
        return _env_report()

    monkeypatch.setattr("molmcp.environment.discover_sources", fake)
    load_config()
    assert captured["locator"] == "/envs/foo"


def test_explicit_env_locator_beats_env_var(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOLMCP_ENV", "/envs/foo")
    captured: dict[str, str | None] = {}

    def fake(locator=None):
        captured["locator"] = locator
        return _env_report()

    monkeypatch.setattr("molmcp.environment.discover_sources", fake)
    load_config(env_locator="/envs/explicit")
    assert captured["locator"] == "/envs/explicit"


def test_resolve_source_spec_passes_through_local_prefix(tmp_path):
    spec = "local:/abs/pkg/dir"
    assert _resolve_source_spec(spec, tmp_path.resolve()) == spec
