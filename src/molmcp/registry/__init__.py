"""Versioned, fail-closed MolCrafts capability registry."""

from .core import (
    Registry,
    RegistryConflictError,
    RegistryError,
    RegistryItemNotFoundError,
)
from .entrypoints import CAPABILITY_ENTRY_POINT_GROUP, load_installed_manifests
from .manifest import (
    MANIFEST_FILENAME,
    DuplicateJSONKeyError,
    LoadedManifest,
    ManifestError,
    canonical_sha256,
    dumps_manifest,
    load_manifest,
    load_manifest_data,
    loads_manifest,
)
from .models import (
    SCHEMA_VERSION,
    CatalogItemV1,
    CatalogKind,
    ExecutableCapabilityV1,
    Invocation,
    InvocationKind,
    Provenance,
    RegistryValidationError,
    Requirements,
    parse_catalog_item,
    split_registry_id,
    validate_registry_id,
)

__all__ = [
    "CAPABILITY_ENTRY_POINT_GROUP",
    "MANIFEST_FILENAME",
    "SCHEMA_VERSION",
    "CatalogItemV1",
    "CatalogKind",
    "DuplicateJSONKeyError",
    "ExecutableCapabilityV1",
    "Invocation",
    "InvocationKind",
    "LoadedManifest",
    "ManifestError",
    "Provenance",
    "Registry",
    "RegistryConflictError",
    "RegistryError",
    "RegistryItemNotFoundError",
    "RegistryValidationError",
    "Requirements",
    "canonical_sha256",
    "dumps_manifest",
    "load_installed_manifests",
    "load_manifest",
    "load_manifest_data",
    "loads_manifest",
    "parse_catalog_item",
    "split_registry_id",
    "validate_registry_id",
]
