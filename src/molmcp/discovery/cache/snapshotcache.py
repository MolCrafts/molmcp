"""SnapshotCache — on-disk layout for indexed snapshots.

    <cache_dir>/snapshots/<slug>/manifest.json
                                /graph.db
                                /raw/         (GitHub sources)
                                /evidence/<query_hash>.json
    <cache_dir>/refs/<spec-slug>.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import DiscoveryConfig


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

    def graph_db_path(self, snapshot_id: str) -> Path:
        return self.snapshot_dir(snapshot_id) / "graph.db"

    def manifest_path(self, snapshot_id: str) -> Path:
        return self.snapshot_dir(snapshot_id) / "manifest.json"

    def raw_dir(self, snapshot_id: str) -> Path:
        return self.snapshot_dir(snapshot_id) / "raw"

    def evidence_dir(self, snapshot_id: str) -> Path:
        return self.snapshot_dir(snapshot_id) / "evidence"

    def ref_path(self, spec: str) -> Path:
        return self.refs_root / f"{slugify(spec)}.json"

    def ensure_dir(self, snapshot_id: str) -> Path:
        d = self.snapshot_dir(snapshot_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def has(self, snapshot_id: str) -> bool:
        """True when both a manifest and a graph.db are present."""
        return (
            self.manifest_path(snapshot_id).is_file()
            and self.graph_db_path(snapshot_id).is_file()
        )

    def write_manifest(self, snapshot_id: str, manifest: dict) -> None:
        self.ensure_dir(snapshot_id)
        self.manifest_path(snapshot_id).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def read_manifest(self, snapshot_id: str) -> dict | None:
        path = self.manifest_path(snapshot_id)
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
