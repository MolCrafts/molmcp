"""Convention overlay tests — parsing, graph contribution, injection."""

from __future__ import annotations

from pathlib import Path

import pytest

from molmcp.discovery import DiscoveryConfig, DiscoveryEngine
from molmcp.discovery.evidence import (
    _MAX_CONVENTION_CHARS,
    _MAX_CONVENTIONS,
    EvidenceBuilder,
)
from molmcp.discovery.overlay.catalog import CatalogOverlay, load_catalog
from molmcp.discovery.overlay.conventions import load_conventions
from molmcp.discovery.schema import (
    ANALYZER_VERSION,
    SCHEMA_VERSION,
    EdgeKind,
    NodeKind,
)

_MIXED_CATALOG = """
[[capability]]
id = "compute.rdf"
title = "Radial distribution function"
summary = "Compute g(r) between atom selections."
implemented_by = ["compute.RDF"]
tags = ["analysis"]

[[convention]]
id = "style.compute"
scope = "compute"
title = "compute style rules"
rules = [
  "Return new objects, never mutate in place.",
  "Public API needs Google-style docstrings.",
]
tags = ["style", "immutability"]

[[convention]]
id = "style.ghost"
scope = ["nonexistent.pkg"]
title = "Ghost scope"
rules = ["Never resolved against the graph."]

[[convention]]
scope = ["compute"]
title = "broken: missing id"

[[convention]]
id = "style.no_scope"
title = "broken: missing scope"
"""

# Capabilities-only catalog, byte-identical in spirit to the one used by
# tests/discovery/test_overlay.py — proves backward compatibility.
_OLD_CATALOG = """
[[capability]]
id = "compute.rdf"
title = "Radial distribution function"
summary = "Compute g(r) between atom selections."
implemented_by = ["compute.RDF"]
examples = ["examples/rdf.py"]
tags = ["analysis"]

[[capability]]
id = "missing.thing"
summary = "Declared but not implemented anywhere."
implemented_by = ["does.not.Exist"]
"""

_SOURCE = '''"""Compute module."""


class RDF:
    """Radial distribution function compute op."""

    def run(self):
        return 1
'''


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def mixed_catalog(tmp_path):
    catalog = tmp_path / "capability_catalog.toml"
    catalog.write_text(_MIXED_CATALOG, encoding="utf-8")
    return catalog


@pytest.fixture
def convention_engine(tmp_path, mixed_catalog):
    repo = tmp_path / "repo"
    _write(repo / "compute.py", _SOURCE)
    overlay = CatalogOverlay(mixed_catalog, name="test")
    engine = DiscoveryEngine(
        DiscoveryConfig(cache_dir=tmp_path / "cache"), overlays=[overlay]
    )
    return engine, str(repo)


# --- schema additions (ac-001) -------------------------------------------


def test_schema_version_is_bumped_to_4():
    assert SCHEMA_VERSION == 4


def test_analyzer_version_is_bumped_to_2():
    assert ANALYZER_VERSION == 2


def test_convention_node_kind_exists():
    assert NodeKind.CONVENTION == "convention"


def test_governs_edge_kind_exists():
    assert EdgeKind.GOVERNS == "governs"


# --- load_conventions parsing (ac-002) -----------------------------------


def test_load_conventions_returns_only_convention_entries(mixed_catalog):
    conventions = load_conventions(mixed_catalog)
    assert {c.id for c in conventions} == {"style.compute", "style.ghost"}


def test_load_conventions_parses_fields(mixed_catalog):
    conventions = load_conventions(mixed_catalog)
    compute = next(c for c in conventions if c.id == "style.compute")
    assert compute.title == "compute style rules"
    assert compute.rules == [
        "Return new objects, never mutate in place.",
        "Public API needs Google-style docstrings.",
    ]
    assert compute.tags == ["style", "immutability"]


def test_scope_string_is_normalized_to_list(mixed_catalog):
    conventions = load_conventions(mixed_catalog)
    compute = next(c for c in conventions if c.id == "style.compute")
    assert compute.scope == ["compute"]


def test_scope_list_stays_a_list(mixed_catalog):
    conventions = load_conventions(mixed_catalog)
    ghost = next(c for c in conventions if c.id == "style.ghost")
    assert ghost.scope == ["nonexistent.pkg"]


def test_entry_missing_id_is_skipped(mixed_catalog):
    conventions = load_conventions(mixed_catalog)
    assert all(c.title != "broken: missing id" for c in conventions)


def test_entry_missing_scope_is_skipped(mixed_catalog):
    conventions = load_conventions(mixed_catalog)
    assert all(c.id != "style.no_scope" for c in conventions)


def test_old_catalog_without_conventions_yields_empty_list(tmp_path):
    catalog = tmp_path / "old.toml"
    catalog.write_text(_OLD_CATALOG, encoding="utf-8")
    assert load_conventions(catalog) == []


def test_load_catalog_unaffected_by_convention_sections(mixed_catalog):
    capabilities = load_catalog(mixed_catalog)
    assert {c.id for c in capabilities} == {"compute.rdf"}
    rdf = capabilities[0]
    assert rdf.implemented_by == ["compute.RDF"]


# --- graph contribution via DiscoveryEngine + CatalogOverlay (ac-003) -----


def test_graph_contains_convention_node(convention_engine):
    engine, repo = convention_engine
    graph = engine.get_graph(repo)
    conventions = [n for n in graph.nodes if n.kind == "convention"]
    assert {n.qualname for n in conventions} == {"style.compute", "style.ghost"}


