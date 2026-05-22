"""Filesystem walk: collect source files with hashes, honoring excludes.

Applies ``DiscoveryConfig.excludes`` plus a best-effort ``.gitignore``
parser (common cases: comments, blank lines, trailing-slash directories,
basename and path globs). Negation (``!``) is intentionally not handled
in v1 — principle 9, keep it inspectable.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from ..analyzers import language_for_path
from ..config import DiscoveryConfig


@dataclass(frozen=True, slots=True)
class WalkedFile:
    """One source file discovered by the walk."""

    rel_path: str
    abs_path: str
    language: str
    content_hash: str
    size: int
    mtime: float


def load_gitignore(root: Path) -> list[str]:
    """Read top-level ``.gitignore`` patterns, if present."""
    gi = root / ".gitignore"
    if not gi.is_file():
        return []
    patterns: list[str] = []
    try:
        for raw in gi.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                continue
            patterns.append(line)
    except OSError:
        return []
    return patterns


def _matches(rel_posix: str, name: str, patterns: list[str]) -> bool:
    for pat in patterns:
        p = pat.strip().rstrip("/")
        if not p:
            continue
        if p.startswith("/"):
            p = p[1:]
        if "/" in p:
            if fnmatch.fnmatch(rel_posix, p) or fnmatch.fnmatch(
                rel_posix, p + "/*"
            ):
                return True
        elif fnmatch.fnmatch(name, p):
            return True
    return False


def walk_files(
    root: Path,
    config: DiscoveryConfig,
    scope: str | None = None,
) -> list[WalkedFile]:
    """Walk ``root`` (optionally restricted to the ``scope`` subtree).

    Returns recognized source files only, each with a SHA256 content
    hash, sorted by repo-relative path for deterministic snapshot ids.
    """
    root = root.resolve()
    walk_root = (root / scope) if scope else root
    patterns = list(config.excludes) + load_gitignore(root)
    results: list[WalkedFile] = []

    for dirpath, dirnames, filenames in os.walk(walk_root):
        dpath = Path(dirpath)
        # Prune excluded directories in place.
        kept: list[str] = []
        for d in dirnames:
            rel = (dpath / d).relative_to(root).as_posix()
            if not _matches(rel, d, patterns):
                kept.append(d)
        dirnames[:] = sorted(kept)

        for fname in filenames:
            abs_path = dpath / fname
            rel_posix = abs_path.relative_to(root).as_posix()
            if _matches(rel_posix, fname, patterns):
                continue
            language = language_for_path(fname)
            if language is None:
                continue
            try:
                stat = abs_path.stat()
            except OSError:
                continue
            if stat.st_size > config.max_file_bytes:
                continue
            try:
                data = abs_path.read_bytes()
            except OSError:
                continue
            results.append(
                WalkedFile(
                    rel_path=rel_posix,
                    abs_path=str(abs_path),
                    language=language,
                    content_hash=hashlib.sha256(data).hexdigest(),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                )
            )

    results.sort(key=lambda w: w.rel_path)
    return results
