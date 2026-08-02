"""Optional source allowlist for knowledge tools (packages / outline / open / search).

When set, agents may only consult the named MolCrafts packages — e.g. a
visualization task can pin ``molpy,molvis,molplot`` and never surface
``atomiverse``. Empty / unset = all configured sources (legacy behaviour).

Configuration (first match wins for process-wide default):

* Environment ``MOLMCP_SOURCES`` — comma-separated names
  (``molpy,molvis,molplot``; aliases ``molcrafts-molpy`` accepted).
* Per-tool ``sources=`` argument still works as a *further* intersection with
  this allowlist (cannot widen past it).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from typing import Any

__all__ = [
    "ENV_SOURCES",
    "deny_source",
    "filter_package_cards",
    "get_env_source_allowlist",
    "intersect_sources",
    "normalize_source_name",
    "parse_source_allowlist",
    "ref_source",
    "source_allowed",
]

ENV_SOURCES = "MOLMCP_SOURCES"

_SPLIT = re.compile(r"[\s,;]+")


def normalize_source_name(name: str) -> str:
    """Lowercase root package id (``molcrafts-molpy`` → ``molpy``)."""
    raw = (name or "").strip().lower()
    if not raw:
        return ""
    # registry-style @ns/pkg or path-ish leftovers
    if raw.startswith("@"):
        raw = raw.split("/", 1)[-1]
    # distribution name molcrafts-molpy → molpy; molpy stays molpy
    dashed = raw.replace("_", "-")
    parts = [p for p in dashed.split("-") if p]
    if len(parts) >= 2 and parts[0] in {"molcrafts", "pkg"}:
        return parts[-1]
    # symbol-ish molpy.Atom → molpy
    if "." in raw and not raw.startswith("."):
        return raw.split(".", 1)[0]
    return raw


def parse_source_allowlist(raw: str | Sequence[str] | None) -> frozenset[str] | None:
    """Parse allowlist; ``None`` means unrestricted."""
    if raw is None:
        return None
    if isinstance(raw, str):
        if not raw.strip() or raw.strip() in {"*", "all"}:
            return None
        items = [p for p in _SPLIT.split(raw.strip()) if p]
    else:
        items = [str(x).strip() for x in raw if str(x).strip()]
    if not items:
        return None
    roots = {normalize_source_name(x) for x in items}
    roots.discard("")
    return frozenset(roots) if roots else None


def get_env_source_allowlist() -> frozenset[str] | None:
    """Process-wide allowlist from :data:`ENV_SOURCES`."""
    return parse_source_allowlist(os.environ.get(ENV_SOURCES))


def source_allowed(source: str, allow: frozenset[str] | None) -> bool:
    if allow is None:
        return True
    root = normalize_source_name(source)
    if not root:
        return False
    if root in allow:
        return True
    # allow "molpy" when source is "molpy.core"
    base = root.split(".", 1)[0]
    if base in allow:
        return True
    return any(
        root == a or root.startswith(a + ".") or a.startswith(root) for a in allow
    )


def ref_source(ref: str) -> str | None:
    """Best-effort source root from a symbol ref (``molpy.Atom`` → ``molpy``)."""
    text = (ref or "").strip()
    if not text:
        return None
    if text.startswith("@"):
        # @ns/name — not a source root
        return None
    if "::" in text:
        text = text.split("::", 1)[0]
    if "." in text:
        return normalize_source_name(text.split(".", 1)[0])
    return normalize_source_name(text)


def intersect_sources(
    requested: Sequence[str] | None,
    allow: frozenset[str] | None,
) -> list[str] | None:
    """Intersect tool ``sources=`` with process allowlist.

    Returns ``None`` when unrestricted and no request; empty list when the
    intersection is empty (caller should deny).
    """
    if allow is None and not requested:
        return None
    if requested:
        req = [normalize_source_name(s) for s in requested if str(s).strip()]
        req = [s for s in req if s]
        if allow is None:
            return req
        return [s for s in req if source_allowed(s, allow)]
    # no request → pin to full allowlist so search/compose cannot widen
    return sorted(allow) if allow is not None else None


def deny_source(source: str, allow: frozenset[str] | None) -> dict[str, Any]:
    allowed = ", ".join(sorted(allow)) if allow else "(none)"
    return {
        "ok": False,
        "code": "SOURCE_NOT_ALLOWED",
        "error": (
            f"source {source!r} is outside the active knowledge scope "
            f"(allowed: {allowed})"
        ),
        "hint": (
            "Pin sources via MOLMCP_SOURCES or tool sources= "
            f"(allowed: {allowed}). Do not invent APIs from out-of-scope packages."
        ),
        "markdown": "",
        "data": {"source": source, "allowed_sources": sorted(allow or ())},
    }


def filter_package_cards(
    cards: Iterable[dict[str, Any]],
    allow: frozenset[str] | None,
) -> list[dict[str, Any]]:
    if allow is None:
        return list(cards)
    out: list[dict[str, Any]] = []
    for card in cards:
        name = card.get("name") if isinstance(card, dict) else None
        if isinstance(name, str) and source_allowed(name, allow):
            out.append(card)
    return out
