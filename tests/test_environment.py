"""RED unit tests for the (not-yet-written) ``molmcp.environment`` module.

These tests pin the contract of the environment auto-discovery policy engine
described in ``.claude/specs/env-auto-discovery-01-discover.md``:

  * ``resolve_site_paths`` — pure locator normalization (no target-python
    execution), fail-closed on unresolvable locators.
  * ``discover_sources`` — layered family identification (entry-point group /
    ``molcrafts`` keyword / PEP 610 editable / ``MOLMCP_DISCOVER`` override)
    and spec emission (``pkg:<top_level>`` for self, ``local:<pkg-dir>`` for
    foreign), fail-soft per-dist.

The module does not exist yet, so importing it at collection time is the
expected RED state (collection error). Every case below encodes the eventual
GREEN behaviour.

Determinism: no wall-clock, no network, no import/execution of the enumerated
dists. Foreign enumeration runs against REAL hand-written ``*.dist-info``
directories on disk (exercising ``importlib.metadata.distributions(path=...)``
for real); the self-env case follows the ``tests/registry/test_entrypoints.py``
monkeypatch template for ``importlib.metadata``.
"""

from __future__ import annotations

import dataclasses
import importlib.metadata
import json
import re
from pathlib import Path
from typing import NamedTuple

import pytest

import molmcp.environment as environment
from molmcp.config import ConfigurationError
from molmcp.discovery import DiscoveryConfig
from molmcp.discovery.source import SourceResolver
from molmcp.environment import (
    DiscoveredSource,
    EnvironmentReport,
    discover_sources,
    resolve_site_paths,
)

# The frozen diagnostic alphabet for ``identified_by`` (wire-format literals,
# not enum members — pinned per house rule).
_SIGNAL_LITERALS = {"entry_point", "keyword", "editable", "override"}
_PEP503 = re.compile(r"[-_.]+")


# --------------------------------------------------------------------------- #
# Fixture builders (real on-disk dist-info; no installed packages required).
# --------------------------------------------------------------------------- #
def _norm(name: str) -> str:
    """PEP 503 canonical form: lowercase, runs of ``-_.`` folded to ``-``."""
    return _PEP503.sub("-", name).lower()


def _wheel_escape(name: str) -> str:
    """Escape a distribution name for the ``<name>-<ver>.dist-info`` dir name."""
    return re.sub(r"[^\w\d.]+", "_", name)


def _write_dist(
    site_packages: Path,
    name: str,
    *,
    version: str = "1.0.0",
    keywords: str | None = None,
    entry_points: dict[str, dict[str, str]] | None = None,
    top_level: str | None = None,
    direct_url: str | None = None,
) -> Path:
    """Write a fake ``*.dist-info`` dir and return its path.

    Content is fabricated but structurally real, so
    ``importlib.metadata.distributions(path=[site_packages])`` yields a genuine
    ``PathDistribution`` exposing metadata / entry_points / read_text.
    """
    dist_info = site_packages / f"{_wheel_escape(name)}-{version}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)

    meta = ["Metadata-Version: 2.1", f"Name: {name}", f"Version: {version}"]
    if keywords is not None:
        meta.append(f"Keywords: {keywords}")
    (dist_info / "METADATA").write_text("\n".join(meta) + "\n", encoding="utf-8")

    if entry_points is not None:
        lines: list[str] = []
        for group, entries in entry_points.items():
            lines.append(f"[{group}]")
            for key, value in entries.items():
                lines.append(f"{key} = {value}")
            lines.append("")
        (dist_info / "entry_points.txt").write_text("\n".join(lines), encoding="utf-8")

    if top_level is not None:
        (dist_info / "top_level.txt").write_text(top_level + "\n", encoding="utf-8")

    if direct_url is not None:
        (dist_info / "direct_url.json").write_text(direct_url, encoding="utf-8")

    return dist_info


def _make_pkg(root: Path, *parts: str) -> Path:
    """Create ``root/parts.../__init__.py`` and return the package directory."""
    pkg_dir = root.joinpath(*parts)
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    return pkg_dir


def _editable_url(checkout: Path) -> str:
    """A PEP 610 ``direct_url.json`` blob marking an editable install."""
    return json.dumps({"url": checkout.as_uri(), "dir_info": {"editable": True}})


