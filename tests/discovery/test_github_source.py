"""GitHub source resolution tests (network mocked)."""

from __future__ import annotations

import io
import json
import tarfile

import pytest

from molmcp.discovery import DiscoveryConfig, DiscoveryEngine
from molmcp.discovery.source import SourceError, github

_SHA = "a" * 40
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
    """Build an ``_http_get`` replacement serving a fake repo."""

    def _get(url, token=None, accept="application/vnd.github+json"):
        if "codeload" in url:
            return _make_tarball(f"repo-{sha}", files)
        if "/commits/" in url:
            return json.dumps({"sha": sha}).encode("utf-8")
        return json.dumps({"default_branch": "main"}).encode("utf-8")

    return _get


def _engine(tmp_path) -> DiscoveryEngine:
    return DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))


def test_resolves_ref_to_commit_sha(monkeypatch, tmp_path):
    monkeypatch.setattr(github, "_http_get", fake_http(_SHA, _FILES))
    result = _engine(tmp_path).index("github:owner/repo")
    assert result.snapshot.origin == "github"
    assert result.snapshot.commit == _SHA
    assert result.snapshot.snapshot_id == f"github:commit:{_SHA}"


def test_extracts_graph_from_tarball(monkeypatch, tmp_path):
    monkeypatch.setattr(github, "_http_get", fake_http(_SHA, _FILES))
    graph = _engine(tmp_path).get_graph("github:owner/repo")
    assert "calc.add" in {n.qualname for n in graph.nodes}


def test_second_index_is_cache_first(monkeypatch, tmp_path):
    calls: list[str] = []
    served = fake_http(_SHA, _FILES)

    def counting(url, token=None, accept="application/vnd.github+json"):
        calls.append(url)
        return served(url, token, accept)

    monkeypatch.setattr(github, "_http_get", counting)
    engine = _engine(tmp_path)
    engine.index("github:owner/repo")
    after_first = len(calls)
    assert after_first > 0

    engine.index("github:owner/repo")
    assert len(calls) == after_first  # cache-first: no extra network


def test_ref_in_spec_is_recorded(monkeypatch, tmp_path):
    monkeypatch.setattr(github, "_http_get", fake_http(_SHA, {"m.py": "x = 1\n"}))
    result = _engine(tmp_path).index("github:owner/repo@dev")
    assert result.snapshot.ref == "dev"


def test_invalid_spec_raises(tmp_path):
    with pytest.raises(SourceError):
        _engine(tmp_path).index("github:not-a-valid-spec")
