"""Strict loading and canonical digesting for registry manifests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import (
    SCHEMA_VERSION,
    CatalogItemV1,
    RegistryValidationError,
)

MANIFEST_FILENAME = "molcrafts.registry.json"
_WIRE_FIELDS = {"schema_version", "items"}
_ZERO_DIGEST = "0" * 64


class ManifestError(RegistryValidationError):
    """A registry manifest could not be parsed or validated."""


class DuplicateJSONKeyError(ManifestError):
    """A JSON object declared the same key more than once."""


@dataclass(frozen=True, slots=True)
class LoadedManifest:
    """A fully validated manifest plus loader-owned trust metadata."""

    schema_version: str
    digest: str
    items: tuple[CatalogItemV1, ...]
    source: str

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ManifestError(f"manifest schema_version must be {SCHEMA_VERSION!r}")
        if (
            not isinstance(self.digest, str)
            or len(self.digest) != 64
            or any(character not in "0123456789abcdef" for character in self.digest)
        ):
            raise ManifestError(
                "manifest digest must be a lowercase SHA-256 hex digest"
            )
        if not isinstance(self.items, tuple) or not all(
            isinstance(item, CatalogItemV1) for item in self.items
        ):
            raise ManifestError("manifest items must be validated catalog items")
        if not isinstance(self.source, str) or not self.source:
            raise ManifestError("manifest source must be a non-empty string")
        for item in self.items:
            if item.provenance.manifest_digest != self.digest:
                raise ManifestError(
                    f"item {item.id} provenance digest does not match its manifest"
                )
        expected = canonical_sha256(
            {
                "schema_version": self.schema_version,
                "items": [item.to_wire_dict() for item in self.items],
            }
        )
        if self.digest != expected:
            raise ManifestError("manifest digest does not match canonical content")

    def to_wire_dict(self) -> dict[str, object]:
        """Return the self-digest-free JSON representation used for hashing."""

        return {
            "schema_version": self.schema_version,
            "items": [item.to_wire_dict() for item in self.items],
        }

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready loaded representation including trusted metadata."""

        return {
            "schema_version": self.schema_version,
            "digest": self.digest,
            "source": self.source,
            "items": [item.to_dict() for item in self.items],
        }


# A concise name for callers that do not need to distinguish wire/loaded forms.
ManifestV1 = LoadedManifest


def canonical_json_bytes(value: object) -> bytes:
    """Encode JSON deterministically for content addressing.

    Object keys are sorted, insignificant whitespace is removed, Unicode is
    encoded directly as UTF-8, and non-finite floats are rejected.
    """

    try:
        encoded = json.dumps(
            _json_ready(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ManifestError("manifest payload is not canonical JSON data") from exc
    return encoded.encode("utf-8")


def canonical_sha256(value: object) -> str:
    """Return the lowercase SHA-256 digest of canonical JSON data."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def load_manifest(path: str | Path) -> LoadedManifest:
    """Load and strictly validate a registry manifest from a UTF-8 JSON file."""

    manifest_path = Path(path)
    try:
        raw = manifest_path.read_bytes()
    except OSError as exc:
        raise ManifestError(f"cannot read registry manifest: {manifest_path}") from exc
    return loads_manifest(raw, source=str(manifest_path.resolve()))


def loads_manifest(
    raw: str | bytes | bytearray, *, source: str = "<memory>"
) -> LoadedManifest:
    """Load a manifest from JSON text or UTF-8 bytes."""

    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ManifestError("registry manifest must be UTF-8") from exc
    if not isinstance(raw, str):
        raise ManifestError("registry manifest must be JSON text or UTF-8 bytes")
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except ManifestError:
        raise
    except json.JSONDecodeError as exc:
        raise ManifestError(
            f"invalid registry manifest JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc
    return load_manifest_data(payload, source=source)


def load_manifest_data(
    payload: Mapping[str, Any], *, source: str = "<memory>"
) -> LoadedManifest:
    """Validate an already decoded wire manifest and attach its digest.

    Wire provenance intentionally has no ``manifest_digest`` field.  Parsing
    first uses a sentinel digest only to validate and normalize every item.
    The canonical digest is then computed over the normalized, digest-free
    payload and injected into the final immutable item models.
    """

    if not isinstance(payload, Mapping):
        raise ManifestError("registry manifest must be a JSON object")
    if not all(isinstance(key, str) for key in payload):
        raise ManifestError("registry manifest keys must be strings")
    unknown = set(payload) - _WIRE_FIELDS
    missing = _WIRE_FIELDS - set(payload)
    if unknown:
        raise ManifestError(
            "registry manifest contains unknown field(s): " + ", ".join(sorted(unknown))
        )
    if missing:
        raise ManifestError(
            "registry manifest is missing required field(s): "
            + ", ".join(sorted(missing))
        )
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ManifestError(
            f"manifest schema_version must be {SCHEMA_VERSION!r}, "
            f"got {payload['schema_version']!r}"
        )
    items_data = payload["items"]
    if isinstance(items_data, (str, bytes, bytearray)) or not isinstance(
        items_data, Sequence
    ):
        raise ManifestError("manifest items must be an array")

    try:
        provisional = tuple(
            CatalogItemV1.from_wire_dict(item, manifest_digest=_ZERO_DIGEST)
            for item in items_data
        )
    except RegistryValidationError as exc:
        raise ManifestError(str(exc)) from exc
    _reject_duplicate_ids(provisional)

    normalized_payload = {
        "schema_version": SCHEMA_VERSION,
        "items": [
            item.to_wire_dict()
            for item in sorted(provisional, key=lambda item: item.id)
        ],
    }
    digest = canonical_sha256(normalized_payload)
    try:
        items = tuple(
            CatalogItemV1.from_wire_dict(item, manifest_digest=digest)
            for item in normalized_payload["items"]
        )
    except RegistryValidationError as exc:  # defensive: provisional already passed
        raise ManifestError(str(exc)) from exc
    return LoadedManifest(
        schema_version=SCHEMA_VERSION,
        digest=digest,
        items=items,
        source=source,
    )


def dumps_manifest(manifest: LoadedManifest, *, indent: int | None = 2) -> str:
    """Serialize a loaded manifest back to its strict, digest-free wire form."""

    if not isinstance(manifest, LoadedManifest):
        raise TypeError("manifest must be a LoadedManifest")
    return json.dumps(
        manifest.to_wire_dict(),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=indent,
        separators=(",", ":") if indent is None else None,
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJSONKeyError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ManifestError(f"non-finite JSON number is forbidden: {value}")


def _json_ready(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


def _reject_duplicate_ids(items: Sequence[CatalogItemV1]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in items:
        if item.id in seen:
            duplicates.add(item.id)
        seen.add(item.id)
    if duplicates:
        raise ManifestError(
            "manifest contains duplicate registry id(s): "
            + ", ".join(sorted(duplicates))
        )


__all__ = [
    "MANIFEST_FILENAME",
    "DuplicateJSONKeyError",
    "LoadedManifest",
    "ManifestError",
    "ManifestV1",
    "canonical_json_bytes",
    "canonical_sha256",
    "dumps_manifest",
    "load_manifest",
    "load_manifest_data",
    "loads_manifest",
]
