"""Source resolution: specs -> immutable snapshots."""

from __future__ import annotations

from .resolver import Snapshot, SnapshotId, SourceError, SourceResolver
from .walk import WalkedFile, walk_files

__all__ = [
    "Snapshot",
    "SnapshotId",
    "SourceError",
    "SourceResolver",
    "WalkedFile",
    "walk_files",
]
