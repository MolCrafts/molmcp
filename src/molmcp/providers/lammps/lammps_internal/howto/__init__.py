"""Extensible LAMMPS howto registry.

A *howto* is a short, curated entry covering one self-contained LAMMPS
task — debugging a setup crash, computing elastic constants, setting up
TIP3P water, etc. Howtos are *pointers + skeletons*, not substitutes
for the docs.

This is a developer extension point. The howto registry sits alongside
LAMMPS's own ``Howto_<topic>.html`` doc pages: those are doc URLs we
hand off to the LLM (kind ``howto_topic`` in :mod:`urls`); these are
package-curated playbooks with rationale, user-facing steps, optional
snippets, and pointers into the official docs.

Adding a howto
--------------

1. Open the relevant category file under ``howto/`` (e.g.
   ``howto/mechanics.py``) — or create a new category file and a new
   entry under :data:`CATEGORY_DESCRIPTIONS`.
2. Append a ``Howto(...)`` literal to that module's ``HOWTOS`` tuple.
3. If you created a new module, import it in :func:`_load_all`.

That's the whole interface. No spec or schema changes needed.

Public surface
--------------

- :class:`Howto` — frozen dataclass schema.
- :func:`list_categories` — categories + counts + descriptions.
- :func:`find` — keyword search; optional category filter.
- :func:`get` — fetch a single howto by ``(category, slug)``.
- :func:`all_howtos` — iterate everything (used by tests + tools).
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import urls

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "debug": "Debug techniques: skip-run, echo, comment-bisect, neigh modify, ...",
    "mechanics": "Stress, strain, elastic constants, deformation protocols",
    "transport": "Thermal conductivity, viscosity, diffusion coefficients",
    "equilibration": "Minimize-then-MD, NPT-to-NVT handoff, gradual thermalization",
    "rerun": "Post-hoc trajectory analysis via the rerun command",
    "forcefield": "CHARMM, AMBER, OPLS, TIP3P, TIP4P setup",
    "polymer": "Polymer setup, bond-break protocols, collapse checks",
    "output": "Thermo, dump, multi-replica output patterns",
}


@dataclass(frozen=True)
class Howto:
    """One curated LAMMPS howto entry."""

    category: str
    slug: str
    title: str
    rationale: str
    user_steps: tuple[str, ...] = ()
    snippet: str | None = None
    snippet_caveat: str | None = None
    doc_refs: tuple[str, ...] = ()  # slugs (e.g. "Howto_elastic"), URLs built later
    related_commands: tuple[tuple[str, str], ...] = ()  # (kind, name)
    related_howtos: tuple[tuple[str, str], ...] = ()  # (category, slug)
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.snippet is not None and not self.snippet_caveat:
            raise ValueError(
                f"howto {self.category}/{self.slug}: snippet without snippet_caveat"
            )
        if self.snippet is not None and len(self.snippet.splitlines()) > 30:
            raise ValueError(
                f"howto {self.category}/{self.slug}: snippet exceeds 30 lines"
            )

    def search_text(self) -> str:
        return " ".join(
            [self.title, self.rationale, *self.tags, self.slug]
        ).lower()

    def to_summary_dict(self) -> dict:
        return {
            "category": self.category,
            "slug": self.slug,
            "title": self.title,
            "summary": self.rationale.split(". ")[0].strip(),
            "tags": list(self.tags),
        }

    def to_full_dict(self, version: str) -> dict:
        urls._validate_version(version)
        out: dict[str, object] = {
            "category": self.category,
            "slug": self.slug,
            "title": self.title,
            "rationale": self.rationale,
            "user_steps": list(self.user_steps),
            "doc_refs": [urls.build_url(s, version) for s in self.doc_refs],
            "related_commands": [
                {
                    "kind": kind,
                    "name": name,
                    "url": (
                        urls.build_url(urls.PAGE_SLUGS[(kind, name)], version)
                        if (kind, name) in urls.PAGE_SLUGS
                        else None
                    ),
                }
                for (kind, name) in self.related_commands
            ],
            "related_howtos": [
                {"category": c, "slug": s} for (c, s) in self.related_howtos
            ],
            "tags": list(self.tags),
            "version": version,
        }
        if self.snippet is not None:
            out["snippet"] = self.snippet
            out["snippet_caveat"] = self.snippet_caveat
        return out


def _load_all() -> tuple[Howto, ...]:
    """Aggregate ``HOWTOS`` from every category submodule."""
    from . import (
        debug,
        equilibration,
        forcefield,
        mechanics,
        output,
        polymer,
        rerun,
        transport,
    )
    aggregated: list[Howto] = []
    for module in (
        debug, mechanics, transport, equilibration, rerun,
        forcefield, polymer, output,
    ):
        aggregated.extend(getattr(module, "HOWTOS", ()))
    seen: dict[tuple[str, str], Howto] = {}
    for r in aggregated:
        key = (r.category, r.slug)
        if key in seen:
            raise ValueError(f"duplicate howto key: {key}")
        seen[key] = r
    return tuple(aggregated)


_ALL: tuple[Howto, ...] | None = None


def all_howtos() -> tuple[Howto, ...]:
    global _ALL
    if _ALL is None:
        _ALL = _load_all()
    return _ALL


def list_categories() -> dict:
    counts: dict[str, int] = {}
    for r in all_howtos():
        counts[r.category] = counts.get(r.category, 0) + 1
    return {
        "categories": [
            {
                "name": name,
                "count": counts.get(name, 0),
                "description": CATEGORY_DESCRIPTIONS.get(name, ""),
            }
            for name in CATEGORY_DESCRIPTIONS
        ],
        "guidance": (
            "Use search_howtos(query, category=...) to search; "
            "get_howto(category, slug) for full content."
        ),
    }


def find(
    query: str, category: str | None = None, limit: int = 25
) -> dict:
    norm = query.strip().lower()
    matches: list[tuple[float, Howto]] = []
    for r in all_howtos():
        if category is not None and r.category != category:
            continue
        text = r.search_text()
        if not norm:
            score = 0.0
        else:
            tokens = [t for t in norm.split() if t]
            hits = sum(1 for t in tokens if t in text)
            if hits == 0:
                continue
            score = -hits
        matches.append((score, r))
    matches.sort(key=lambda x: (x[0], x[1].category, x[1].slug))
    truncated = False
    if len(matches) > limit:
        matches = matches[:limit]
        truncated = True
    return {
        "query": query,
        "category": category,
        "matches": [r.to_summary_dict() for _, r in matches],
        "truncated": truncated,
    }


def get(
    category: str, slug: str, version: str = urls.DEFAULT_VERSION
) -> dict:
    for r in all_howtos():
        if r.category == category and r.slug == slug:
            return r.to_full_dict(version)
    return {
        "error": f"no howto at {category}/{slug}",
        "category": category,
        "slug": slug,
        "available_in_category": [
            r.slug for r in all_howtos() if r.category == category
        ],
    }
