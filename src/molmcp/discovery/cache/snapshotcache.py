"""SnapshotCache — on-disk layout for indexed snapshots.

<cache_dir>/snapshots/<slug>/profiles/<build-id>/manifest.json
                                                /graph.db
                            /raw/         (GitHub sources)
                            /evidence/<query_hash>.json
<cache_dir>/refs/<spec-slug>.json
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import DiscoveryConfig


@dataclass(slots=True)
class _SnapshotEntry:
    snapshot_id: str
    directory: Path
    spec: str
    indexed_at: float


def slugify(value: str) -> str:
    """Filesystem-safe slug for a snapshot id or spec string."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


class SnapshotCache:
    """Owns the on-disk cache directory tree."""

    def __init__(self, config: DiscoveryConfig) -> None:
        self.config = config
        self.root = Path(config.cache_dir)

    @property
    def snapshots_root(self) -> Path:
        return self.root / "snapshots"

    @property
    def refs_root(self) -> Path:
        return self.root / "refs"

    def snapshot_dir(self, snapshot_id: str) -> Path:
        return self.snapshots_root / slugify(snapshot_id)

    def profile_dir(self, snapshot_id: str, build_id: str | None = None) -> Path:
        if build_id is None:
            return self.snapshot_dir(snapshot_id)
        return self.snapshot_dir(snapshot_id) / "profiles" / slugify(build_id)

    def graph_db_path(self, snapshot_id: str, build_id: str | None = None) -> Path:
        return self.profile_dir(snapshot_id, build_id) / "graph.db"

    def manifest_path(self, snapshot_id: str, build_id: str | None = None) -> Path:
        return self.profile_dir(snapshot_id, build_id) / "manifest.json"

    def raw_dir(self, snapshot_id: str) -> Path:
        return self.snapshot_dir(snapshot_id) / "raw"

    def extract_db_path(self) -> Path:
        return self.root / "extract.db"

    def evidence_dir(self, snapshot_id: str) -> Path:
        return self.snapshot_dir(snapshot_id) / "evidence"

    def ref_path(self, spec: str) -> Path:
        return self.refs_root / f"{slugify(spec)}.json"

    def ensure_dir(self, snapshot_id: str, build_id: str | None = None) -> Path:
        d = self.profile_dir(snapshot_id, build_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def has(self, snapshot_id: str, build_id: str | None = None) -> bool:
        """True when both a manifest and a graph.db are present."""
        return (
            self.manifest_path(snapshot_id, build_id).is_file()
            and self.graph_db_path(snapshot_id, build_id).is_file()
        )

    def write_manifest(
        self, snapshot_id: str, manifest: dict, build_id: str | None = None
    ) -> None:
        self.ensure_dir(snapshot_id, build_id)
        self.manifest_path(snapshot_id, build_id).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def read_manifest(
        self, snapshot_id: str, build_id: str | None = None
    ) -> dict | None:
        path = self.manifest_path(snapshot_id, build_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def write_ref(self, spec: str, payload: dict) -> None:
        self.refs_root.mkdir(parents=True, exist_ok=True)
        self.ref_path(spec).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def read_ref(self, spec: str) -> dict | None:
        path = self.ref_path(spec)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    # -- eviction ----------------------------------------------------

    def _scan_snapshots(self) -> list[_SnapshotEntry]:
        entries: list[_SnapshotEntry] = []
        if not self.snapshots_root.is_dir():
            return entries
        for directory in self.snapshots_root.iterdir():
            if not directory.is_dir():
                continue
            manifest_paths = [directory / "manifest.json"]
            profiles = directory / "profiles"
            if profiles.is_dir():
                manifest_paths.extend(profiles.glob("*/manifest.json"))
            manifests: list[dict] = []
            for manifest_path in manifest_paths:
                if not manifest_path.is_file():
                    continue
                try:
                    manifests.append(
                        json.loads(manifest_path.read_text(encoding="utf-8"))
                    )
                except (json.JSONDecodeError, OSError):
                    continue
            if not manifests:
                continue
            manifest = max(
                manifests, key=lambda item: float(item.get("indexed_at", 0.0))
            )
            entries.append(
                _SnapshotEntry(
                    snapshot_id=manifest.get("snapshot_id", directory.name),
                    directory=directory,
                    spec=manifest.get("spec", "?"),
                    indexed_at=float(manifest.get("indexed_at", 0.0)),
                )
            )
        return entries

    def evict(self) -> dict:
        """Prune cached snapshots past the configured limits.

        Drops snapshots older than ``max_cache_age_days`` and, per
        source spec, keeps only the newest ``max_snapshots_per_spec``.
        """
        removed: list[str] = []
        now = time.time()
        max_age = self.config.max_cache_age_days * 86400
        survivors: dict[str, list[_SnapshotEntry]] = {}

        for entry in self._scan_snapshots():
            if max_age > 0 and (now - entry.indexed_at) > max_age:
                shutil.rmtree(entry.directory, ignore_errors=True)
                removed.append(entry.snapshot_id)
                continue
            survivors.setdefault(entry.spec, []).append(entry)

        keep = max(self.config.max_snapshots_per_spec, 1)
        for entries in survivors.values():
            entries.sort(key=lambda e: e.indexed_at, reverse=True)
            for entry in entries[keep:]:
                shutil.rmtree(entry.directory, ignore_errors=True)
                removed.append(entry.snapshot_id)

        return {"removed": removed, "removed_count": len(removed)}
