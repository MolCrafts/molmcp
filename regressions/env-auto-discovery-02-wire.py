#!/usr/bin/env python3
"""Regression example: auto-discovery wired into app assembly (02-wire).

Standalone (no pytest dependency). Builds a throwaway ``site-packages`` under a
``tempfile.TemporaryDirectory`` holding one hand-written fake ``*.dist-info``
family distribution (flagged by a ``molcrafts`` keyword) beside a real package
directory, then drives the app-assembly PUBLIC API exactly as an installed
library user would::

    config = molmcp.config.load_config(None, env_locator=<site-packages>)
    collection = molmcp.runtime.build_collection(config)
    info = collection.info()

and asserts the documented reference outcome (spec:
``.claude/specs/env-auto-discovery-02-wire.md``, Testing strategy -> Regression
example; acceptance ``ac-010``). The feature has no literature basis, so the
assertions pin the spec's documented expected output:

    * the unconditional ``workspace`` source maps to the (neutral) cwd;
    * the discovered ``Molfoo`` dist appears as source ``molfoo`` whose spec is
      ``local:<site-packages>/molfoo`` (the foreign package directory);
    * ``info()["configuration"]["discovery"]`` surfaces the environment
      ``site_paths`` and the ``["keyword"]`` ``identified_by`` signal;
    * ``molfoo`` also appears under ``info()["sources"]``.

The script runs from a fresh, empty temp cwd so no ambient ``molcrafts.json``
interferes and the ``workspace`` source is that temp directory.

Run directly::

    python regressions/env-auto-discovery-02-wire.py

Prints the resolved sources plus the discovery diagnostics and exits 0 on
success, or raises ``AssertionError`` (non-zero exit) on any mismatch. Also
collectable by the project's test runner via ``test_env_auto_discovery_02_wire``.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from molmcp.config import load_config
from molmcp.runtime import build_collection

_WHEEL_ESCAPE = re.compile(r"[^\w\d.]+")


def _wheel_escape(name: str) -> str:
    """Escape a distribution name for its ``<name>-<version>.dist-info`` dir."""
    return _WHEEL_ESCAPE.sub("_", name)


def _make_pkg(root: Path, *parts: str) -> Path:
    """Create ``root/parts.../__init__.py`` and return the package directory."""
    pkg_dir = root.joinpath(*parts)
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    return pkg_dir


def _write_dist(
    site_packages: Path,
    name: str,
    *,
    version: str,
    keywords: str,
    top_level: str,
) -> None:
    """Write a fabricated-but-structurally-real ``*.dist-info`` directory.

    ``importlib.metadata.distributions(path=[site_packages])`` then yields a
    genuine ``PathDistribution`` for it, so no package is ever installed.
    """
    dist_info = site_packages / f"{_wheel_escape(name)}-{version}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    meta = [
        "Metadata-Version: 2.1",
        f"Name: {name}",
        f"Version: {version}",
        f"Keywords: {keywords}",
    ]
    (dist_info / "METADATA").write_text("\n".join(meta) + "\n", encoding="utf-8")
    (dist_info / "top_level.txt").write_text(top_level + "\n", encoding="utf-8")


def _build_synthetic_env(root: Path) -> tuple[Path, Path]:
    """Populate ``root`` with a synthetic site-packages; return its parts."""
    site_packages = root / "site-packages"
    site_packages.mkdir()
    package_dir = _make_pkg(site_packages, "molfoo")
    _write_dist(
        site_packages,
        "Molfoo",
        version="1.2.3",
        keywords="molcrafts, chemistry",
        top_level="molfoo",
    )
    return site_packages, package_dir


def _require(condition: bool, message: str) -> None:
    """Assert-equivalent that survives ``python -O`` and exits non-zero."""
    if not condition:
        raise AssertionError(message)


def _assert_wiring(
    config: Any,
    info: dict[str, Any],
    workspace: Path,
    site_packages: Path,
    package_dir: Path,
) -> None:
    """Pin the documented end-to-end reference outcome via the public API."""
    want_spec = f"local:{package_dir.resolve()}"
    _require(
        config.sources.get("workspace") == str(workspace.resolve()),
        f"workspace must map to cwd -> {config.sources.get('workspace')}",
    )
    _require(
        config.sources.get("molfoo") == want_spec,
        f"molfoo source spec {config.sources.get('molfoo')} != {want_spec}",
    )

    discovery = info["configuration"].get("discovery")
    _require(discovery is not None, "info configuration.discovery is missing")
    site = [Path(path).resolve() for path in discovery["site_paths"]]
    _require(
        site_packages.resolve() in site,
        f"discovery site_paths {site} omit {site_packages.resolve()}",
    )

    by_name = {source["name"]: source for source in discovery["sources"]}
    _require("molfoo" in by_name, f"discovery.sources omit molfoo -> {sorted(by_name)}")
    molfoo = by_name["molfoo"]
    _require(
        molfoo["spec"] == want_spec,
        f"discovery molfoo spec {molfoo['spec']} != {want_spec}",
    )
    _require(
        molfoo["identified_by"] == ["keyword"],
        f"discovery molfoo identified_by {molfoo['identified_by']} != ['keyword']",
    )
    _require(
        "molfoo" in info["sources"],
        f"info.sources omit the discovered package -> {sorted(info['sources'])}",
    )


def _print_summary(config: Any, info: dict[str, Any]) -> None:
    """Print the public-API diagnostics that answer 'what/why was discovered'."""
    print("config.sources:")
    print(json.dumps(config.sources, indent=2, sort_keys=True))
    print("\ninfo()['configuration']['discovery']:")
    print(json.dumps(info["configuration"]["discovery"], indent=2, sort_keys=True))


def main() -> int:
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="molmcp-wire-regression-") as tmp:
        root = Path(tmp)
        site_packages, package_dir = _build_synthetic_env(root)
        workspace = root / "workspace"  # neutral cwd: no molcrafts.json here
        workspace.mkdir()
        os.chdir(workspace)
        try:
            config = load_config(None, env_locator=str(site_packages))
            collection = build_collection(config)
            info = collection.info()
        finally:
            os.chdir(original_cwd)

        _assert_wiring(config, info, workspace, site_packages, package_dir)
        _print_summary(config, info)

    print(
        "\nOK: no-file load_config folded the synthetic environment via the "
        "public API; the discovered package is a source and info() surfaces "
        "its environment path and identified-by signal."
    )
    return 0


def test_env_auto_discovery_02_wire() -> None:
    """Pytest-collectable entry point; the script needs no pytest to run."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
