"""molmcp is configured by settings and CLI flags, never by the environment.

An env var is invisible configuration: it does not show up in
``molmcp config list``, it is not there when the next shell starts, and two
plane servers launched by different clients can disagree about it without
either being wrong. Everything molmcp decides for itself therefore lives in
``~/.molmcp/settings.json``.

Two exceptions, both about secrets rather than configuration, are named
below with the reason they stay.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "molmcp"

#: Where reading the environment is still correct, and why.
_ALLOWED: dict[str, str] = {
    # A bearer token must not sit in a settings file; the config names the
    # variable that holds it, which is the point of the mechanism.
    "server.py": "bearer token indirection (server.auth_token_env)",
    "runtime.py": "registry credential headers reference ${VAR}",
    # Same reasoning: a GitHub PAT belongs in the environment, not on disk.
    "discovery/config.py": "GITHUB_TOKEN fallback for the GitHub source",
    # Passes an environment through to a child process; reads nothing.
    "helpers/subprocess.py": "builds the child env for run_safe",
}


def _reads_environment(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}:
            value = node.value
            if isinstance(value, ast.Name) and value.id == "os":
                return True
        if isinstance(node, ast.Name) and node.id == "getenv":
            return True
    return False


@pytest.mark.parametrize("path", sorted(SRC.rglob("*.py")), ids=lambda p: p.name)
def test_no_module_reads_the_environment_for_configuration(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))

    if not _reads_environment(tree):
        return

    assert path.relative_to(SRC).as_posix() in _ALLOWED, (
        f"{path.relative_to(SRC)} reads the environment. Configuration belongs "
        f"in settings (see molmcp.settings); add it to _ALLOWED only if it is "
        f"a secret that must not be written to disk."
    )


def test_the_allowlist_does_not_rot():
    """Every exemption must still be a module that reads the environment."""
    stale = [
        name
        for name in _ALLOWED
        if not (SRC / name).is_file()
        or not _reads_environment(ast.parse((SRC / name).read_text()))
    ]

    assert stale == []
