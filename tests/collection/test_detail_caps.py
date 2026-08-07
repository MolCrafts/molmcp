"""A symbol page is bounded before it reaches an agent's context.

The caps existed — 12 000 characters of source, 2 000 of example code —
but they lived in `discovery/evidence.py`, which no tool calls. The path
that serves `open` had none, so one `open(include_source=True)` against a
large module returned 41 568 characters of this very repository.

The 256 KB response middleware is not a substitute: it is a blunt backstop
that truncates a whole payload, where this trims one field and says so.
"""

from __future__ import annotations

import pytest

from molmcp.collection import CollectionIndex, SourceBinding
from molmcp.collection.index import (
    MAX_EXAMPLE_CHARS,
    MAX_SOURCE_CHARS,
)
from molmcp.discovery import DiscoveryConfig, DiscoveryEngine


@pytest.fixture
def big_source(tmp_path):
    """One module whose single symbol is far larger than the cap."""
    repo = tmp_path / "repo"
    repo.mkdir()
    body = "\n".join(f"    value_{i} = {i}  # padding" for i in range(4000))
    example = "\n".join(f">>> step_{i}()" for i in range(400))
    (repo / "big.py").write_text(
        f'"""Module doc.\n\n{example}\n"""\n\n\nclass Huge:\n'
        f'    """A very large class.\n\n{example}\n    """\n\n{body}\n',
        encoding="utf-8",
    )
    engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))
    collection = CollectionIndex(
        [SourceBinding(name="big", spec=str(repo), engine=engine, namespace="big")],
        None,
    )
    query = engine.query(str(repo))
    snapshot = query.snapshot.snapshot_id
    node = max(query.store.load_graph().nodes, key=lambda n: n.end_line - n.start_line)
    query.store.close()
    return collection, f"big@{snapshot}:{node.id}"


class TestSourceIsCapped:
    def test_source_code_is_trimmed_to_the_cap(self, big_source):
        collection, ref = big_source

        detail = collection.describe(ref, include_source=True)

        assert detail is not None
        assert len(detail["source_code"]) <= MAX_SOURCE_CHARS + 64

    def test_a_trimmed_snippet_says_so(self, big_source):
        collection, ref = big_source

        detail = collection.describe(ref, include_source=True)

        assert "truncated" in detail["source_code"]

    def test_a_small_symbol_is_returned_whole(self, tmp_path):
        repo = tmp_path / "small"
        repo.mkdir()
        (repo / "m.py").write_text(
            'def tiny():\n    """Tiny."""\n    return 1\n', encoding="utf-8"
        )
        engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))
        collection = CollectionIndex(
            [SourceBinding(name="s", spec=str(repo), engine=engine, namespace="s")],
            None,
        )
        query = engine.query(str(repo))
        snapshot = query.snapshot.snapshot_id
        node = next(n for n in query.store.load_graph().nodes if n.name == "tiny")
        query.store.close()

        detail = collection.describe(f"s@{snapshot}:{node.id}", include_source=True)

        assert "truncated" not in detail["source_code"]
        assert "return 1" in detail["source_code"]


class TestExampleCodeIsCapped:
    def test_example_snippets_are_trimmed(self, big_source):
        collection, ref = big_source

        detail = collection.describe(ref, include_source=False)

        for example in detail.get("examples") or []:
            code = (example.get("metadata") or {}).get("code", "")
            assert len(code) <= MAX_EXAMPLE_CHARS + 64


class TestTheWholePageStaysBounded:
    def test_one_open_cannot_dump_a_whole_module(self, big_source):
        """41 568 characters was the measured cost of the missing cap."""
        import json

        collection, ref = big_source

        detail = collection.describe(ref, include_source=True)

        assert len(json.dumps(detail, default=str)) < 30_000
