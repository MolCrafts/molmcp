from __future__ import annotations

import json

import pytest

from molmcp.registry import (
    CatalogItemV1,
    DuplicateJSONKeyError,
    ExecutableCapabilityV1,
    LoadedManifest,
    ManifestError,
    Registry,
    RegistryConflictError,
    RegistryValidationError,
    dumps_manifest,
    load_manifest_data,
    loads_manifest,
)


def _provenance() -> dict:
    return {
        "source_uri": "https://github.com/MolCrafts/molpack",
        "revision": "0123456789abcdef",
        "declarer": "molpack",
    }


def _concept(identifier: str = "@molpy/analysis.rdf") -> dict:
    return {
        "schema_version": "1",
        "id": identifier,
        "kind": "concept",
        "title": "Radial distribution function",
        "summary": "计算径向分布函数 g(r)",
        "package": "molpy",
        "package_version": "0.8.0",
        "tags": ["analysis", "rdf"],
        "aliases": ["径向分布函数", "pair correlation"],
        "examples": [{"query": "oxygen oxygen rdf"}],
        "provenance": _provenance(),
    }


def _executable(identifier: str = "@molpack/pack") -> dict:
    return {
        "schema_version": "1",
        "id": identifier,
        "kind": "executable",
        "title": "Pack molecular system",
        "summary": "Pack fixed molecule targets under restraints and PBC.",
        "package": "molpack",
        "package_version": "0.4.2",
        "tags": ["packing"],
        "aliases": ["pack box"],
        "examples": [{"targets": 2}],
        "provenance": _provenance(),
        "invocation": {"kind": "python", "target": "molpack:pack"},
        "input_schema": {
            "type": "object",
            "properties": {
                "tolerance": {
                    "type": "number",
                    "x-molcrafts-unit": "angstrom",
                }
            },
            "required": ["tolerance"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "x-molcrafts-artifact-kind": "packed-structure",
        },
        "side_effects": [],
        "supported_backends": ["local"],
        "requirements": {
            "packages": ["molcrafts-molpack==0.4.2"],
            "executables": [],
            "platforms": ["any"],
        },
        "validators": [],
        "timeout_seconds": 3600,
        "resource_class": "cpu",
    }


def _manifest(*items: dict) -> dict:
    return {"schema_version": "1", "items": list(items)}


def test_manifest_digest_is_canonical_and_loader_owned():
    payload = _manifest(_concept(), _executable())
    first = loads_manifest(json.dumps(payload, ensure_ascii=False), source="memory:a")
    second = loads_manifest(
        json.dumps(payload, ensure_ascii=False, indent=4, sort_keys=True),
        source="memory:b",
    )

    assert first.digest == second.digest
    assert len(first.digest) == 64
    assert all(item.provenance.manifest_digest == first.digest for item in first.items)
    assert "manifest_digest" not in dumps_manifest(first)
    assert loads_manifest(dumps_manifest(first)).digest == first.digest

    reversed_items = load_manifest_data(_manifest(_executable(), _concept()))
    assert reversed_items.digest == first.digest


def test_loaded_executable_is_explicit_and_pinned():
    item = load_manifest_data(_manifest(_executable())).items[0]
    assert isinstance(item, ExecutableCapabilityV1)
    assert item.executable is True
    assert item.invocation.target == "molpack:pack"
    assert item.side_effects == ()


def test_concept_is_never_executable():
    item = load_manifest_data(_manifest(_concept())).items[0]
    assert type(item) is CatalogItemV1
    assert item.executable is False
    with pytest.raises(RegistryValidationError):
        Registry().register(_concept())  # type: ignore[arg-type]


def test_missing_explicit_side_effects_fails_closed():
    item = _executable()
    item.pop("side_effects")
    with pytest.raises(ManifestError, match="side_effects"):
        load_manifest_data(_manifest(item))


@pytest.mark.parametrize(
    "version", ["latest", "*", ">=0.4", "main", "banana", "1.x", "git+repo@main"]
)
def test_floating_executable_versions_are_rejected(version):
    item = _executable()
    item["package_version"] = version
    with pytest.raises(ManifestError, match="pinned version"):
        load_manifest_data(_manifest(item))


def test_unknown_fields_and_invalid_json_schema_are_rejected():
    unknown = _concept()
    unknown["surprise"] = True
    with pytest.raises(ManifestError, match="unknown field"):
        load_manifest_data(_manifest(unknown))

    invalid_schema = _executable()
    invalid_schema["input_schema"] = {"type": "definitely-not-json-schema"}
    with pytest.raises(ManifestError, match="invalid JSON Schema type"):
        load_manifest_data(_manifest(invalid_schema))


@pytest.mark.parametrize(
    "schema, match",
    [
        ({"$ref": "https://evil.test/schema.json"}, "local manifest reference"),
        ({"$ref": "#/$defs/missing"}, "missing local schema target"),
        ({"x-molcrafts-index-base": True}, "must be 0 or 1"),
        (
            {"dependentSchemas": {"atoms": {"x-molcrafts-index-base": 9}}},
            "must be 0 or 1",
        ),
    ],
)
def test_execution_schemas_are_self_contained_and_scientifically_strict(schema, match):
    item = _executable()
    item["input_schema"] = schema
    with pytest.raises(ManifestError, match=match):
        load_manifest_data(_manifest(item))


def test_valid_local_json_schema_reference_is_accepted():
    item = _executable()
    item["input_schema"] = {
        "$defs": {"coordinate": {"type": "number"}},
        "type": "array",
        "items": {"$ref": "#/$defs/coordinate"},
    }
    loaded = load_manifest_data(_manifest(item)).items[0]
    assert isinstance(loaded, ExecutableCapabilityV1)


@pytest.mark.parametrize(
    "requirement", ["not a requirement ???", "pkg @ https://evil.test/pkg.whl"]
)
def test_invalid_or_direct_url_package_requirements_are_rejected(requirement):
    item = _executable()
    item["requirements"]["packages"] = [requirement]
    with pytest.raises(ManifestError, match="package requirement|direct URL"):
        load_manifest_data(_manifest(item))


@pytest.mark.parametrize(
    "invocation, match",
    [
        ({"kind": "python", "target": "not a callable"}, "module:qualname"),
        ({"kind": "mcp", "target": "invalid tool!"}, "MCP tool name"),
        ({"kind": "cli", "target": ["bash", "-c", "rm -rf /"]}, "command shell"),
        ({"kind": "cli", "target": ["molpack", "bad\narg"]}, "NUL or newlines"),
    ],
)
def test_invocation_targets_are_typed_and_shell_free(invocation, match):
    item = _executable()
    item["invocation"] = invocation
    with pytest.raises(ManifestError, match=match):
        load_manifest_data(_manifest(item))


def test_duplicate_json_keys_and_ids_are_rejected():
    with pytest.raises(DuplicateJSONKeyError):
        loads_manifest('{"schema_version":"1","schema_version":"1","items":[]}')
    with pytest.raises(ManifestError, match="duplicate registry id"):
        load_manifest_data(_manifest(_concept(), _concept()))


def test_registry_registration_is_batch_atomic():
    first, second = load_manifest_data(
        _manifest(_concept(), _concept("@molpy/other"))
    ).items
    registry = Registry([first])
    with pytest.raises(RegistryConflictError):
        registry.register_many([second, first])
    assert registry.list_items() == [first]


def test_registry_search_is_unicode_aware_and_deterministic():
    manifest = load_manifest_data(_manifest(_concept(), _executable()))
    registry = Registry()
    registry.register_manifest(manifest)
    assert registry.search("径向分布函数")[0].id == "@molpy/analysis.rdf"
    assert registry.search("pack box")[0].id == "@molpack/pack"
    assert registry.search("", namespaces="@molpy")[0].id == "@molpy/analysis.rdf"
    assert registry.search("packing", kinds="executable")[0].executable is True


def test_registry_info_and_missing_lookup():
    registry = Registry()
    registry.register_manifest(load_manifest_data(_manifest(_executable())))
    assert registry.info()["executable_count"] == 1
    with pytest.raises(KeyError):
        registry.get("@molpy/missing")


def test_manifest_namespace_authority_fails_closed():
    manifest = load_manifest_data(_manifest(_executable("@molpack/pack")))
    registry = Registry()
    with pytest.raises(RegistryConflictError, match="foreign registry id"):
        registry.register_manifest(manifest, namespace="@molexp")
    assert len(registry) == 0

    registry.register_manifest(manifest, namespace="@molpack")
    info = registry.info()
    assert info["package_versions"] == {"molpack": ["0.4.2"]}
    assert info["backends"] == ["local"]
    assert info["manifests"][0]["digest"] == manifest.digest
    assert registry.record_info("@molpack/pack") == {
        "source": "<memory>",
        "manifest_digest": manifest.digest,
        "execution_status": "ready",
    }


def test_executable_cannot_bypass_manifest_digest_boundary():
    manifest = load_manifest_data(_manifest(_executable()))
    executable = manifest.items[0]
    with pytest.raises(RegistryValidationError, match="LoadedManifest"):
        Registry().register(executable)

    forged_data = executable.to_dict()
    forged_data["provenance"]["manifest_digest"] = "0" * 64
    forged = CatalogItemV1.from_dict(forged_data)
    with pytest.raises(ManifestError, match="canonical content"):
        LoadedManifest(
            schema_version="1",
            digest="0" * 64,
            items=(forged,),
            source="forged",
        )


def test_cross_manifest_validator_refs_resolve_atomically():
    executable = _executable()
    executable["validators"] = ["@molpack/validate-input"]
    validator = _concept("@molpack/validate-input")
    validator.update(
        kind="validator",
        package="molpack",
        package_version="0.4.2",
    )
    executable_manifest = load_manifest_data(_manifest(executable))
    validator_manifest = load_manifest_data(_manifest(validator))

    registry = Registry()
    with pytest.raises(RegistryConflictError, match="missing validator"):
        registry.register_manifest(executable_manifest)
    assert len(registry) == 0

    registry.register_manifests(
        (
            (executable_manifest, "@molpack", "ready"),
            (validator_manifest, "@molpack", "ready"),
        )
    )
    assert registry.get("@molpack/pack").executable is True


def test_incompatible_executable_package_versions_fail_atomically():
    first = _executable("@molpack/pack")
    second = _executable("@molpack/pack-v2")
    second["package_version"] = "0.5.0"
    manifests = (
        (load_manifest_data(_manifest(first)), "@molpack", "ready"),
        (load_manifest_data(_manifest(second)), "@molpack", "ready"),
    )
    registry = Registry()
    with pytest.raises(RegistryConflictError, match="incompatible package versions"):
        registry.register_manifests(manifests)
    assert len(registry) == 0


def test_search_only_executable_is_never_ready_for_handoff():
    manifest = load_manifest_data(_manifest(_executable()))
    registry = Registry()
    registry.register_manifest(manifest, execution_status="search_only")
    assert registry.execution_status("@molpack/pack") == "search_only"
    assert registry.is_executable("@molpack/pack") is False
    assert registry.info()["executable_count"] == 0
    assert registry.info()["search_only_executable_count"] == 1