def test_convention_node_carries_metadata(convention_engine):
    engine, repo = convention_engine
    graph = engine.get_graph(repo)
    node = next(n for n in graph.nodes if n.qualname == "style.compute")
    assert node.language == "convention"
    assert node.summary == "compute style rules"
    assert node.metadata["title"] == "compute style rules"
    assert node.metadata["scope"] == ["compute"]
    assert node.metadata["rules"] == [
        "Return new objects, never mutate in place.",
        "Public API needs Google-style docstrings.",
    ]
    assert node.metadata["tags"] == ["style", "immutability"]


def test_governs_edge_links_convention_to_scope_module(convention_engine):
    engine, repo = convention_engine
    graph = engine.get_graph(repo)
    convention = next(n for n in graph.nodes if n.qualname == "style.compute")
    module = next(
        n
        for n in graph.nodes
        if n.qualname == "compute" and n.kind in ("module", "package")
    )
    governs = [
        e for e in graph.edges if e.kind == "governs" and e.source == convention.id
    ]
    assert [e.target for e in governs] == [module.id]
    assert governs[0].provenance == "resolved"


def test_unmatched_scope_is_kept_as_unresolved_ref(convention_engine):
    engine, repo = convention_engine
    graph = engine.get_graph(repo)
    names = {u.name for u in graph.unresolved if u.kind == "governs"}
    assert "nonexistent.pkg" in names


# --- injection into evidence payloads (ac-004 / ac-005 / ac-006) ----------

_INJ_CATALOG_TEMPLATE = """
[[convention]]
id = "c.pkg"
scope = "pkg"
title = "pkg rules"
rules = ["pkg-wide rule"]

[[convention]]
id = "c.pkg.sub"
scope = "pkg.sub"
title = "sub rules"
rules = ["sub-specific rule"]

[[convention]]
id = "c.pkg.extra-a"
scope = "pkg"
title = "extra a"
rules = ["filler a"]

[[convention]]
id = "c.pkg.extra-b"
scope = "pkg"
title = "extra b"
rules = ["filler b"]

[[convention]]
id = "c.long"
scope = "longmod"
title = "long rules"
rules = ["{long_rule}"]
"""


@pytest.fixture
def injection_query(tmp_path):
    repo = tmp_path / "inj_repo"
    _write(repo / "pkg" / "__init__.py", '"""pkg."""\n')
    _write(
        repo / "pkg" / "mod.py",
        '"""mod."""\n\n\ndef shallow():\n    """Shallow fn."""\n    return 1\n',
    )
    _write(repo / "pkg" / "sub" / "__init__.py", '"""sub."""\n')
    _write(
        repo / "pkg" / "sub" / "mod.py",
        '"""deep mod."""\n\n\ndef deep():\n    """Deep fn."""\n    return 2\n',
    )
    _write(
        repo / "pkgx.py",
        '"""pkgx."""\n\n\ndef outside():\n    """Out of scope."""\n    return 3\n',
    )
    _write(
        repo / "longmod.py",
        '"""longmod."""\n\n\ndef lf():\n    """Long-rule fn."""\n    return 4\n',
    )
    catalog = tmp_path / "inj_catalog.toml"
    catalog.write_text(
        _INJ_CATALOG_TEMPLATE.format(long_rule="r" * (_MAX_CONVENTION_CHARS + 300)),
        encoding="utf-8",
    )
    engine = DiscoveryEngine(
        DiscoveryConfig(cache_dir=tmp_path / "inj_cache"),
        overlays=[CatalogOverlay(catalog, name="inj")],
    )
    return engine.query(str(repo))


def test_describe_injects_conventions_for_in_scope_symbol(injection_query):
    detail = EvidenceBuilder(injection_query).describe("pkg.mod.shallow", False, None)
    assert detail["conventions"]
    entry = detail["conventions"][0]
    assert set(entry) == {"id", "title", "scope", "rules", "tags"}


def test_describe_out_of_scope_symbol_gets_empty_list(injection_query):
    # "pkgx" must NOT match scope "pkg" (dot-boundary matching).
    detail = EvidenceBuilder(injection_query).describe("pkgx.outside", False, None)
    assert detail["conventions"] == []


def test_most_specific_scope_first_and_count_capped(injection_query):
    detail = EvidenceBuilder(injection_query).describe("pkg.sub.mod.deep", False, None)
    entries = detail["conventions"]
    # four conventions match (c.pkg, c.pkg.sub, two fillers) but the
    # count is capped and the longest-scope match leads.
    assert len(entries) == _MAX_CONVENTIONS
    assert entries[0]["id"] == "c.pkg.sub"


def test_overlong_rules_text_is_truncated(injection_query):
    detail = EvidenceBuilder(injection_query).describe("longmod.lf", False, None)
    rules = detail["conventions"][0]["rules"]
    assert rules.endswith("... (truncated)")
    assert len(rules) <= _MAX_CONVENTION_CHARS + len("\n... (truncated)")


def test_find_capability_matches_carry_conventions(injection_query):
    result = EvidenceBuilder(injection_query).find_capability("shallow", 8)
    assert result["matches"]
    assert all("conventions" in m for m in result["matches"])
    shallow = next(
        m for m in result["matches"] if m["node"]["qualname"] == "pkg.mod.shallow"
    )
    assert shallow["conventions"]
