"""Strict, MCP-independent registry data contracts.

The classes in this module model *validated registry declarations*.  They do
not know anything about the discovery graph: a code search result can never be
coerced into an executable capability through this API.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, TypeAlias
from urllib.parse import unquote, urlparse

from jsonschema.exceptions import SchemaError
from jsonschema.validators import Draft202012Validator
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

JSONScalar: TypeAlias = None | bool | int | float | str
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
FrozenJSON: TypeAlias = (
    JSONScalar | tuple["FrozenJSON", ...] | Mapping[str, "FrozenJSON"]
)

SCHEMA_VERSION = "1"

_REGISTRY_ID_RE = re.compile(
    r"^@(?P<namespace>[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?)/"
    r"(?P<name>[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?)$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_JSON_SCHEMA_TYPES = {
    "array",
    "boolean",
    "integer",
    "null",
    "number",
    "object",
    "string",
}
_CATALOG_KINDS = {"concept", "recipe", "convention", "validator"}
_PYTHON_TARGET_RE = re.compile(
    r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$"
)
_MCP_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHELL_EXECUTABLES = frozenset(
    {"sh", "bash", "zsh", "fish", "cmd", "cmd.exe", "powershell", "pwsh"}
)


class RegistryValidationError(ValueError):
    """A registry contract failed strict validation."""


class CatalogKind(StrEnum):
    """Supported registry item kinds."""

    CONCEPT = "concept"
    RECIPE = "recipe"
    CONVENTION = "convention"
    VALIDATOR = "validator"
    EXECUTABLE = "executable"


class InvocationKind(StrEnum):
    """Supported, structured invocation transports."""

    PYTHON = "python"
    CLI = "cli"
    MCP = "mcp"


def validate_registry_id(value: object, *, field_name: str = "id") -> str:
    """Validate and return a stable ``@namespace/name`` registry identifier."""

    value = _require_string(value, field_name)
    if _REGISTRY_ID_RE.fullmatch(value) is None:
        raise RegistryValidationError(
            f"{field_name} must match '@namespace/name' using lowercase ASCII "
            "letters, digits, '.', '_' or '-'"
        )
    return value


def split_registry_id(value: object) -> tuple[str, str]:
    """Return the namespace and name components of a validated registry id."""

    identifier = validate_registry_id(value)
    match = _REGISTRY_ID_RE.fullmatch(identifier)
    assert match is not None  # guaranteed by validate_registry_id
    return match.group("namespace"), match.group("name")


def _require_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegistryValidationError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise RegistryValidationError(f"{field_name} must not contain outer whitespace")
    return value


def _require_exact_fields(
    data: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
    model: str,
) -> None:
    optional = optional or set()
    unknown = set(data) - required - optional
    missing = required - set(data)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise RegistryValidationError(f"{model} contains unknown field(s): {names}")
    if missing:
        names = ", ".join(sorted(missing))
        raise RegistryValidationError(f"{model} is missing required field(s): {names}")


def _require_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RegistryValidationError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise RegistryValidationError(f"{field_name} keys must be strings")
    return value


def _require_sequence(value: object, field_name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise RegistryValidationError(f"{field_name} must be an array")
    return value


def _string_tuple(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = True,
    unique: bool = True,
) -> tuple[str, ...]:
    values = tuple(
        _require_string(item, f"{field_name}[{index}]")
        for index, item in enumerate(_require_sequence(value, field_name))
    )
    if not allow_empty and not values:
        raise RegistryValidationError(f"{field_name} must not be empty")
    if unique and len(set(values)) != len(values):
        raise RegistryValidationError(f"{field_name} must not contain duplicates")
    return values


def _freeze_json(value: object, field_name: str = "value") -> FrozenJSON:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise RegistryValidationError(
                f"{field_name} must contain finite JSON numbers"
            )
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, FrozenJSON] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RegistryValidationError(f"{field_name} keys must be strings")
            frozen[key] = _freeze_json(item, f"{field_name}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(
            _freeze_json(item, f"{field_name}[{index}]")
            for index, item in enumerate(value)
        )
    raise RegistryValidationError(f"{field_name} contains a non-JSON value")


def _thaw_json(value: FrozenJSON) -> JSONValue:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _validate_json_schema(schema: object, field_name: str) -> Mapping[str, FrozenJSON]:
    """Validate common JSON Schema keyword shapes without an external runtime.

    JSON Schema intentionally permits extension keywords, so rejecting every
    unknown keyword would make the scientific ``x-molcrafts-*`` annotations
    impossible.  This checks that the contract is an object and validates the
    structural shape of standard keywords and MolCrafts annotations.
    """

    mapping = _require_mapping(schema, field_name)
    references: list[tuple[str, str]] = []
    _validate_schema_node(mapping, field_name, references)
    _validate_local_references(mapping, references)
    try:
        Draft202012Validator.check_schema(dict(mapping))
    except SchemaError as exc:
        raise RegistryValidationError(
            f"{field_name} is not a valid JSON Schema 2020-12 document: {exc.message}"
        ) from exc
    frozen = _freeze_json(mapping, field_name)
    assert isinstance(frozen, Mapping)
    return frozen


def _validate_schema_node(
    schema: Mapping[str, Any],
    path: str,
    references: list[tuple[str, str]],
) -> None:
    schema_type = schema.get("type")
    if schema_type is not None:
        if isinstance(schema_type, str):
            schema_types = [schema_type]
        else:
            schema_types = list(_require_sequence(schema_type, f"{path}.type"))
            if not schema_types:
                raise RegistryValidationError(f"{path}.type must not be empty")
        if any(item not in _JSON_SCHEMA_TYPES for item in schema_types):
            raise RegistryValidationError(
                f"{path}.type contains an invalid JSON Schema type"
            )
        if len(set(schema_types)) != len(schema_types):
            raise RegistryValidationError(f"{path}.type must not contain duplicates")

    properties = schema.get("properties")
    if properties is not None:
        for name, child in _require_mapping(properties, f"{path}.properties").items():
            _validate_schema_value(child, f"{path}.properties.{name}", references)

    pattern_properties = schema.get("patternProperties")
    if pattern_properties is not None:
        for pattern, child in _require_mapping(
            pattern_properties, f"{path}.patternProperties"
        ).items():
            try:
                re.compile(pattern)
            except re.error as exc:
                raise RegistryValidationError(
                    f"{path}.patternProperties contains invalid regex {pattern!r}"
                ) from exc
            _validate_schema_value(
                child, f"{path}.patternProperties.{pattern}", references
            )

    required = schema.get("required")
    if required is not None:
        _string_tuple(required, f"{path}.required")

    for keyword in ("allOf", "anyOf", "oneOf", "prefixItems"):
        value = schema.get(keyword)
        if value is not None:
            children = _require_sequence(value, f"{path}.{keyword}")
            if keyword != "prefixItems" and not children:
                raise RegistryValidationError(f"{path}.{keyword} must not be empty")
            for index, child in enumerate(children):
                _validate_schema_value(child, f"{path}.{keyword}[{index}]", references)

    for keyword in (
        "items",
        "additionalProperties",
        "unevaluatedProperties",
        "unevaluatedItems",
        "contains",
        "not",
        "if",
        "then",
        "else",
        "propertyNames",
        "contentSchema",
    ):
        value = schema.get(keyword)
        if value is not None:
            _validate_schema_value(value, f"{path}.{keyword}", references)

    definitions = schema.get("$defs")
    if definitions is not None:
        for name, child in _require_mapping(definitions, f"{path}.$defs").items():
            _validate_schema_value(child, f"{path}.$defs.{name}", references)

    for keyword in ("definitions", "dependentSchemas"):
        definitions = schema.get(keyword)
        if definitions is not None:
            for name, child in _require_mapping(
                definitions, f"{path}.{keyword}"
            ).items():
                _validate_schema_value(child, f"{path}.{keyword}.{name}", references)

    for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
        reference = schema.get(keyword)
        if reference is None:
            continue
        reference = _require_string(reference, f"{path}.{keyword}")
        if not reference.startswith("#"):
            raise RegistryValidationError(
                f"{path}.{keyword} must be a local manifest reference"
            )
        references.append((f"{path}.{keyword}", reference))

    enum = schema.get("enum")
    if enum is not None and not _require_sequence(enum, f"{path}.enum"):
        raise RegistryValidationError(f"{path}.enum must not be empty")

    for keyword in ("minLength", "maxLength", "minItems", "maxItems"):
        value = schema.get(keyword)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise RegistryValidationError(
                f"{path}.{keyword} must be a non-negative integer"
            )

    index_base = schema.get("x-molcrafts-index-base")
    if index_base is not None and (
        type(index_base) is not int or index_base not in (0, 1)
    ):
        raise RegistryValidationError(f"{path}.x-molcrafts-index-base must be 0 or 1")
    for annotation in (
        "x-molcrafts-unit",
        "x-molcrafts-dimension",
        "x-molcrafts-coordinate-frame",
        "x-molcrafts-artifact-kind",
    ):
        value = schema.get(annotation)
        if value is not None:
            _require_string(value, f"{path}.{annotation}")

    # Validate the complete tree as JSON, including extension keywords.
    _freeze_json(schema, path)


def _validate_schema_value(
    value: object, path: str, references: list[tuple[str, str]]
) -> None:
    if isinstance(value, bool):
        return
    mapping = _require_mapping(value, path)
    _validate_schema_node(mapping, path, references)


def _validate_local_references(
    root: Mapping[str, Any], references: Sequence[tuple[str, str]]
) -> None:
    for path, reference in references:
        if reference == "#":
            continue
        if not reference.startswith("#/"):
            raise RegistryValidationError(
                f"{path} must use a local JSON Pointer reference"
            )
        current: object = root
        for raw_token in reference[2:].split("/"):
            decoded = unquote(raw_token)
            if re.search(r"~(?![01])", decoded):
                raise RegistryValidationError(
                    f"{path} contains an invalid JSON Pointer escape"
                )
            token = decoded.replace("~1", "/").replace("~0", "~")
            if isinstance(current, Mapping) and token in current:
                current = current[token]
                continue
            if (
                isinstance(current, Sequence)
                and not isinstance(current, (str, bytes, bytearray))
                and token.isdigit()
                and int(token) < len(current)
            ):
                current = current[int(token)]
                continue
            raise RegistryValidationError(
                f"{path} points to missing local schema target {reference!r}"
            )
        if not isinstance(current, (Mapping, bool)):
            raise RegistryValidationError(
                f"{path} target {reference!r} is not a JSON Schema object or boolean"
            )


def _is_floating_version(version: str) -> bool:
    try:
        Version(version)
    except InvalidVersion:
        return True
    return False


@dataclass(frozen=True, slots=True)
class Provenance:
    """Trusted origin metadata attached by the manifest loader."""

    source_uri: str
    revision: str
    manifest_digest: str
    declarer: str

    def __post_init__(self) -> None:
        source_uri = _require_string(self.source_uri, "provenance.source_uri")
        parsed = urlparse(source_uri)
        if not parsed.scheme:
            raise RegistryValidationError(
                "provenance.source_uri must be an absolute URI"
            )
        object.__setattr__(self, "source_uri", source_uri)
        object.__setattr__(
            self, "revision", _require_string(self.revision, "provenance.revision")
        )
        digest = _require_string(self.manifest_digest, "provenance.manifest_digest")
        if _SHA256_RE.fullmatch(digest) is None:
            raise RegistryValidationError(
                "provenance.manifest_digest must be a lowercase SHA-256 hex digest"
            )
        object.__setattr__(self, "manifest_digest", digest)
        object.__setattr__(
            self, "declarer", _require_string(self.declarer, "provenance.declarer")
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Provenance:
        data = _require_mapping(data, "provenance")
        required = {"source_uri", "revision", "manifest_digest", "declarer"}
        _require_exact_fields(data, required=required, model="provenance")
        return cls(**{name: data[name] for name in required})

    @classmethod
    def from_wire_dict(
        cls, data: Mapping[str, Any], *, manifest_digest: str
    ) -> Provenance:
        """Build provenance from manifest wire data and a loader-owned digest.

        ``manifest_digest`` is deliberately forbidden on the wire.  A manifest
        cannot self-report the digest that decides whether it is trusted.
        """

        data = _require_mapping(data, "provenance")
        required = {"source_uri", "revision", "declarer"}
        _require_exact_fields(data, required=required, model="manifest provenance")
        return cls(
            source_uri=data["source_uri"],
            revision=data["revision"],
            declarer=data["declarer"],
            manifest_digest=manifest_digest,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "source_uri": self.source_uri,
            "revision": self.revision,
            "manifest_digest": self.manifest_digest,
            "declarer": self.declarer,
        }

    def to_wire_dict(self) -> dict[str, str]:
        return {
            "source_uri": self.source_uri,
            "revision": self.revision,
            "declarer": self.declarer,
        }


@dataclass(frozen=True, slots=True)
class Invocation:
    """A structured invocation declaration; raw shell strings are impossible."""

    kind: InvocationKind | str
    target: str | tuple[str, ...] | list[str]

    def __post_init__(self) -> None:
        try:
            kind = InvocationKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise RegistryValidationError(
                "invocation.kind must be one of: python, cli, mcp"
            ) from exc
        object.__setattr__(self, "kind", kind)

        if kind is InvocationKind.CLI:
            target = _string_tuple(
                self.target, "invocation.target", allow_empty=False, unique=False
            )
            executable = target[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
            if executable in _SHELL_EXECUTABLES:
                raise RegistryValidationError(
                    "invocation.target must not invoke a command shell"
                )
            if any("\x00" in argument or "\n" in argument for argument in target):
                raise RegistryValidationError(
                    "invocation.target argv must not contain NUL or newlines"
                )
        else:
            target = _require_string(self.target, "invocation.target")
            if (
                kind is InvocationKind.PYTHON
                and _PYTHON_TARGET_RE.fullmatch(target) is None
            ):
                raise RegistryValidationError(
                    "python invocation.target must be 'module:qualname'"
                )
            if kind is InvocationKind.MCP and _MCP_TARGET_RE.fullmatch(target) is None:
                raise RegistryValidationError(
                    "mcp invocation.target must be a valid MCP tool name"
                )
        object.__setattr__(self, "target", target)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Invocation:
        data = _require_mapping(data, "invocation")
        required = {"kind", "target"}
        _require_exact_fields(data, required=required, model="invocation")
        return cls(kind=data["kind"], target=data["target"])

    def to_dict(self) -> dict[str, object]:
        target: str | list[str]
        if isinstance(self.target, tuple):
            target = list(self.target)
        else:
            target = self.target
        return {"kind": str(self.kind), "target": target}


@dataclass(frozen=True, slots=True)
class Requirements:
    """Runtime requirements for an executable capability."""

    packages: tuple[str, ...] | list[str]
    executables: tuple[str, ...] | list[str]
    platforms: tuple[str, ...] | list[str]

    def __post_init__(self) -> None:
        packages = _string_tuple(self.packages, "requirements.packages")
        normalized_packages: set[str] = set()
        for index, package in enumerate(packages):
            try:
                requirement = Requirement(package)
            except InvalidRequirement as exc:
                raise RegistryValidationError(
                    f"requirements.packages[{index}] is not a valid package requirement"
                ) from exc
            if requirement.url is not None:
                raise RegistryValidationError(
                    f"requirements.packages[{index}] must not use a direct URL"
                )
            normalized = canonicalize_name(requirement.name)
            if normalized in normalized_packages:
                raise RegistryValidationError(
                    "requirements.packages must not repeat a normalized package name"
                )
            normalized_packages.add(normalized)
        object.__setattr__(self, "packages", packages)
        object.__setattr__(
            self,
            "executables",
            _string_tuple(self.executables, "requirements.executables"),
        )
        object.__setattr__(
            self, "platforms", _string_tuple(self.platforms, "requirements.platforms")
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Requirements:
        data = _require_mapping(data, "requirements")
        required = {"packages", "executables", "platforms"}
        _require_exact_fields(data, required=required, model="requirements")
        return cls(**{name: data[name] for name in required})

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "packages": list(self.packages),
            "executables": list(self.executables),
            "platforms": list(self.platforms),
        }


_CATALOG_FIELDS = {
    "schema_version",
    "id",
    "kind",
    "title",
    "summary",
    "package",
    "package_version",
    "tags",
    "aliases",
    "examples",
    "provenance",
}
_EXECUTABLE_FIELDS = _CATALOG_FIELDS | {
    "invocation",
    "input_schema",
    "output_schema",
    "side_effects",
    "supported_backends",
    "requirements",
    "validators",
    "timeout_seconds",
    "resource_class",
}


@dataclass(frozen=True, slots=True)
class CatalogItemV1:
    """A non-executable registry catalog declaration."""

    schema_version: str
    id: str
    kind: CatalogKind | str
    title: str
    summary: str
    package: str
    package_version: str
    tags: tuple[str, ...] | list[str]
    aliases: tuple[str, ...] | list[str]
    examples: tuple[FrozenJSON, ...] | list[JSONValue]
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise RegistryValidationError(
                "schema_version must be "
                f"{SCHEMA_VERSION!r}, got {self.schema_version!r}"
            )
        object.__setattr__(self, "id", validate_registry_id(self.id))
        try:
            kind = CatalogKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise RegistryValidationError(
                f"unsupported catalog kind: {self.kind!r}"
            ) from exc
        if str(kind) not in _CATALOG_KINDS:
            raise RegistryValidationError(
                "CatalogItemV1 kind must be concept, recipe, convention, or validator; "
                "use ExecutableCapabilityV1 for executable declarations"
            )
        object.__setattr__(self, "kind", kind)
        for field_name in ("title", "summary", "package", "package_version"):
            object.__setattr__(
                self, field_name, _require_string(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "tags", _string_tuple(self.tags, "tags"))
        object.__setattr__(self, "aliases", _string_tuple(self.aliases, "aliases"))
        examples = tuple(
            _freeze_json(example, f"examples[{index}]")
            for index, example in enumerate(
                _require_sequence(self.examples, "examples")
            )
        )
        object.__setattr__(self, "examples", examples)
        if not isinstance(self.provenance, Provenance):
            raise RegistryValidationError("provenance must be a Provenance object")

    @property
    def namespace(self) -> str:
        return split_registry_id(self.id)[0]

    @property
    def name(self) -> str:
        return split_registry_id(self.id)[1]

    @property
    def executable(self) -> bool:
        return False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CatalogItemV1:
        """Strictly parse loaded data, dispatching executable declarations."""

        data = _require_mapping(data, "catalog item")
        if cls is CatalogItemV1 and data.get("kind") == CatalogKind.EXECUTABLE:
            return ExecutableCapabilityV1.from_dict(data)
        _require_exact_fields(data, required=_CATALOG_FIELDS, model="catalog item")
        return cls(**_catalog_kwargs(data, Provenance.from_dict(data["provenance"])))

    @classmethod
    def from_wire_dict(
        cls, data: Mapping[str, Any], *, manifest_digest: str
    ) -> CatalogItemV1:
        data = _require_mapping(data, "catalog item")
        if cls is CatalogItemV1 and data.get("kind") == CatalogKind.EXECUTABLE:
            return ExecutableCapabilityV1.from_wire_dict(
                data, manifest_digest=manifest_digest
            )
        _require_exact_fields(data, required=_CATALOG_FIELDS, model="catalog item")
        provenance = Provenance.from_wire_dict(
            data["provenance"], manifest_digest=manifest_digest
        )
        return cls(**_catalog_kwargs(data, provenance))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            **self._base_dict(),
            "provenance": self.provenance.to_dict(),
        }

    def to_wire_dict(self) -> dict[str, JSONValue]:
        return {
            **self._base_dict(),
            "provenance": self.provenance.to_wire_dict(),
        }

    def _base_dict(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "kind": str(self.kind),
            "title": self.title,
            "summary": self.summary,
            "package": self.package,
            "package_version": self.package_version,
            "tags": list(self.tags),
            "aliases": list(self.aliases),
            "examples": [_thaw_json(example) for example in self.examples],
        }


@dataclass(frozen=True, slots=True)
class ExecutableCapabilityV1(CatalogItemV1):
    """An explicitly declared, pinned, executable registry capability."""

    invocation: Invocation
    input_schema: Mapping[str, FrozenJSON] | dict[str, JSONValue]
    output_schema: Mapping[str, FrozenJSON] | dict[str, JSONValue]
    side_effects: tuple[str, ...] | list[str]
    supported_backends: tuple[str, ...] | list[str]
    requirements: Requirements
    validators: tuple[str, ...] | list[str]
    timeout_seconds: int
    resource_class: str

    def __post_init__(self) -> None:
        # Validate shared fields here because CatalogItemV1 intentionally
        # rejects kind="executable" when constructed directly.
        if self.schema_version != SCHEMA_VERSION:
            raise RegistryValidationError(
                "schema_version must be "
                f"{SCHEMA_VERSION!r}, got {self.schema_version!r}"
            )
        object.__setattr__(self, "id", validate_registry_id(self.id))
        try:
            kind = CatalogKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise RegistryValidationError(
                "executable kind must be 'executable'"
            ) from exc
        if kind is not CatalogKind.EXECUTABLE:
            raise RegistryValidationError(
                "ExecutableCapabilityV1 kind must be 'executable'"
            )
        object.__setattr__(self, "kind", kind)
        for field_name in ("title", "summary", "package", "package_version"):
            object.__setattr__(
                self, field_name, _require_string(getattr(self, field_name), field_name)
            )
        if _is_floating_version(self.package_version):
            raise RegistryValidationError(
                "executable package_version must be an exact, pinned version"
            )
        object.__setattr__(self, "tags", _string_tuple(self.tags, "tags"))
        object.__setattr__(self, "aliases", _string_tuple(self.aliases, "aliases"))
        object.__setattr__(
            self,
            "examples",
            tuple(
                _freeze_json(example, f"examples[{index}]")
                for index, example in enumerate(
                    _require_sequence(self.examples, "examples")
                )
            ),
        )
        if not isinstance(self.provenance, Provenance):
            raise RegistryValidationError("provenance must be a Provenance object")
        if not isinstance(self.invocation, Invocation):
            raise RegistryValidationError("invocation must be an Invocation object")
        object.__setattr__(
            self,
            "input_schema",
            _validate_json_schema(self.input_schema, "input_schema"),
        )
        object.__setattr__(
            self,
            "output_schema",
            _validate_json_schema(self.output_schema, "output_schema"),
        )
        object.__setattr__(
            self, "side_effects", _string_tuple(self.side_effects, "side_effects")
        )
        object.__setattr__(
            self,
            "supported_backends",
            _string_tuple(
                self.supported_backends, "supported_backends", allow_empty=False
            ),
        )
        if not isinstance(self.requirements, Requirements):
            raise RegistryValidationError("requirements must be a Requirements object")
        validators = _string_tuple(self.validators, "validators")
        for index, validator in enumerate(validators):
            validate_registry_id(validator, field_name=f"validators[{index}]")
        object.__setattr__(self, "validators", validators)
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int)
            or self.timeout_seconds <= 0
        ):
            raise RegistryValidationError("timeout_seconds must be a positive integer")
        object.__setattr__(
            self,
            "resource_class",
            _require_string(self.resource_class, "resource_class"),
        )

    @property
    def executable(self) -> bool:
        return True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ExecutableCapabilityV1:
        data = _require_mapping(data, "executable capability")
        _require_exact_fields(
            data, required=_EXECUTABLE_FIELDS, model="executable capability"
        )
        return cls(**_executable_kwargs(data, Provenance.from_dict(data["provenance"])))

    @classmethod
    def from_wire_dict(
        cls, data: Mapping[str, Any], *, manifest_digest: str
    ) -> ExecutableCapabilityV1:
        data = _require_mapping(data, "executable capability")
        _require_exact_fields(
            data, required=_EXECUTABLE_FIELDS, model="executable capability"
        )
        provenance = Provenance.from_wire_dict(
            data["provenance"], manifest_digest=manifest_digest
        )
        return cls(**_executable_kwargs(data, provenance))

    def to_dict(self) -> dict[str, JSONValue]:
        return self._executable_dict(include_digest=True)

    def to_wire_dict(self) -> dict[str, JSONValue]:
        return self._executable_dict(include_digest=False)

    def _executable_dict(self, *, include_digest: bool) -> dict[str, JSONValue]:
        result = self._base_dict()
        result.update(
            {
                "provenance": (
                    self.provenance.to_dict()
                    if include_digest
                    else self.provenance.to_wire_dict()
                ),
                "invocation": self.invocation.to_dict(),
                "input_schema": _thaw_json(self.input_schema),
                "output_schema": _thaw_json(self.output_schema),
                "side_effects": list(self.side_effects),
                "supported_backends": list(self.supported_backends),
                "requirements": self.requirements.to_dict(),
                "validators": list(self.validators),
                "timeout_seconds": self.timeout_seconds,
                "resource_class": self.resource_class,
            }
        )
        return result


def _catalog_kwargs(data: Mapping[str, Any], provenance: Provenance) -> dict[str, Any]:
    return {
        "schema_version": data["schema_version"],
        "id": data["id"],
        "kind": data["kind"],
        "title": data["title"],
        "summary": data["summary"],
        "package": data["package"],
        "package_version": data["package_version"],
        "tags": data["tags"],
        "aliases": data["aliases"],
        "examples": data["examples"],
        "provenance": provenance,
    }


def _executable_kwargs(
    data: Mapping[str, Any], provenance: Provenance
) -> dict[str, Any]:
    return {
        **_catalog_kwargs(data, provenance),
        "invocation": Invocation.from_dict(data["invocation"]),
        "input_schema": data["input_schema"],
        "output_schema": data["output_schema"],
        "side_effects": data["side_effects"],
        "supported_backends": data["supported_backends"],
        "requirements": Requirements.from_dict(data["requirements"]),
        "validators": data["validators"],
        "timeout_seconds": data["timeout_seconds"],
        "resource_class": data["resource_class"],
    }


def parse_catalog_item(data: Mapping[str, Any]) -> CatalogItemV1:
    """Strictly parse an already loaded registry item."""

    return CatalogItemV1.from_dict(data)


__all__ = [
    "CatalogItemV1",
    "CatalogKind",
    "ExecutableCapabilityV1",
    "Invocation",
    "InvocationKind",
    "Provenance",
    "RegistryValidationError",
    "Requirements",
    "SCHEMA_VERSION",
    "parse_catalog_item",
    "split_registry_id",
    "validate_registry_id",
]
