"""Engine configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Directory / file glob patterns never walked. Covers the common build
# outputs and caches across the ecosystems molmcp targets.
DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "site-packages",
    ".eggs",
    "*.egg-info",
    "target",
    "cmake-build-*",
    ".idea",
    ".vscode",
    ".molmcp",
)


def default_cache_dir() -> Path:
    """Resolve the on-disk cache root.

    ``MOLMCP_CACHE_DIR`` wins; otherwise ``XDG_CACHE_HOME`` (or
    ``~/.cache``) under ``molmcp/discovery``.
    """
    env = os.environ.get("MOLMCP_CACHE_DIR")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "molmcp" / "discovery"


@dataclass(slots=True)
class DiscoveryConfig:
    """Tunable knobs for the discovery engine.

    All fields have working defaults; tests pass an explicit
    ``cache_dir`` so they never touch the user's real cache.
    """

    cache_dir: Path = field(default_factory=default_cache_dir)
    max_file_bytes: int = 1024 * 1024
    excludes: tuple[str, ...] = DEFAULT_EXCLUDES
    max_snapshots_per_spec: int = 3
    max_cache_age_days: int = 30
    # Ceiling on the shared extraction cache. Retention by age does not bound
    # it: an indexed environment of tens of thousands of files is all current,
    # none of it stale, and left uncapped it reached gigabytes in normal use.
    max_extract_cache_bytes: int = 512 * 1024 * 1024
    watch: bool = False
    watch_interval: float = 5.0
    github_token: str | None = None

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        if self.github_token is None:
            self.github_token = os.environ.get("GITHUB_TOKEN") or None
