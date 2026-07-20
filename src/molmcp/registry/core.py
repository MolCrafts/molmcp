"""Deterministic, fail-closed in-memory registry."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable

from packaging.utils import canonicalize_name
from packaging.version import Version

from .manifest import LoadedManifest
from .models import (
    CatalogItemV1,
    CatalogKind,
    ExecutableCapabilityV1,
    RegistryValidationError,
    validate_registry_id,
)


class RegistryError(RuntimeError):
    """Base class for registry state errors."""


class RegistryConflictError(RegistryError):
    """A registration would make resolution ambiguous."""


class RegistryItemNotFoundError(RegistryError, KeyError):
    """A requested stable registry reference is not registered."""


class Registry:
    """A deterministic collection of validated registry items.

    Registration is fail-closed and batch-atomic: a duplicate ID rejects the
    entire batch, including byte-identical declarations.  There is no merge or
    last-write-wins behavior.
    """

    def __init__(self, items: Iterable[CatalogItemV1] = ()) -> None:
        self._items: dict[str, CatalogItemV1] = {}
        self._manifests: list[tuple[LoadedManifest, str]] = []
        self._execution_status: dict[str, str] = {}
        self._origins: dict[str, dict[str, str]] = {}
        self._commit(items, allow_executable=False)

    def register(self, item: CatalogItemV1) -> CatalogItemV1:
        """Register one validated item or raise on conflict."""

        self.register_many((item,))
        return item

    def register_many(self, items: Iterable[CatalogItemV1]) -> list[CatalogItemV1]:
        """Register non-executable catalog items atomically.

        Executable capabilities must cross the loader-owned manifest digest
        boundary through :meth:`register_manifest`.
        """

        return self._commit(items, allow_executable=False)

    def _commit(
        self,
        items: Iterable[CatalogItemV1],
        *,
        allow_executable: bool,
        execution_statuses: dict[str, str] | None = None,
    ) -> list[CatalogItemV1]:
        execution_statuses = execution_statuses or {}
        registered = self._register_many(items, allow_executable=allow_executable)
        try:
            self._validate_consistency({**self._execution_status, **execution_statuses})
        except Exception:
            for item in registered:
                self._items.pop(item.id, None)
            raise
        self._execution_status.update(execution_statuses)
        return registered

    def _register_many(
        self, items: Iterable[CatalogItemV1], *, allow_executable: bool
    ) -> list[CatalogItemV1]:
        """Atomically register a validated batch."""

        batch = list(items)
        for index, item in enumerate(batch):
            if not isinstance(item, CatalogItemV1):
                raise RegistryValidationError(
                    f"items[{index}] must be a CatalogItemV1 or ExecutableCapabilityV1"
                )
            if isinstance(item, ExecutableCapabilityV1) and not allow_executable:
                raise RegistryValidationError(
                    f"executable item {item.id} must be registered from a "
                    "LoadedManifest"
                )

        counts = Counter(item.id for item in batch)
        repeated = {identifier for identifier, count in counts.items() if count > 1}
        existing = set(self._items).intersection(counts)
        conflicts = repeated | existing
        if conflicts:
            raise RegistryConflictError(
                "duplicate registry id(s): " + ", ".join(sorted(conflicts))
            )

        # Update only after every validation and conflict check has passed.
        self._items.update({item.id: item for item in batch})
        return batch

    def register_manifest(
        self,
        manifest: LoadedManifest,
        *,
        namespace: str | None = None,
        execution_status: str = "ready",
    ) -> list[CatalogItemV1]:
        """Atomically register all items from a validated loaded manifest."""

        return self.register_manifests(((manifest, namespace, execution_status),))

    def register_manifests(
        self,
        manifests: Iterable[tuple[LoadedManifest, str | None, str]],
    ) -> list[CatalogItemV1]:
        """Atomically register manifests and resolve cross-manifest refs."""

        entries = list(manifests)
        items: list[CatalogItemV1] = []
        loaded: list[tuple[LoadedManifest, str]] = []
        statuses: dict[str, str] = {}
        for index, (manifest, namespace, execution_status) in enumerate(entries):
            if not isinstance(manifest, LoadedManifest):
                raise RegistryValidationError(
                    f"manifests[{index}] must contain a LoadedManifest"
                )
            if execution_status not in {"ready", "search_only"}:
                raise RegistryValidationError(
                    f"manifests[{index}] execution status must be ready or search_only"
                )
            if namespace is not None:
                normalized = namespace.removeprefix("@")
                validate_registry_id(f"@{normalized}/x", field_name="namespace")
                foreign = sorted(
                    item.id for item in manifest.items if item.namespace != normalized
                )
                if foreign:
                    raise RegistryConflictError(
                        f"manifest source restricted to @{normalized} contains foreign "
                        "registry id(s): " + ", ".join(foreign)
                    )
            items.extend(manifest.items)
            loaded.append((manifest, execution_status))
            statuses.update(
                {
                    item.id: execution_status
                    for item in manifest.items
                    if isinstance(item, ExecutableCapabilityV1)
                }
            )

        registered = self._commit(
            items,
            allow_executable=True,
            execution_statuses=statuses,
        )
        self._manifests.extend(loaded)
        for manifest, execution_status in loaded:
            for item in manifest.items:
                self._origins[item.id] = {
                    "source": manifest.source,
                    "manifest_digest": manifest.digest,
                    "execution_status": execution_status,
                }
        return registered

    def _validate_consistency(self, execution_statuses: dict[str, str]) -> None:
        """Validate references and package-version compatibility."""

        executable_versions: dict[str, set[str]] = {}
        for item in self._items.values():
            if not isinstance(item, ExecutableCapabilityV1):
                continue
            if execution_statuses.get(item.id) == "ready":
                executable_versions.setdefault(
                    canonicalize_name(item.package), set()
                ).add(str(Version(item.package_version)))
            for validator_ref in item.validators:
                target = self._items.get(validator_ref)
                if target is None:
                    raise RegistryConflictError(
                        f"executable {item.id} references missing validator "
                        f"{validator_ref}"
                    )
                if str(target.kind) != "validator":
                    raise RegistryConflictError(
                        f"executable {item.id} validator ref {validator_ref} "
                        "does not resolve to kind 'validator'"
                    )
        conflicts = {
            package: values
            for package, values in executable_versions.items()
            if len(values) > 1
        }
        if conflicts:
            details = ", ".join(
                f"{package}={sorted(values)}"
                for package, values in sorted(conflicts.items())
            )
            raise RegistryConflictError(
                "incompatible package versions in registry: " + details
            )

    def get(self, ref: str) -> CatalogItemV1:
        """Resolve one exact stable registry reference."""

        ref = validate_registry_id(ref, field_name="ref")
        try:
            return self._items[ref]
        except KeyError as exc:
            raise RegistryItemNotFoundError(f"registry item not found: {ref}") from exc

    def execution_status(self, ref: str) -> str:
        """Return ready, search_only, or not_executable for an exact ref."""

        item = self.get(ref)
        if not isinstance(item, ExecutableCapabilityV1):
            return "not_executable"
        return self._execution_status[ref]

    def is_executable(self, ref: str) -> bool:
        """Whether ``ref`` is trusted and ready for Molexp handoff."""

        return self.execution_status(ref) == "ready"

    def record_info(self, ref: str) -> dict[str, str] | None:
        """Return loader-observed origin and trust state for an exact ref."""

        self.get(ref)
        origin = self._origins.get(ref)
        return dict(origin) if origin is not None else None

    def search(
        self,
        query: str,
        kinds: Iterable[str] | str | None = None,
        namespaces: Iterable[str] | str | None = None,
        limit: int = 20,
    ) -> list[CatalogItemV1]:
        """Search registry metadata with deterministic lexical ranking."""

        if not isinstance(query, str):
            raise RegistryValidationError("query must be a string")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise RegistryValidationError("limit must be a positive integer")
        kind_filter = _normalize_kinds(kinds)
        namespace_filter = _normalize_namespaces(namespaces)

        candidates = [
            item
            for item in self._items.values()
            if (kind_filter is None or str(item.kind) in kind_filter)
            and (namespace_filter is None or item.namespace in namespace_filter)
        ]
        normalized_query = _normalize(query)
        if not normalized_query:
            return sorted(candidates, key=lambda item: item.id)[:limit]

        scored = [(_search_score(item, normalized_query), item) for item in candidates]
        return [
            item
            for score, item in sorted(scored, key=lambda pair: (-pair[0], pair[1].id))
            if score > 0
        ][:limit]

    def list_items(self) -> list[CatalogItemV1]:
        """Return all items in stable reference order."""

        return [self._items[identifier] for identifier in sorted(self._items)]

    def info(self) -> dict[str, object]:
        """Return compact, JSON-serializable registry coverage information."""

        items = self.list_items()
        kinds = Counter(str(item.kind) for item in items)
        namespaces = Counter(item.namespace for item in items)
        packages = Counter(item.package for item in items)
        versions: dict[str, set[str]] = {}
        backends: set[str] = set()
        for item in items:
            versions.setdefault(item.package, set()).add(item.package_version)
            if (
                isinstance(item, ExecutableCapabilityV1)
                and self._execution_status.get(item.id) == "ready"
            ):
                backends.update(item.supported_backends)
        return {
            "schema_version": "1",
            "item_count": len(items),
            "executable_count": sum(
                self._execution_status.get(item.id) == "ready" for item in items
            ),
            "declared_executable_count": sum(
                isinstance(item, ExecutableCapabilityV1) for item in items
            ),
            "search_only_executable_count": sum(
                self._execution_status.get(item.id) == "search_only" for item in items
            ),
            "namespaces": dict(sorted(namespaces.items())),
            "kinds": dict(sorted(kinds.items())),
            "packages": dict(sorted(packages.items())),
            "package_versions": {
                package: sorted(values) for package, values in sorted(versions.items())
            },
            "backends": sorted(backends),
            "manifests": [
                {
                    "source": manifest.source,
                    "digest": manifest.digest,
                    "item_count": len(manifest.items),
                    "execution_status": execution_status,
                }
                for manifest, execution_status in self._manifests
            ],
        }

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, ref: object) -> bool:
        return isinstance(ref, str) and ref in self._items


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _normalize_kinds(kinds: Iterable[str] | str | None) -> set[str] | None:
    if kinds is None:
        return None
    values = [kinds] if isinstance(kinds, str) else list(kinds)
    result: set[str] = set()
    for kind in values:
        try:
            result.add(str(CatalogKind(kind)))
        except (TypeError, ValueError) as exc:
            raise RegistryValidationError(f"unsupported kind filter: {kind!r}") from exc
    return result


def _normalize_namespaces(
    namespaces: Iterable[str] | str | None,
) -> set[str] | None:
    if namespaces is None:
        return None
    values = [namespaces] if isinstance(namespaces, str) else list(namespaces)
    result: set[str] = set()
    for namespace in values:
        if not isinstance(namespace, str):
            raise RegistryValidationError("namespace filters must be strings")
        normalized = namespace[1:] if namespace.startswith("@") else namespace
        # Reuse the public identifier grammar rather than maintaining a second
        # subtly different namespace pattern.
        validate_registry_id(f"@{normalized}/x", field_name="namespace")
        result.add(normalized)
    return result


def _search_score(item: CatalogItemV1, query: str) -> int:
    identifier = _normalize(item.id)
    namespace = _normalize(item.namespace)
    name = _normalize(item.name)
    title = _normalize(item.title)
    summary = _normalize(item.summary)
    package = _normalize(item.package)
    aliases = [_normalize(alias) for alias in item.aliases]
    tags = [_normalize(tag) for tag in item.tags]
    examples = _normalize(
        json.dumps(item.to_dict()["examples"], ensure_ascii=False, sort_keys=True)
    )

    score = 0
    if query == identifier:
        score += 10_000
    if query == name:
        score += 5_000
    if query == title:
        score += 4_000
    if query in aliases:
        score += 4_500
    if query in tags:
        score += 3_000
    if query == namespace or query == package:
        score += 2_000

    fields = (
        (identifier, 160),
        (name, 150),
        (title, 120),
        (" ".join(aliases), 110),
        (" ".join(tags), 90),
        (summary, 50),
        (package, 40),
        (examples, 10),
    )
    query_tokens = tuple(dict.fromkeys(_tokens(query)))
    for field, weight in fields:
        if query in field:
            score += weight * 3
        score += sum(weight for token in query_tokens if token in field)
    return score


def _tokens(value: str) -> list[str]:
    # ``\w`` is Unicode-aware in Python, retaining Chinese terms while also
    # splitting punctuation in registry IDs and natural-language queries.
    return re.findall(r"\w+", value, flags=re.UNICODE)


__all__ = [
    "Registry",
    "RegistryConflictError",
    "RegistryError",
    "RegistryItemNotFoundError",
]
