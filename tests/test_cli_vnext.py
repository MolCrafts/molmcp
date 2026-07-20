from __future__ import annotations

import json

from molmcp import cli


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
    assert captured == {"transport": "stdio"}


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
