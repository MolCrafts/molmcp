from __future__ import annotations

import json

from molmcp import cli
from molmcp.environment import EnvironmentReport


def _empty_report(locator=None) -> EnvironmentReport:
    return EnvironmentReport(
        locator=locator,
        is_self=locator is None,
        site_paths=(),
        sources=(),
        skipped=(),
        excluded=(),
    )


class _FakeCollection:
    def info(self):
        return {}


def _config(tmp_path):
    path = tmp_path / "molcrafts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "sources": {"project": "."},
                "watch": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_no_arguments_defaults_to_serve(monkeypatch, tmp_path):
    captured = {}

    class FakeServer:
        def run(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "create_server", lambda **kwargs: FakeServer())
    assert cli.main([]) == 0
    # Stdio clients (agent hosts) must not get FastMCP banners / INFO chatter.
    assert captured == {
        "transport": "stdio",
        "show_banner": False,
        "log_level": "ERROR",
    }


def test_search_emits_json(monkeypatch, tmp_path, capsys):
    class Hit:
        def to_dict(self):
            return {"ref": "@molpack/pack", "executable": True}

    class Collection:
        def search(self, *args, **kwargs):
            return [Hit()]

    monkeypatch.setattr(cli, "build_registry", lambda config: object())
    monkeypatch.setattr(cli, "build_collection", lambda config, registry: Collection())
    assert cli.main(["search", "pack", "--config", str(_config(tmp_path))]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["ref"] == "@molpack/pack"


def test_registry_validate(tmp_path, capsys):
    manifest = tmp_path / "molcrafts.registry.json"
    manifest.write_text(
        json.dumps({"schema_version": "1", "items": []}), encoding="utf-8"
    )
    assert cli.main(["registry", "validate", str(manifest)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["digest"]
    assert payload["items"] == []


def test_unknown_index_source_is_user_error(monkeypatch, tmp_path, capsys):
    class Collection:
        sources = ()

    monkeypatch.setattr(cli, "build_registry", lambda config: object())
    monkeypatch.setattr(cli, "build_collection", lambda config, registry: Collection())
    code = cli.main(["index", "missing", "--config", str(_config(tmp_path))])
    assert code == 2
    assert "unknown configured sources" in capsys.readouterr().err


def test_non_loopback_override_requires_auth(monkeypatch, tmp_path, capsys):
    class FakeServer:
        def run(self, **kwargs):
            raise AssertionError("must fail before run")

    monkeypatch.setattr(cli, "create_server", lambda **kwargs: FakeServer())
    code = cli.main(
        [
            "serve",
            "--config",
            str(_config(tmp_path)),
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
        ]
    )
    assert code == 2
    assert "requires server.auth_token_env" in capsys.readouterr().err


def _patch_collection(monkeypatch):
    monkeypatch.setattr(cli, "build_registry", lambda config: object())
    monkeypatch.setattr(
        cli, "build_collection", lambda config, registry: _FakeCollection()
    )


def test_env_flag_is_threaded_into_discovery(monkeypatch, tmp_path):
    captured: dict[str, str | None] = {}

    def fake(locator=None):
        captured["locator"] = locator
        return _empty_report(locator)

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MOLMCP_ENV", raising=False)
    monkeypatch.setattr("molmcp.environment.discover_sources", fake)
    _patch_collection(monkeypatch)
    assert cli.main(["info", "--env", "/envs/x"]) == 0
    assert captured["locator"] == "/envs/x"


def test_molmcp_env_used_when_flag_absent(monkeypatch, tmp_path):
    captured: dict[str, str | None] = {}

    def fake(locator=None):
        captured["locator"] = locator
        return _empty_report(locator)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOLMCP_ENV", "/envs/y")
    monkeypatch.setattr("molmcp.environment.discover_sources", fake)
    _patch_collection(monkeypatch)
    assert cli.main(["info"]) == 0
    assert captured["locator"] == "/envs/y"


def test_locator_is_none_without_flag_or_env(monkeypatch, tmp_path):
    captured: dict[str, str | None] = {}

    def fake(locator=None):
        captured["locator"] = locator
        return _empty_report(locator)

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MOLMCP_ENV", raising=False)
    monkeypatch.setattr("molmcp.environment.discover_sources", fake)
    _patch_collection(monkeypatch)
    assert cli.main(["info"]) == 0
    assert captured["locator"] is None


def test_bad_env_locator_exits_two(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MOLMCP_ENV", raising=False)
    missing = tmp_path / "nonexistent-env"
    code = cli.main(["info", "--env", str(missing)])
    assert code == 2
    assert "molmcp:" in capsys.readouterr().err
