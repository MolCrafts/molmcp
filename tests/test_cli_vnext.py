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
                "schema_version": "2",
                "sources": {"project": "."},
                "watch": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_no_arguments_defaults_to_planes(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "multi-link" in out.lower() or "planes" in out.lower() or "catalog" in out


def test_serve_requires_plane(monkeypatch, tmp_path, capsys):
    captured = {}

    class FakeServer:
        def run(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "create_plane", lambda *a, **kwargs: FakeServer())
    assert cli.main(["serve", "catalog"]) == 0
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

    monkeypatch.setattr(cli, "build_collection", lambda config: Collection())
    assert cli.main(["search", "pack", "--config", str(_config(tmp_path))]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["ref"] == "@molpack/pack"


def test_unknown_index_source_is_user_error(monkeypatch, tmp_path, capsys):
    class Collection:
        sources = ()

    monkeypatch.setattr(cli, "build_collection", lambda config: Collection())
    code = cli.main(["index", "missing", "--config", str(_config(tmp_path))])
    assert code == 2
    assert "unknown configured sources" in capsys.readouterr().err


def test_non_loopback_override_requires_auth(monkeypatch, tmp_path, capsys):
    class FakeServer:
        def run(self, **kwargs):
            raise AssertionError("must fail before run")

    monkeypatch.setattr(cli, "create_plane", lambda *a, **kwargs: FakeServer())
    code = cli.main(
        [
            "serve",
            "catalog",
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
    monkeypatch.setattr(cli, "build_collection", lambda config: _FakeCollection())


def test_route_cli(capsys):
    assert cli.main(["route", "draw a molecule"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(m["plane"] == "molvis" for m in payload["planes"])