def _by_distribution(report: EnvironmentReport) -> dict[str, DiscoveredSource]:
    """Index a report's sources by PEP 503-normalized distribution name."""
    return {_norm(src.distribution): src for src in report.sources}


def _spec_path(source: DiscoveredSource) -> Path:
    """The filesystem path inside a ``local:<abspath>`` spec."""
    assert source.spec.startswith("local:"), source.spec
    return Path(source.spec[len("local:") :])


# --------------------------------------------------------------------------- #
# resolve_site_paths — locator normalization (Task 1).
# --------------------------------------------------------------------------- #
def test_resolve_site_paths_passthrough_site_packages_dir(tmp_path):
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    result = resolve_site_paths(str(site_packages))
    assert all(isinstance(path, Path) for path in result)
    assert site_packages.resolve() in {path.resolve() for path in result}


def test_resolve_site_paths_passthrough_dir_with_dist_info(tmp_path):
    # Not named "site-packages", but contains a *.dist-info -> still a passthrough.
    holder = tmp_path / "lib-store"
    holder.mkdir()
    _write_dist(holder, "Foo")
    result = resolve_site_paths(str(holder))
    assert holder.resolve() in {path.resolve() for path in result}


def test_resolve_site_paths_posix_venv_root(tmp_path):
    venv = tmp_path / "venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    site_packages = venv / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    result = resolve_site_paths(str(venv))
    assert site_packages.resolve() in {path.resolve() for path in result}


def test_resolve_site_paths_python_executable_without_execution(tmp_path):
    env_root = tmp_path / "env"
    bindir = env_root / "bin"
    bindir.mkdir(parents=True)
    exe = bindir / "python"
    # A plain text stub: the locator must be derived structurally, never run.
    exe.write_text("#!/bin/sh\nexit 47\n", encoding="utf-8")
    site_packages = env_root / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    result = resolve_site_paths(str(exe))
    assert site_packages.resolve() in {path.resolve() for path in result}


def test_resolve_site_paths_nonexistent_locator_fails_closed(tmp_path):
    with pytest.raises(ConfigurationError):
        resolve_site_paths(str(tmp_path / "does-not-exist"))


def test_resolve_site_paths_no_site_packages_fails_closed(tmp_path):
    # An existing directory that is neither a site-packages nor a venv root.
    empty = tmp_path / "just-a-dir"
    empty.mkdir()
    with pytest.raises(ConfigurationError):
        resolve_site_paths(str(empty))


# --------------------------------------------------------------------------- #
# Foreign enumeration — real dist-info fixture (Task 2).
# --------------------------------------------------------------------------- #
class ForeignEnv(NamedTuple):
    report: EnvironmentReport
    site_packages: Path
    checkout_src: Path
    checkout_flat: Path
    checkout_tri: Path


@pytest.fixture
def foreign_env(tmp_path, monkeypatch) -> ForeignEnv:
    """A synthetic foreign env: one dist per signal plus a non-family wheel."""
    monkeypatch.delenv("MOLMCP_DISCOVER", raising=False)

    site_packages = tmp_path / "env" / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)

    # Non-editable family wheels: package dir lives beside the dist-info.
    _make_pkg(site_packages, "foo")
    _make_pkg(site_packages, "bar")
    _make_pkg(site_packages, "numpyish")

    # Editable checkouts (src-layout, flat-layout, and a three-signal one).
    checkout_src = tmp_path / "checkout_src"
    _make_pkg(checkout_src, "src", "baz")
    checkout_flat = tmp_path / "checkout_flat"
    _make_pkg(checkout_flat, "qux")
    checkout_tri = tmp_path / "checkout_tri"
    _make_pkg(checkout_tri, "src", "tri")

    # (a) entry-point group only.
    _write_dist(
        site_packages,
        "Foo",
        entry_points={"molmcp.providers": {"foo": "foo:provider"}},
        top_level="foo",
    )
    # (b) molcrafts keyword only.
    _write_dist(site_packages, "Bar", keywords="molcrafts, chemistry", top_level="bar")
    # (c) editable (PEP 610) only, src-layout.
    _write_dist(
        site_packages,
        "Baz",
        top_level="baz",
        direct_url=_editable_url(checkout_src),
    )
    # editable only, flat-layout.
    _write_dist(
        site_packages,
        "Qux",
        top_level="qux",
        direct_url=_editable_url(checkout_flat),
    )
    # No signals at all -> must not be emitted.
    _write_dist(
        site_packages, "Numpyish", keywords="arrays, math", top_level="numpyish"
    )
    # All three signals at once, editable src-layout.
    _write_dist(
        site_packages,
        "Tri",
        keywords="molcrafts",
        entry_points={"molmcp.capabilities": {"t": "tri:cap"}},
        top_level="tri",
        direct_url=_editable_url(checkout_tri),
    )

    report = discover_sources(str(site_packages))
    return ForeignEnv(
        report=report,
        site_packages=site_packages.resolve(),
        checkout_src=checkout_src.resolve(),
        checkout_flat=checkout_flat.resolve(),
        checkout_tri=checkout_tri.resolve(),
    )


