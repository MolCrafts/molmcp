"""DiscoveryEngine indexing / caching tests."""

from __future__ import annotations

from pathlib import Path

from molmcp.discovery import DiscoveryConfig, DiscoveryEngine
from molmcp.discovery.schema import SCHEMA_VERSION


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    _write(
        repo / "calc.py",
        '"""Calculator module."""\n\n'
        "\n"
        "def add(a: int, b: int) -> int:\n"
        '    """Add two numbers."""\n'
        "    return a + b\n"
        "\n"
        "\n"
        "class Calc:\n"
        '    """A calculator."""\n'
        "\n"
        "    def run(self) -> int:\n"
        "        return add(1, 2)\n",
    )
    return repo


def _engine(tmp_path: Path) -> DiscoveryEngine:
    return DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))


def test_index_writes_db_and_manifest(tmp_path):
    engine = _engine(tmp_path)
    result = engine.index(str(_repo(tmp_path)))
    sid = result.snapshot.snapshot_id

    assert engine.cache.graph_db_path(sid).is_file()
    assert engine.cache.manifest_path(sid).is_file()

    manifest = engine.cache.read_manifest(sid)
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["node_count"] == result.node_count
    assert manifest["origin"] == "local"


def test_reload_matches_indexed_graph(tmp_path):
    engine = _engine(tmp_path)
    result = engine.index(str(_repo(tmp_path)))
    reloaded = engine.load_graph(result.snapshot.snapshot_id)

    assert len(reloaded.nodes) == result.node_count
    assert {n.id for n in reloaded.nodes} == {n.id for n in result.graph.nodes}
    assert len(reloaded.edges) == result.edge_count


def test_second_index_uses_cache(tmp_path):
    engine = _engine(tmp_path)
    repo = str(_repo(tmp_path))
    first = engine.index(repo)
    second = engine.index(repo)
    assert first.cached is False
    assert second.cached is True
    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id


def test_force_reindex_bypasses_cache(tmp_path):
    engine = _engine(tmp_path)
    repo = str(_repo(tmp_path))
    engine.index(repo)
    forced = engine.index(repo, force=True)
    assert forced.cached is False


def test_typescript_file_recorded_without_nodes(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "a.py", "def f():\n    pass\n")
    _write(repo / "app.ts", "export const x = 1;\n")
    result = _engine(tmp_path).index(str(repo))

    ts_files = [f for f in result.graph.files if f.language == "typescript"]
    assert len(ts_files) == 1
    assert ts_files[0].node_count == 0
    assert any("unavailable" in e for e in ts_files[0].errors)
    # the Python file still produced nodes
    assert any(n.language == "python" for n in result.graph.nodes)


def test_index_resolves_internal_calls(tmp_path):
    engine = _engine(tmp_path)
    result = engine.index(str(_repo(tmp_path)))
    add = next(n for n in result.graph.nodes if n.qualname == "calc.add")
    run = next(n for n in result.graph.nodes if n.qualname == "calc.Calc.run")
    calls = {(e.source, e.target) for e in result.graph.edges if e.kind == "calls"}
    assert (run.id, add.id) in calls
