"""GitHub ref-freshness tests (network mocked)."""

from __future__ import annotations

import io
import json
import tarfile

from molmcp.discovery import DiscoveryConfig, DiscoveryEngine
from molmcp.discovery.source import github

_SHA1 = "a" * 40
_SHA2 = "b" * 40
_FILES = {"calc.py": "def add(a, b):\n    return a + b\n"}


def _make_tarball(top: str, files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=f"{top}/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def fake_http(sha: str, files: dict[str, str]):
    def _get(url, token=None, accept="application/vnd.github+json"):
        if "codeload" in url:
            return _make_tarball(f"repo-{sha}", files)
        if "/commits/" in url:
            return json.dumps({"sha": sha}).encode("utf-8")
        return json.dumps({"default_branch": "main"}).encode("utf-8")

    return _get


def _engine(tmp_path) -> DiscoveryEngine:
    return DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))


def test_freshness_unknown_when_not_indexed(tmp_path):
    assert _engine(tmp_path).check_freshness("github:owner/repo") == "unknown"


def test_freshness_fresh_after_index(monkeypatch, tmp_path):
    monkeypatch.setattr(github, "_http_get", fake_http(_SHA1, _FILES))
    engine = _engine(tmp_path)
    engine.index("github:owner/repo")
    assert engine.check_freshness("github:owner/repo") == "fresh"


def test_freshness_stale_when_remote_moves(monkeypatch, tmp_path):
    monkeypatch.setattr(github, "_http_get", fake_http(_SHA1, _FILES))
    engine = _engine(tmp_path)
    engine.index("github:owner/repo")

    monkeypatch.setattr(github, "_http_get", fake_http(_SHA2, _FILES))
    assert engine.check_freshness("github:owner/repo") == "stale"


def test_refresh_picks_up_new_commit(monkeypatch, tmp_path):
    monkeypatch.setattr(github, "_http_get", fake_http(_SHA1, _FILES))
    engine = _engine(tmp_path)
    first = engine.index("github:owner/repo")
    assert first.snapshot.commit == _SHA1

    monkeypatch.setattr(
        github,
        "_http_get",
        fake_http(_SHA2, {"calc.py": "def mul(a, b):\n    return a * b\n"}),
    )
    result = engine.refresh("github:owner/repo")
    assert result.snapshot.commit == _SHA2
    assert result.freshness == "fresh"
    assert "calc.mul" in {n.qualname for n in result.graph.nodes}


def test_local_source_is_always_fresh(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("x = 1\n", encoding="utf-8")
    assert _engine(tmp_path).check_freshness(str(repo)) == "fresh"