def test_foreign_signal_a_entry_point_group(foreign_env):
    source = _by_distribution(foreign_env.report)["foo"]
    assert source.identified_by == ("entry_point",)
    assert _spec_path(source).resolve() == (foreign_env.site_packages / "foo").resolve()


def test_foreign_signal_b_molcrafts_keyword(foreign_env):
    source = _by_distribution(foreign_env.report)["bar"]
    assert source.identified_by == ("keyword",)
    assert _spec_path(source).resolve() == (foreign_env.site_packages / "bar").resolve()


def test_foreign_editable_src_layout_points_at_package_not_checkout_root(foreign_env):
    source = _by_distribution(foreign_env.report)["baz"]
    assert "editable" in source.identified_by
    package_dir = _spec_path(source).resolve()
    assert package_dir == (foreign_env.checkout_src / "src" / "baz").resolve()
    # Deliberately NOT the checkout / repo root, nor the bare src dir.
    assert package_dir != foreign_env.checkout_src
    assert package_dir != (foreign_env.checkout_src / "src").resolve()


def test_foreign_editable_flat_layout_points_at_package(foreign_env):
    source = _by_distribution(foreign_env.report)["qux"]
    assert "editable" in source.identified_by
    package_dir = _spec_path(source).resolve()
    assert package_dir == (foreign_env.checkout_flat / "qux").resolve()
    assert package_dir != foreign_env.checkout_flat


def test_foreign_non_family_wheel_is_not_emitted(foreign_env):
    assert "numpyish" not in _by_distribution(foreign_env.report)


def test_foreign_three_signals_records_all(foreign_env):
    source = _by_distribution(foreign_env.report)["tri"]
    assert set(source.identified_by) == {"entry_point", "keyword", "editable"}
    assert (
        _spec_path(source).resolve()
        == (foreign_env.checkout_tri / "src" / "tri").resolve()
    )


def test_foreign_sources_sorted_by_name(foreign_env):
    names = [src.name for src in foreign_env.report.sources]
    assert names == sorted(names)


def test_foreign_report_metadata(foreign_env):
    report = foreign_env.report
    assert report.is_self is False
    assert report.locator is not None
    assert foreign_env.site_packages in {path.resolve() for path in report.site_paths}


def test_foreign_report_to_dict_is_json_able(foreign_env):
    report = foreign_env.report
    payload = report.to_dict()
    assert isinstance(payload, dict)
    blob = json.dumps(payload)  # must not raise: fully JSON-able
    foo = _by_distribution(report)["foo"]
    assert foo.spec in blob  # specs survive the round-trip


