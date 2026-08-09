"""Unit tests for knowledge source allowlisting."""

from __future__ import annotations

from molmcp.settings import Settings
from molmcp.source_scope import (
    deny_source,
    filter_package_cards,
    get_source_allowlist,
    intersect_sources,
    normalize_source_name,
    parse_source_allowlist,
    ref_source,
    source_allowed,
)


def test_normalize_source_name() -> None:
    assert normalize_source_name("molpy") == "molpy"
    assert normalize_source_name("molcrafts-molpy") == "molpy"
    assert normalize_source_name("molpy.Atom") == "molpy"


def test_parse_and_allow() -> None:
    allow = parse_source_allowlist("molpy, molvis, molplot")
    assert allow is not None
    assert source_allowed("molpy", allow)
    assert source_allowed("molvis", allow)
    assert not source_allowed("atomiverse", allow)
    assert not source_allowed("molpack", allow)


def test_intersect_and_filter_cards() -> None:
    allow = parse_source_allowlist(["molpy", "molplot"])
    assert intersect_sources(["molpy", "atomiverse"], allow) == ["molpy"]
    cards = [
        {"name": "molpy", "summary": "a"},
        {"name": "atomiverse", "summary": "b"},
        {"name": "molplot", "summary": "c"},
    ]
    filtered = filter_package_cards(cards, allow)
    assert [c["name"] for c in filtered] == ["molpy", "molplot"]


def test_deny_payload() -> None:
    allow = parse_source_allowlist("molpy")
    denied = deny_source("atomiverse", allow)
    assert denied["ok"] is False
    assert denied["code"] == "SOURCE_NOT_ALLOWED"


def test_allowlist_comes_from_settings_not_the_environment() -> None:
    assert get_source_allowlist(Settings()) is None

    allow = get_source_allowlist(Settings(knowledge_scope=("molpy", "molvis")))

    assert allow is not None
    assert "molpy" in allow
    assert not source_allowed("atomiverse", allow)


def test_ref_source() -> None:
    assert ref_source("molpy.core.Atom") == "molpy"
    assert ref_source("@ns/name") is None
