"""``molmcp discovery`` CLI subcommand tests."""

from __future__ import annotations

from pathlib import Path

from molmcp.cli import main


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "calc.py").write_text(
        '"""Calc."""\n\n\ndef add(a, b):\n    """Add."""\n    return a + b\n'
        "\n\nclass Calc:\n    \"\"\"A calculator.\"\"\"\n",
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