def test_foreign_malformed_direct_url_is_skipped_others_enumerate(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("MOLMCP_DISCOVER", raising=False)
    site_packages = tmp_path / "sp"
    site_packages.mkdir()
    _make_pkg(site_packages, "good")

    # A family (keyword) dist whose direct_url.json is corrupt and whose
    # package dir is absent -> fail-soft skip, never a bad spec.
    _write_dist(site_packages, "Good", keywords="molcrafts", top_level="good")
    _write_dist(
        site_packages,
        "Rotten",
        keywords="molcrafts",
        top_level="rotten",
        direct_url="{ this is not valid json",
    )

    report = discover_sources(str(site_packages))
    by_dist = _by_distribution(report)
    assert "good" in by_dist
    assert "rotten" not in by_dist
    assert any("rotten" in str(entry).lower() for entry in report.skipped)


def test_foreign_editable_src_layout_without_top_level_txt_finds_real_package(
    tmp_path, monkeypatch
):
    """PEP 660 editable installs ship no ``top_level.txt``.

    The import package name is then NOT derivable from the distribution name:
    ``molcrafts-molvis`` imports as ``molvis``. Probing only the dist-name
    guess (``molcrafts_molvis``) drops a perfectly importable checkout as
    "no importable package directory found"; the real package directory must
    be located from the editable checkout itself.
    """
    monkeypatch.delenv("MOLMCP_DISCOVER", raising=False)

    checkout = tmp_path / "molvis"
    package_dir = _make_pkg(checkout, "src", "molvis")

    site_packages = tmp_path / "env" / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    _write_dist(
        site_packages,
        "molcrafts-molvis",
        top_level=None,  # PEP 660 editable wheels omit top_level.txt
        direct_url=_editable_url(checkout),
    )

    report = discover_sources(str(site_packages))
    by_dist = _by_distribution(report)

    assert not any("molvis" in str(entry).lower() for entry in report.skipped)
    assert "molcrafts-molvis" in by_dist
    source = by_dist["molcrafts-molvis"]
    assert "editable" in source.identified_by
    assert _spec_path(source).resolve() == package_dir.resolve()
    assert source.spec == f"local:{package_dir.resolve()}"


# --------------------------------------------------------------------------- #
# Self-env — monkeypatched distributions + resolver acceptance (Task 3).
# --------------------------------------------------------------------------- #
def test_self_env_emits_pkg_spec_and_resolver_accepts_it(tmp_path, monkeypatch):
    monkeypatch.delenv("MOLMCP_DISCOVER", raising=False)
    site_packages = tmp_path / "self-sp"
    site_packages.mkdir()
    _write_dist(
        site_packages,
        "fixture-pkg",
        entry_points={"molmcp.providers": {"x": "fixture_pkg:greet"}},
        top_level="fixture_pkg",
    )
    # Materialize real PathDistributions before patching the global finder.
    real_dists = list(importlib.metadata.distributions(path=[str(site_packages)]))
    monkeypatch.setattr(
        environment.importlib.metadata,
        "distributions",
        lambda *args, **kwargs: list(real_dists),
    )

    report = discover_sources(None)
    assert report.is_self is True
    assert report.site_paths == ()
    assert len(report.sources) == 1
    source = report.sources[0]
    assert source.spec == "pkg:fixture_pkg"
    assert source.identified_by == ("entry_point",)

    # The emitted spec must be consumable by the existing SourceResolver
    # (pkg:fixture_pkg resolves because tests/fixture_pkg is importable).
    resolver = SourceResolver(DiscoveryConfig(cache_dir=tmp_path / "cache"))
    snapshot = resolver.resolve(source.spec)
    assert snapshot.spec == "pkg:fixture_pkg"


# --------------------------------------------------------------------------- #
# MOLMCP_DISCOVER override / exclude, PEP 503 matching (Task 4).
# --------------------------------------------------------------------------- #
def test_molmcp_discover_force_include_records_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MOLMCP_DISCOVER", "+extra,-mol.py")
    site_packages = tmp_path / "sp"
    site_packages.mkdir()
    _make_pkg(site_packages, "extra")
    _make_pkg(site_packages, "mol_py")

    # 'extra' carries no a/b/c signal; only the +override forces it in.
    _write_dist(site_packages, "extra", top_level="extra")
    # 'Mol-Py' IS a family match (keyword) but is force-excluded below.
    _write_dist(site_packages, "Mol-Py", keywords="molcrafts", top_level="mol_py")

    report = discover_sources(str(site_packages))
    by_dist = _by_distribution(report)
    assert "extra" in by_dist
    assert by_dist["extra"].identified_by == ("override",)


def test_molmcp_discover_force_exclude_uses_pep503_normalization(tmp_path, monkeypatch):
    # NOTE (deviation): the spec sketch wrote ``-molpy``; under PEP 503 that
    # canonicalizes to ``molpy`` and can NOT match ``Mol-Py`` (-> ``mol-py``).
    # We use ``-mol.py`` (one of the two spellings the task named) so the
    # exclusion is a genuine PEP 503 match across ``.`` / ``-`` / case.
    monkeypatch.setenv("MOLMCP_DISCOVER", "+extra,-mol.py")
    site_packages = tmp_path / "sp"
    site_packages.mkdir()
    _make_pkg(site_packages, "extra")
    _make_pkg(site_packages, "mol_py")
    _write_dist(site_packages, "extra", top_level="extra")
    _write_dist(site_packages, "Mol-Py", keywords="molcrafts", top_level="mol_py")

    report = discover_sources(str(site_packages))
    assert "mol-py" not in _by_distribution(report)
    assert "mol-py" in {_norm(str(entry)) for entry in report.excluded}


def test_molrs_not_auto_discovered_as_python_api_source(tmp_path, monkeypatch):
    """molrs is MolCrafts-family but not a public Python API surface.

    Agents use ``molpy.Frame``; auto-discovery must not index ``molrs`` as a
    codegraph source. ``MOLMCP_DISCOVER=+molrs`` can re-enable for debugging.
    """
    monkeypatch.delenv("MOLMCP_DISCOVER", raising=False)
    site_packages = tmp_path / "sp"
    site_packages.mkdir()
    _make_pkg(site_packages, "molrs")
    _make_pkg(site_packages, "molpy")
    _write_dist(
        site_packages, "molcrafts-molrs", keywords="molcrafts", top_level="molrs"
    )
    _write_dist(
        site_packages, "molcrafts-molpy", keywords="molcrafts", top_level="molpy"
    )

    report = discover_sources(str(site_packages))
    by_dist = _by_distribution(report)
    assert any("molpy" in d for d in by_dist)
    assert not any("molrs" in d for d in by_dist)
    assert any("molrs" in _norm(str(e)) for e in report.excluded)

    # Explicit opt-in re-enables molrs as a source.
    monkeypatch.setenv("MOLMCP_DISCOVER", "+molcrafts-molrs")
    report2 = discover_sources(str(site_packages))
    by2 = _by_distribution(report2)
    assert any("molrs" in d for d in by2)


# --------------------------------------------------------------------------- #
# identified_by literal contract (Task 5).
# --------------------------------------------------------------------------- #
def test_identified_by_literals_are_wire_format_strings(foreign_env):
    seen: set[str] = set()
    for source in foreign_env.report.sources:
        for literal in source.identified_by:
            assert isinstance(literal, str)
            seen.add(literal)
    # Only the four frozen diagnostic literals may appear.
    assert seen <= _SIGNAL_LITERALS
    # The three non-override signals are all present in this fixture.
    assert {"entry_point", "keyword", "editable"} <= seen


# --------------------------------------------------------------------------- #
# Static boundary assertions on the module source (Task 6).
# --------------------------------------------------------------------------- #
def test_environment_module_has_no_execution_or_forbidden_imports():
    source = Path(environment.__file__).read_text(encoding="utf-8")
    for banned in ("subprocess", "os.system", "runpy", "import_module"):
        assert banned not in source, f"environment.py must not reference {banned!r}"
    for banned_import in (
        "molmcp.cli",
        "molmcp.runtime",
        "molmcp.server",
        "molmcp.discovery",
        "fastmcp",
    ):
        assert banned_import not in source, (
            f"environment.py must not import {banned_import!r}"
        )


def test_environment_module_has_no_hardcoded_family_names():
    """Discovery must not hardcode a positive family allowlist.

    An intentional *exclude* set for non-public API distributions (e.g. molrs)
    is allowed — strip that constant and comments before scanning.
    """
    import re

    source = Path(environment.__file__).read_text(encoding="utf-8")
    source = re.sub(
        r"_NON_PYTHON_API_DISTRIBUTIONS[^=]*=\s*frozenset\(\s*\{.*?\}\s*\)",
        "",
        source,
        flags=re.DOTALL,
    )
    source = re.sub(r"#.*?$", "", source, flags=re.MULTILINE)
    forbidden = {"molpy", "molpack", "molq", "molrs", "molvis", "molexp"}
    present = {name for name in forbidden if name in source}
    assert present == set(), f"no hardcoded family allowlist allowed; found {present}"


# --------------------------------------------------------------------------- #
# Immutability (Task 7).
# --------------------------------------------------------------------------- #
def test_discovered_source_is_frozen():
    source = DiscoveredSource(
        name="foo",
        spec="pkg:foo",
        identified_by=("entry_point",),
        distribution="Foo",
        version="1.0.0",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        source.name = "bar"  # type: ignore[misc]


def test_environment_report_is_frozen():
    report = EnvironmentReport(
        locator=None,
        is_self=True,
        site_paths=(),
        sources=(),
        skipped=(),
        excluded=(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.is_self = False  # type: ignore[misc]
