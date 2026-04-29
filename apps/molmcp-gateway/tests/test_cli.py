"""Tests for ``molmcp-gateway`` CLI argument resolution."""

from __future__ import annotations

import pytest

pytest.importorskip("molmcp", reason="molcrafts-molmcp not installed")
pytest.importorskip("fastmcp", reason="fastmcp not installed")

from molmcp_gateway.cli import _resolve_import_roots, build_parser  # noqa: E402
from molmcp_gateway.config import DEFAULT_IMPORT_ROOTS  # noqa: E402


def _parse(*argv: str):
    return build_parser().parse_args(list(argv))


def test_resolve_import_roots_uses_defaults() -> None:
    assert _resolve_import_roots(_parse()) == DEFAULT_IMPORT_ROOTS


def test_resolve_import_roots_appends_extras_in_order() -> None:
    args = _parse("--import-root", "molpack", "--import-root", "molq")
    assert _resolve_import_roots(args) == DEFAULT_IMPORT_ROOTS + ("molpack", "molq")


def test_resolve_import_roots_dedups_overlap_with_defaults() -> None:
    args = _parse("--import-root", "molpy", "--import-root", "molpack")
    assert _resolve_import_roots(args) == DEFAULT_IMPORT_ROOTS + ("molpack",)


def test_resolve_import_roots_skips_defaults_when_disabled() -> None:
    args = _parse("--no-default-import-roots", "--import-root", "molpack")
    assert _resolve_import_roots(args) == ("molpack",)


def test_resolve_import_roots_no_introspection_returns_empty() -> None:
    args = _parse("--no-introspection", "--import-root", "molpack")
    assert _resolve_import_roots(args) == ()


def test_resolve_import_roots_strips_whitespace_and_drops_empty() -> None:
    args = _parse(
        "--no-default-import-roots",
        "--import-root",
        "  molpack  ",
        "--import-root",
        "",
    )
    assert _resolve_import_roots(args) == ("molpack",)
