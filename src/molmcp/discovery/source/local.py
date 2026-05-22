"""Local + installed-package source resolution."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import time
from pathlib import Path

from ..config import DiscoveryConfig
from .resolver import Snapshot, SnapshotId, SourceError
from .walk import WalkedFile, walk_files


def _package_dir(name: str) -> Path | None:
    """On-disk directory of an importable package (namespace-safe)."""
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError, ModuleNotFoundError):
        return None
    if spec is None:
        return None
    locations = list(spec.submodule_search_locations or [])
    if locations:
        return Path(locations[0])
    if spec.origin and spec.origin not in ("built-in", "frozen"):
        return Path(spec.origin).parent
    return None


def _git_commit(path: Path) -> str | None:
    """Best-effort current commit SHA, for display only."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else None


def _local_digest(files: tuple[WalkedFile, ...]) -> str:
    """Content hash over (path, file-hash) pairs — branch-independent."""
    h = hashlib.sha256()
    for wf in files:
        h.update(wf.rel_path.encode("utf-8"))
        h.update(b"\0")
        h.update(wf.content_hash.encode("utf-8"))
        h.update(b"\n")
    return "sha256-" + h.hexdigest()[:32]


def _build_snapshot(
    root: Path, scope: str | None, spec: str, config: DiscoveryConfig
) -> Snapshot:
    files = tuple(walk_files(root, config, scope))
    snapshot_id = SnapshotId("local", "hash", _local_digest(files))
    return Snapshot(
        snapshot_id=str(snapshot_id),
        origin="local",
        spec=spec,
        root_dir=root,
        scope=scope,
        ref=None,
        commit=_git_commit(root),
        created_at=time.time(),
        files=files,
    )


def resolve_local_path(
    path: Path, spec: str, config: DiscoveryConfig
) -> Snapshot:
    """Resolve a local directory path to a snapshot.

    When the path is itself a Python package (has ``__init__.py``), the
    walk root is set to its parent so module qualnames include the
    package name.
    """
    path = path.resolve()
    if not path.exists():
        raise SourceError(f"path does not exist: {path}")
    if not path.is_dir():
        raise SourceError(f"not a directory: {path}")
    if (path / "__init__.py").is_file():
        return _build_snapshot(path.parent, path.name, spec, config)
    return _build_snapshot(path, None, spec, config)


def resolve_pkg(name: str, spec: str, config: DiscoveryConfig) -> Snapshot:
    """Resolve an installed Python package by import name."""
    if not name:
        raise SourceError("empty package name in 'pkg:' spec")
    pkg_dir = _package_dir(name)
    if pkg_dir is None or not pkg_dir.is_dir():
        raise SourceError(f"package not importable or has no source: {name}")
    return _build_snapshot(pkg_dir.parent, pkg_dir.name, spec, config)
