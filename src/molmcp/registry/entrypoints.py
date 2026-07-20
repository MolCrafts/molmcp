"""Installed-package manifest discovery.

An entry point in ``molmcp.capabilities`` resolves to one of:

- a path-like object naming ``molcrafts.registry.json``;
- a :class:`LoadedManifest`;
- a zero-argument callable returning either form.

The loader never accepts dictionaries or code-discovery results.  This keeps
the executable trust boundary at a parsed, content-addressed manifest.
"""

from __future__ import annotations

import importlib.metadata
import os
from collections.abc import Callable

from .manifest import LoadedManifest, ManifestError, load_manifest
from .models import validate_registry_id

CAPABILITY_ENTRY_POINT_GROUP = "molmcp.capabilities"


def load_installed_manifests(
    namespace: str | None = None,
) -> list[LoadedManifest]:
    """Load installed manifests, optionally selecting one trusted namespace."""
    try:
        entry_points = importlib.metadata.entry_points(
            group=CAPABILITY_ENTRY_POINT_GROUP
        )
    except TypeError:  # pragma: no cover - old importlib.metadata fallback
        entry_points = importlib.metadata.entry_points().get(
            CAPABILITY_ENTRY_POINT_GROUP, []
        )

    selected = None
    if namespace is not None:
        selected = namespace.removeprefix("@")
        validate_registry_id(f"@{selected}/x", field_name="namespace")
    ordered = sorted(entry_points, key=lambda item: item.name)
    names = [entry_point.name for entry_point in ordered]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ManifestError(
            "duplicate capability entry-point name(s): " + ", ".join(duplicates)
        )

    manifests: list[LoadedManifest] = []
    for entry_point in ordered:
        try:
            validate_registry_id(f"@{entry_point.name}/x", field_name="entry point")
        except ValueError as exc:
            raise ManifestError(
                f"invalid capability entry-point namespace: {entry_point.name!r}"
            ) from exc
        if selected is not None and entry_point.name != selected:
            continue
        try:
            loaded = entry_point.load()
            value = loaded() if isinstance(loaded, Callable) else loaded
            if isinstance(value, LoadedManifest):
                manifest = value
            elif isinstance(value, (str, os.PathLike)):
                manifest = load_manifest(value)
            else:
                raise ManifestError(
                    "capability entry point must resolve to a manifest path, "
                    "LoadedManifest, or zero-argument callable returning one"
                )
        except Exception as exc:
            if isinstance(exc, ManifestError):
                raise
            raise ManifestError(
                f"failed to load capability entry point {entry_point.name!r}: {exc}"
            ) from exc
        foreign = sorted(
            item.id for item in manifest.items if item.namespace != entry_point.name
        )
        if foreign:
            raise ManifestError(
                f"capability entry point {entry_point.name!r} contains foreign "
                "registry id(s): " + ", ".join(foreign)
            )
        manifests.append(
            LoadedManifest(
                schema_version=manifest.schema_version,
                digest=manifest.digest,
                items=manifest.items,
                source=f"entrypoint:{entry_point.name}",
            )
        )
    if selected is not None and not manifests:
        raise ManifestError(f"installed capability namespace not found: @{selected}")
    return manifests
