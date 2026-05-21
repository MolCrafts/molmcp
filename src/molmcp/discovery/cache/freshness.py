"""Freshness tracking — change detection between snapshots.

Two cheap operations:
  * :meth:`FreshnessTracker.changes` diffs a previous snapshot's files
    against a freshly-walked one (added / changed / removed).
  * :meth:`FreshnessTracker.is_stale` does a stat-only check of a
    snapshot's known files (edits + deletions) — used by the local
    watcher in stage 5.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..schema import FileRecord
from ..source import Snapshot
from ..source.walk import WalkedFile


@dataclass(slots=True)
class ChangeSet:
    """The file-level difference between two snapshots."""

    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.changed or self.removed)

    def to_dict(self) -> dict:
        return {
            "added": list(self.added),
            "changed": list(self.changed),
            "removed": list(self.removed),
            "unchanged_count": len(self.unchanged),
        }


class FreshnessTracker:
    """Detects whether indexed source has drifted from disk."""

    @staticmethod
    def changes(
        previous_files: list[FileRecord], current_files: list[WalkedFile]
    ) -> ChangeSet:
        previous = {f.path: f.content_hash for f in previous_files}
        current = {f.rel_path: f.content_hash for f in current_files}
        return ChangeSet(
            added=sorted(p for p in current if p not in previous),
            changed=sorted(
                p
                for p in current
                if p in previous and current[p] != previous[p]
            ),
            removed=sorted(p for p in previous if p not in current),
            unchanged=sorted(
                p
                for p in current
                if p in previous and current[p] == previous[p]
            ),
        )

    @staticmethod
    def is_stale(snapshot: Snapshot) -> bool:
        """True if any known file of ``snapshot`` was edited or removed.

        A stat-only check (no hashing). It does not detect brand-new
        files — a full re-resolve does that.
        """
        for wf in snapshot.files:
            try:
                stat = os.stat(wf.abs_path)
            except OSError:
                return True
            if stat.st_size != wf.size or stat.st_mtime != wf.mtime:
                return True
        return False
