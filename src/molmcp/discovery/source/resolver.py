"""Source resolution: turn a spec string into an immutable Snapshot.

Spec forms:
  * ``<path>`` or ``local:<path>`` — a local directory
  * ``pkg:<importable-name>`` — an installed Python package
  * ``github:owner/repo[@ref]`` — a GitHub repository (Stage 5)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .walk import WalkedFile


class SourceError(RuntimeError):
    """A source spec could not be resolved."""


@dataclass(frozen=True, slots=True)
class SnapshotId:
    """Identity of one indexed source snapshot."""

    origin: str  # "local" | "github"
    key: str  # "hash" | "commit"
    digest: str

    def __str__(self) -> str:
        return f"{self.origin}:{self.key}:{self.digest}"

    @property
    def slug(self) -> str:
        """Filesystem-safe form for use as a cache directory name."""
        return re.sub(r"[^A-Za-z0-9._-]", "_", str(self))


@dataclass(frozen=True, slots=True)
class Snapshot:
    """An immutable, content-identified unit of indexable source."""

    snapshot_id: str
    origin: str
    spec: str
    root_dir: Path
    scope: str | None
    ref: str | None
    commit: str | None
    created_at: float
    files: tuple[WalkedFile, ...]

    @property
    def file_count(self) -> int:
        return len(self.files)


class SourceResolver:
    """Resolves a spec string to a :class:`Snapshot`."""

    def __init__(self, config) -> None:
        self.config = config

    def resolve(self, spec: str) -> Snapshot:
        spec = spec.strip()
        if not spec:
            raise SourceError("empty source spec")
        if spec.startswith("github:"):
            from .github import resolve_github

            return resolve_github(spec, self.config)
        from .local import resolve_local_path, resolve_pkg

        if spec.startswith("pkg:"):
            return resolve_pkg(spec[4:].strip(), spec, self.config)
        path = spec[6:].strip() if spec.startswith("local:") else spec
        return resolve_local_path(Path(path).expanduser(), spec, self.config)
