"""``molmcp discovery`` CLI subcommand tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from molmcp import cli
from molmcp.cli import main


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "calc.py").write_text(
        '"""Calc."""\n\n\ndef add(a, b):\n    """Add."""\n    return a + b\n'
        '\n\nclass Calc:\n    """A calculator."""\n',
        encoding="utf-8",
    )
    return repo


def _use_tmp_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MOLMCP_CACHE_DIR", str(tmp_path / "cache"))


def test_verify_reports_ok(tmp_path, monkeypatch, capsys):
    _use_tmp_cache(tmp_path, monkeypatch)
    code = main(["discovery", "verify", str(_repo(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0
    assert "result:        OK" in out
    assert "FTS5 index:" in out
    assert "sample search:" in out


def test_verify_bad_source_exits_nonzero(tmp_path, monkeypatch, capsys):
    _use_tmp_cache(tmp_path, monkeypatch)
    code = main(["discovery", "verify", "pkg:definitely_not_a_real_pkg"])
    assert code == 1
    assert "error:" in capsys.readouterr().err


def test_index_then_query(tmp_path, monkeypatch, capsys):
    _use_tmp_cache(tmp_path, monkeypatch)
    repo = str(_repo(tmp_path))
    assert main(["discovery", "index", repo]) == 0
    assert main(["discovery", "query", repo, "add"]) == 0
    out = capsys.readouterr().out
    assert "calc.add" in out


def test_outline(tmp_path, monkeypatch, capsys):
    _use_tmp_cache(tmp_path, monkeypatch)
    assert main(["discovery", "outline", str(_repo(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert "calc" in out and "Calc" in out


def test_clean(tmp_path, monkeypatch, capsys):
    _use_tmp_cache(tmp_path, monkeypatch)
    main(["discovery", "index", str(_repo(tmp_path))])
    assert main(["discovery", "clean"]) == 0
    assert "pruned" in capsys.readouterr().out


def test_local_or_github_prefers_local_install(monkeypatch):
    monkeypatch.setattr(cli, "_is_importable", lambda pkg: True)
    assert cli._local_or_github("molpy") == "pkg:molpy"


def test_local_or_github_falls_back_to_github(monkeypatch):
    monkeypatch.setattr(cli, "_is_importable", lambda pkg: False)
    assert cli._local_or_github("molpy") == "github:MolCrafts/molpy"


def test_default_sources_cover_every_package(monkeypatch):
    # None installed -> every single-package source falls back to GitHub.
    monkeypatch.setattr(cli, "_is_importable", lambda pkg: False)
    sources = cli._available_default_sources()
    for pkg in cli._DEFAULT_PACKAGES:
        assert f"github:MolCrafts/{pkg}" in sources


def test_default_sources_include_multi_package_repos(monkeypatch):
    # molnex has no single import name -> always a whole-repo GitHub source,
    # regardless of what is installed locally.
    monkeypatch.setattr(cli, "_is_importable", lambda pkg: True)
    sources = cli._available_default_sources()
    assert "github:MolCrafts/molnex" in sources
    assert "pkg:molnex" not in sources


def test_default_sources_mix_local_and_github(monkeypatch):
    monkeypatch.setattr(cli, "_is_importable", lambda pkg: pkg == "molpy")
    sources = cli._available_default_sources()
    assert "pkg:molpy" in sources
    assert "github:MolCrafts/molq" in sources
    assert "github:MolCrafts/molnex" in sources


# -- molmcp discovery lint -------------------------------------------------


def _dirty_repo(tmp_path: Path) -> Path:
    """A repo with lint findings: undocumented export + untested public fn."""
    repo = tmp_path / "dirty"
    repo.mkdir()
    (repo / "mod.py").write_text(
        '"""Mod."""\n\n__all__ = ["undocumented"]\n\n\n'
        "def undocumented():\n    return 1\n",
        encoding="utf-8",
    )
    return repo


def _clean_repo(tmp_path: Path) -> Path:
    """A repo with no findings: documented symbols, tests linked."""
    repo = tmp_path / "clean"
    repo.mkdir()
    (repo / "mod.py").write_text(
        '"""Mod."""\n\n\ndef add(a, b):\n    """Add."""\n    return a + b\n',
        encoding="utf-8",
    )
    (repo / "test_mod.py").write_text(
        '"""Tests."""\n\nfrom mod import add\n\n\n'
        'def test_add():\n    """Covers add."""\n    assert add(1, 1) == 2\n',
        encoding="utf-8",
    )
    return repo


def test_lint_default_is_advisory_exit_zero(tmp_path, monkeypatch, capsys):
    _use_tmp_cache(tmp_path, monkeypatch)
    code = main(["discovery", "lint", str(_dirty_repo(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0
    assert "undocumented exports" in out
    assert "untested public symbols" in out
    assert "high-unresolved modules" in out


def test_lint_clean_repo_prints_ok(tmp_path, monkeypatch, capsys):
    _use_tmp_cache(tmp_path, monkeypatch)
    code = main(["discovery", "lint", str(_clean_repo(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0
    assert "OK" in out


def test_lint_json_is_machine_readable(tmp_path, monkeypatch, capsys):
    _use_tmp_cache(tmp_path, monkeypatch)
    code = main(["discovery", "lint", str(_dirty_repo(tmp_path)), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "total_findings" in payload
    report = payload["reports"][0]
    for key in (
        "source",
        "summary",
        "undocumented_exports",
        "untested_public_symbols",
        "high_unresolved_modules",
    ):
        assert key in report
    assert payload["total_findings"] >= 1


def test_lint_strict_gates_on_findings(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    assert main(["discovery", "lint", str(_dirty_repo(tmp_path)), "--strict"]) == 1
    assert main(["discovery", "lint", str(_clean_repo(tmp_path)), "--strict"]) == 0


def test_lint_pkg_maps_through_source_resolver(tmp_path, monkeypatch, capsys):
    _use_tmp_cache(tmp_path, monkeypatch)
    repo = _dirty_repo(tmp_path)
    monkeypatch.setattr(cli, "_source_for_package", lambda pkg: str(repo))
    code = main(["discovery", "lint", "--pkg", "fakepkg", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reports"][0]["source"] == str(repo)


def test_lint_without_source_or_pkg_is_usage_error(tmp_path, monkeypatch):
    _use_tmp_cache(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as excinfo:
        main(["discovery", "lint"])
    assert excinfo.value.code == 2


def test_lint_bad_source_exits_nonzero(tmp_path, monkeypatch, capsys):
    _use_tmp_cache(tmp_path, monkeypatch)
    code = main(["discovery", "lint", "pkg:definitely_not_a_real_pkg"])
    assert code == 1
    assert "error:" in capsys.readouterr().err
