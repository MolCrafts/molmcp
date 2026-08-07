"""``molvis`` stage introspection and module refresh.

Both modules are MCP-free and take no molvis dependency, so these tests
drive plain Python objects and a synthetic package on ``sys.path``.

The behaviour worth pinning is the honesty of the reports: a property must
not be described as something you call, and a rebuilt compiled extension
must not be described as refreshed when the process is still running the
old one.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from molmcp.providers.molvis.capabilities import (  # noqa: E402
    describe_stage,
    provenance,
)
from molmcp.providers.molvis.refresh import (  # noqa: E402
    PROCESS_START,
    native_modules,
    refresh_modules,
)


class StubStage:
    """A stage-shaped object covering every capability kind."""

    def __init__(self) -> None:
        self.width = 1200

    @property
    def n_frames(self) -> int:
        """Number of frames currently loaded."""
        return 3

    @property
    def exploding(self) -> int:
        """Reading this raises, as a misbehaving stage would."""
        raise RuntimeError("boom")

    def draw_frame(self, frame: object, *, clear: bool = False) -> None:
        """Place a molecular frame into the edit working tree."""

    def _private(self) -> None:
        """Not part of the surface."""


def _by_name(stage: object, **kwargs: object) -> dict[str, dict[str, object]]:
    caps = describe_stage(stage, **kwargs)  # type: ignore[arg-type]
    return {cap.name: cap.as_dict() for cap in caps}


class TestDescribeStage:
    def test_method_carries_signature_and_summary(self) -> None:
        found = _by_name(StubStage())["draw_frame"]
        assert found["kind"] == "method"
        assert "clear" in str(found["signature"])
        assert found["summary"] == (
            "Place a molecular frame into the edit working tree."
        )

    def test_property_is_not_reported_as_callable(self) -> None:
        # The whole point: an agent that sees a signature calls it, and
        # `n_frames()` on an int raises "'int' object is not callable".
        found = _by_name(StubStage())["n_frames"]
        assert found["kind"] == "property"
        assert found["signature"] is None
        assert found["summary"] == "Number of frames currently loaded."

    def test_property_is_described_without_being_evaluated(self) -> None:
        # `exploding` raises on read; describing the surface must not
        # trigger it, or listing a stage could have side effects.
        found = _by_name(StubStage())["exploding"]
        assert found["kind"] == "property"

    def test_plain_attribute_has_neither_signature_nor_summary(self) -> None:
        found = _by_name(StubStage())["width"]
        assert found == {
            "name": "width",
            "kind": "attribute",
            "signature": None,
            "summary": None,
        }

    def test_private_names_are_excluded(self) -> None:
        assert "_private" not in _by_name(StubStage())

    def test_pattern_filters_case_insensitively(self) -> None:
        assert set(_by_name(StubStage(), pattern="FRAME")) == {
            "draw_frame",
            "n_frames",
        }

    def test_results_are_sorted_by_name(self) -> None:
        names = [cap.name for cap in describe_stage(StubStage())]
        assert names == sorted(names)


class TestProvenance:
    def test_reports_version_slots_and_a_restart_verdict(self) -> None:
        report = provenance()
        assert set(report["versions"]) == {  # type: ignore[arg-type]
            "molcrafts-molvis",
            "molcrafts-molpy",
            "molcrafts-molrs",
        }
        assert isinstance(report["restart_required"], bool)


@pytest.fixture
def synthetic_package(tmp_path: Path) -> str:
    """Import a two-module package from *tmp_path* and yield its name."""
    name = "molmcp_refresh_fixture"
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("VALUE = 1\n")
    (pkg / "leaf.py").write_text("LEAF = 1\n")
    sys.path.insert(0, str(tmp_path))
    __import__(f"{name}.leaf")
    try:
        yield name
    finally:
        sys.path.remove(str(tmp_path))
        for mod in [m for m in list(sys.modules) if m.startswith(name)]:
            del sys.modules[mod]


class TestRefreshModules:
    def test_purges_package_and_submodules(self, synthetic_package: str) -> None:
        report = refresh_modules((synthetic_package,))
        assert set(report.purged) == {
            synthetic_package,
            f"{synthetic_package}.leaf",
        }
        assert synthetic_package not in sys.modules

    def test_next_import_reads_the_edited_source(
        self, synthetic_package: str, tmp_path: Path
    ) -> None:
        # The replacement must differ in *size*, not just content: a `.pyc`
        # is validated against the source's size and its mtime truncated to
        # whole seconds, so a same-length edit inside one second would be
        # served from stale bytecode. Any real edit changes the length.
        (tmp_path / synthetic_package / "__init__.py").write_text(
            "VALUE = 2  # edited\n"
        )
        refresh_modules((synthetic_package,))
        assert __import__(synthetic_package).VALUE == 2

    def test_unrelated_modules_are_untouched(self, synthetic_package: str) -> None:
        report = refresh_modules((synthetic_package,))
        assert "sys" not in report.purged

    def test_prefix_matches_on_the_dotted_boundary(
        self, synthetic_package: str
    ) -> None:
        # `molrs` must not also select `molrs_helpers`.
        sibling = f"{synthetic_package}_sibling"
        sys.modules[sibling] = types.ModuleType(sibling)
        try:
            report = refresh_modules((synthetic_package,))
            assert sibling not in report.purged
            assert sibling in sys.modules
        finally:
            del sys.modules[sibling]

    def test_no_native_extension_means_no_restart(self, synthetic_package: str) -> None:
        report = refresh_modules((synthetic_package,))
        assert report.native == ()
        assert report.restart_required is False


class TestNativeExtensionHonesty:
    """A mapped `.so` rebuilt after start-up must be reported, not purged."""

    @pytest.fixture
    def rebuilt_extension(self, tmp_path: Path) -> str:
        name = "molmcp_native_fixture"
        so = tmp_path / "_lib.abi3.so"
        so.write_bytes(b"\x00")
        # Stamp it into the future: the same relation a rebuild has to a
        # process that started earlier.
        import os

        os.utime(so, (PROCESS_START + 60, PROCESS_START + 60))

        module = types.ModuleType(name)
        module.__file__ = str(so)
        sys.modules[name] = module
        try:
            yield name
        finally:
            sys.modules.pop(name, None)

    def test_rebuilt_extension_demands_a_restart(self, rebuilt_extension: str) -> None:
        report = refresh_modules((rebuilt_extension,))
        assert report.restart_required is True
        assert [mod.module for mod in report.native] == [rebuilt_extension]

    def test_rebuilt_extension_is_not_purged(self, rebuilt_extension: str) -> None:
        # Dropping it would rebind the *same* mapped code under a new
        # module object while making the swap look successful.
        report = refresh_modules((rebuilt_extension,))
        assert rebuilt_extension not in report.purged
        assert rebuilt_extension in sys.modules

    def test_extension_older_than_start_is_not_flagged(self, tmp_path: Path) -> None:
        import os

        name = "molmcp_native_old_fixture"
        so = tmp_path / "_old.abi3.so"
        so.write_bytes(b"\x00")
        os.utime(so, (PROCESS_START - 60, PROCESS_START - 60))
        module = types.ModuleType(name)
        module.__file__ = str(so)
        sys.modules[name] = module
        try:
            mapped = native_modules((name,))
            assert [mod.changed_since_start for mod in mapped] == [False]
        finally:
            sys.modules.pop(name, None)
