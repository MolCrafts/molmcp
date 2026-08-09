"""`packages` is the L0 entry point — it must not pay for a full outline.

Every agent session starts here, and each card wants one summary line and a
module count. It got them by building the entire module tree for every
source: `outline()` walks each module's children, so a package with 75
modules cost 186 batched reads to answer a question two indexed queries
answer.

The same page also opened each source's query handle twice — once through
`collection.info()` and again per card — and each open re-walks and
re-hashes the source from disk.
"""

from __future__ import annotations

import pytest

from molmcp.collection import CollectionIndex, SourceBinding
from molmcp.collection.browse import packages_catalog
from molmcp.discovery import DiscoveryConfig, DiscoveryEngine


@pytest.fixture
def collection(tmp_path):
    repo = tmp_path / "pkg"
    (repo / "sub").mkdir(parents=True)
    (repo / "__init__.py").write_text('"""The package summary."""\n', encoding="utf-8")
    for i in range(12):
        (repo / f"mod{i}.py").write_text(
            f'"""Module {i}."""\n\n\ndef fn{i}():\n    """Do {i}."""\n',
            encoding="utf-8",
        )
    (repo / "sub" / "__init__.py").write_text('"""Sub."""\n', encoding="utf-8")
    engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))
    return CollectionIndex(
        [SourceBinding(name="pkg", spec=str(repo), engine=engine, namespace="pkg")],
        None,
    )


def _count_opens(collection, monkeypatch) -> dict[str, int]:
    counter = {"opens": 0}
    original = SourceBinding.open_query

    def counting(self):
        counter["opens"] += 1
        return original(self)

    monkeypatch.setattr(SourceBinding, "open_query", counting)
    return counter


class TestPackagesOpensEachSourceOnce:
    def test_one_query_handle_per_source(self, collection, monkeypatch):
        packages_catalog(collection)  # warm the on-disk graph
        counter = _count_opens(collection, monkeypatch)

        packages_catalog(collection)

        assert counter["opens"] == 1


class TestPackagesDoesNotBuildAnOutline:
    def test_the_module_tree_is_never_walked(self, collection, monkeypatch):
        from molmcp.discovery.query import DiscoveryQuery

        packages_catalog(collection)
        calls = {"outline": 0}
        original = DiscoveryQuery.outline

        def counting(self, path=None):
            calls["outline"] += 1
            return original(self, path)

        monkeypatch.setattr(DiscoveryQuery, "outline", counting)

        packages_catalog(collection)

        assert calls["outline"] == 0


class TestPackagesStillAnswersTheQuestion:
    def test_the_card_carries_the_package_summary(self, collection):
        cards = packages_catalog(collection)["data"]["packages"]

        assert [c["name"] for c in cards] == ["pkg"]
        assert cards[0]["summary"] == "The package summary."
        assert cards[0]["summary_source"] == "package_docstring"

    def test_the_card_counts_modules(self, collection):
        card = packages_catalog(collection)["data"]["packages"][0]

        # 12 modules + the package and its subpackage.
        assert card["module_count"] == 14

    def test_a_source_without_any_summary_says_so(self, tmp_path):
        repo = tmp_path / "bare"
        repo.mkdir()
        (repo / "m.py").write_text("x = 1\n", encoding="utf-8")
        engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))
        collection = CollectionIndex(
            [SourceBinding(name="bare", spec=str(repo), engine=engine)], None
        )

        card = packages_catalog(collection)["data"]["packages"][0]

        assert card["summary"] is None
        assert "summary missing" in " ".join(card["warnings"])


class TestContextPackFitsWithoutQuadraticWork:
    """`explore` budgets a pack by adding one item at a time.

    It measured the result by re-serialising the *entire* pack after every
    single addition, so a 12-hit, 12-detail pack ran json.dumps 24 times
    over a payload that grew with each pass.
    """

    def test_the_whole_pack_is_not_reserialised_per_item(self, tmp_path, monkeypatch):
        from molmcp.collection import index as index_module

        repo = tmp_path / "many"
        repo.mkdir()
        for i in range(30):
            (repo / f"m{i}.py").write_text(
                f'"""Frame reader {i}."""\n\n\ndef read_frame{i}():\n'
                f'    """Read a frame."""\n',
                encoding="utf-8",
            )
        engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))
        collection = CollectionIndex(
            [SourceBinding(name="many", spec=str(repo), engine=engine)], None
        )
        collection.explore("frame")  # warm

        calls = {"n": 0}
        original = index_module._json_size

        def counting(pack):
            calls["n"] += 1
            return original(pack)

        monkeypatch.setattr(index_module, "_json_size", counting)
        pack = collection.explore("frame")

        assert pack.hits
        # Serialising each item once is inherent and cheap. Serialising the
        # whole, growing pack once per item is what made fitting quadratic:
        # 12 hits and 12 details used to cost 24 full passes.
        assert calls["n"] <= 8

    def test_the_pack_still_respects_its_budget(self, tmp_path):
        repo = tmp_path / "many"
        repo.mkdir()
        for i in range(30):
            (repo / f"m{i}.py").write_text(
                f'"""Frame reader {i}."""\n\n\ndef read_frame{i}():\n'
                f'    """Read a frame in a way that takes some words."""\n',
                encoding="utf-8",
            )
        engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))
        collection = CollectionIndex(
            [SourceBinding(name="many", spec=str(repo), engine=engine)], None
        )

        pack = collection.explore("frame", budget_chars=4000)

        assert pack.used_chars <= 4000
        assert pack.truncated is True
