"""The package version has exactly one source of truth.

`__version__` used to be a literal in `__init__.py` beside the real version in
`pyproject.toml`. 0.5.1 shipped with the two disagreeing — the distribution
said 0.5.1 and `molmcp.__version__` still said 0.5.0 — because a release bumps
the manifest and nobody remembers the copy.
"""

from __future__ import annotations

import importlib.metadata
import re
import tomllib
from pathlib import Path

import molmcp

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


class TestVersionAgrees:
    def test_dunder_version_matches_the_installed_distribution(self):
        assert molmcp.__version__ == importlib.metadata.version("molcrafts-molmcp")

    def test_dunder_version_matches_pyproject(self):
        declared = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"][
            "version"
        ]
        assert molmcp.__version__ == declared

    def test_no_hardcoded_version_literal_remains(self):
        source = (Path(molmcp.__file__).parent / "__init__.py").read_text(
            encoding="utf-8"
        )
        assert not re.search(r'__version__\s*=\s*["\']\d+\.\d+', source), (
            "__version__ must be derived from package metadata, not written "
            "out again where a release bump will miss it"
        )
