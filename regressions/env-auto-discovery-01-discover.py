#!/usr/bin/env python3
"""Regression example: ``molmcp.environment.discover_sources`` on a synthetic env.

Standalone (no pytest dependency). Builds a throwaway site-packages under a
``tempfile.TemporaryDirectory`` with four hand-written fake ``*.dist-info``
distributions — one per family signal plus a non-family wheel — then drives the
environment policy engine through its PUBLIC API only and asserts the emitted
``DiscoveredSource`` specs and ``identified_by`` sets equal the documented
reference values below.

Reference values (spec: ``.claude/specs/env-auto-discovery-01-discover.md``,
Testing strategy -> Regression example). The feature has no literature basis, so
the assertions pin the spec's documented expected output:

    Foo    signal (a): a ``molmcp.*`` entry-point group
           -> identified_by == {"entry_point"}
           -> spec == local:<site-packages>/foo
    Bar    signal (b): a ``molcrafts`` keyword
           -> identified_by == {"keyword"}
           -> spec == local:<site-packages>/bar
    Baz    signal (c): an editable PEP 610 ``direct_url.json``
           -> identified_by == {"editable"}
           -> spec == local:<checkout>/src/baz   (the PACKAGE dir, NOT the
                                                   checkout / repo root)
    Plain  no signal (an ordinary third-party wheel)
           -> NOT emitted at all

Run directly::

    python regressions/env-auto-discovery-01-discover.py

Prints the ``EnvironmentReport.to_dict()`` summary and exits 0 on success, or
raises ``AssertionError`` (non-zero exit) on any mismatch. Also collectable by
the project's test runner via ``test_env_auto_discovery_01_discover``.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

from molmcp.environment import EnvironmentReport, discover_sources

_WHEEL_ESCAPE = re.compile(r"[^\w\d.]+")


def _wheel_escape(name: str) -> str:
    """Escape a distribution name for its ``<name>-<version>.dist-info`` dir."""
    return _WHEEL_ESCAPE.sub("_", name)


def _write_dist(
    site_packages: Path,
    name: str,
    *,
    version: str = "1.0.0",
    keywords: str | None = None,
    entry_points: dict[str, dict[str, str]] | None = None,
    top_level: str | None = None,
    direct_url: str | None = None,
) -> None:
    """Write a fabricated-but-structurally-real ``*.dist-info`` directory.

    ``importlib.metadata.distributions(path=[site_packages])`` then yields a
    genuine ``PathDistribution`` for it, so no package is ever installed.
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


def _make_pkg(root: Path, *parts: str) -> Path:
    """Create ``root/parts.../__init__.py`` and return the package directory."""
    pkg_dir = root.joinpath(*parts)
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    return pkg_dir


def _build_synthetic_env(root: Path) -> Path:
    """Populate ``root`` with a synthetic site-packages; return its path."""
    site_packages = root / "site-packages"
    site_packages.mkdir()

    # Package dirs beside the dist-info (non-editable installs).
    for pkg in ("foo", "bar", "plainpkg"):
        _make_pkg(site_packages, pkg)

    # A separate editable checkout with a src-layout package.
    checkout = root / "baz-checkout"
    _make_pkg(checkout, "src", "baz")

    _write_dist(
        site_packages,
        "Foo",
        entry_points={"molmcp.providers": {"foo": "foo:provider"}},
        top_level="foo",
    )
    _write_dist(site_packages, "Bar", keywords="molcrafts, chemistry", top_level="bar")
    _write_dist(
        site_packages,
        "Baz",
        top_level="baz",
        direct_url=json.dumps(
            {"url": checkout.as_uri(), "dir_info": {"editable": True}}
        ),
    )
    _write_dist(site_packages, "Plain", keywords="arrays, math", top_level="plainpkg")
    return site_packages


def _require(condition: bool, message: str) -> None:
    """Assert-equivalent that survives ``python -O`` and exits non-zero."""
    if not condition:
        raise AssertionError(message)


def _print_summary(report: EnvironmentReport) -> None:
    """Print the JSON-able report summary produced by the public API."""
    print("EnvironmentReport.to_dict():")
    print(json.dumps(report.to_dict(), indent=2))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="molmcp-env-regression-") as tmp:
        root = Path(tmp)
        site_packages = _build_synthetic_env(root)

        report = discover_sources(str(site_packages))
        emitted = {source.distribution: source for source in report.sources}

        # Documented reference: exactly the three family dists; Plain dropped.
        expected_pkg_dir = {
            "Foo": site_packages / "foo",
            "Bar": site_packages / "bar",
            "Baz": root / "baz-checkout" / "src" / "baz",
        }
        expected_signals = {
            "Foo": {"entry_point"},
            "Bar": {"keyword"},
            "Baz": {"editable"},
        }

        _require(
            set(emitted) == set(expected_pkg_dir),
            f"emitted dists {sorted(emitted)} != reference {sorted(expected_pkg_dir)}",
        )

        for dist, source in sorted(emitted.items()):
            _require(
                source.spec.startswith("local:"),
                f"{dist}: foreign spec must be local:<abspath> -> {source.spec}",
            )
            got = Path(source.spec[len("local:") :]).resolve()
            want = expected_pkg_dir[dist].resolve()
            _require(got == want, f"{dist}: spec path {got} != reference {want}")

            got_signals = set(source.identified_by)
            _require(
                got_signals == expected_signals[dist],
                f"{dist}: identified_by {got_signals} != {expected_signals[dist]}",
            )

        # The editable spec must point at the package dir, never the repo root.
        baz = Path(emitted["Baz"].spec[len("local:") :]).resolve()
        checkout = (root / "baz-checkout").resolve()
        _require(
            baz != checkout and baz != checkout / "src",
            f"Baz spec must be the package dir, not the checkout root: {baz}",
        )

        _print_summary(report)

    print(
        f"\nOK: {len(report.sources)} family sources discovered "
        "via the public API; all specs and signals match the reference."
    )
    return 0


def test_env_auto_discovery_01_discover() -> None:
    """Pytest-collectable entry point; the script needs no pytest to run."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
