"""Task routing guide — help LLMs pick the right MolCrafts package.

Built from the **live** collection inventory (which sources are configured and
fresh), not a molexp-side hard-coded package table. Molexp asks molmcp for this
guide; the checklist and suggested queries are derived here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "build_routing_guide",
    "intent_tags_for_task",
    "resolve_source_alias",
    "role_for_source",
    "roles_for_source",
]

# Generic English intent cues → abstract roles. Roles are matched against
# *discovered* source package names (molpack, molpy, …), never hard-coded as
# "always query molpack".
_INTENT_CUES: tuple[tuple[frozenset[str], str], ...] = (
    (
        frozenset({"pack", "packing", "solvate", "solvating", "insert", "fill", "box"}),
        "packing",
    ),
    (
        frozenset(
            {
                "bead",
                "coarse",
                "cg",
                "topology",
                "frame",
                "structure",
                "molecule",
                "atom",
                "bond",
                "forcefield",
                "force-field",
            }
        ),
        "structure",
    ),
    (
        frozenset(
            {"lammps", "gromacs", "openmm", "trajectory", "data file", "restart"}
        ),
        "io_sim",
    ),
    (frozenset({"plot", "visual", "chart", "figure", "render"}), "visualization"),
    (frozenset({"queue", "schedule", "hpc", "slurm", "submit", "job"}), "scheduling"),
    (frozenset({"workflow", "experiment", "run", "artifact", "workspace"}), "workflow"),
    (frozenset({"analyze", "analysis", "rdf", "msd", "metric"}), "analysis"),
)

# Package-name fragments → primary role. Applied only to sources present in
# the live inventory (auto-discovered distributions). Longer fragments win.
_SOURCE_ROLE_FRAGMENTS: tuple[tuple[str, str], ...] = (
    ("molpack", "packing"),
    ("pack", "packing"),
    ("molplot", "visualization"),
    ("plot", "visualization"),
    ("molq", "scheduling"),
    ("queue", "scheduling"),
    ("molexp", "workflow"),
    ("molpy", "structure"),
    ("molvis", "visualization"),
)

# Extra roles a package may also satisfy (e.g. molpy owns structure *and*
# simulator I/O writers). Prevents false "intent io_sim has no source" when
# only molpy is installed.
_SOURCE_EXTRA_ROLES: tuple[tuple[str, str], ...] = (
    ("molpy", "io_sim"),
    ("molpy", "analysis"),
)

# Canonical short name → accepted inventory name fragments (for alias match).
_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "molpy": ("molpy", "molcrafts-molpy", "molcrafts_molpy"),
    "molpack": ("molpack", "molcrafts-molpack", "molcrafts_molpack"),
    "molq": ("molq", "molcrafts-molq", "molcrafts_molq"),
    "molexp": ("molexp", "molcrafts-molexp", "molcrafts_molexp"),
    "molplot": ("molplot", "molcrafts-molplot", "molcrafts_molplot"),
}

_GLOBAL_RULES: tuple[str, ...] = (
    "Primary path: packages → outline → open → compose (inject pages).",
    "search/suggest are index helpers only; open exact refs before coding.",
    "Source symbols are evidence only; bind only executable=true for Molexp.",
    "ok=false / SYMBOL_NOT_FOUND means the API does not exist — do not invent it.",
    "Prefer the package whose role matches the task step over a generic helper.",
    "Never hand-roll what a specialized package already provides.",
)


def intent_tags_for_task(task: str) -> list[str]:
    """Return abstract intent roles detected in free-text *task*."""
    lower = task.lower()
    tags: list[str] = []
    for cues, role in _INTENT_CUES:
        if any(cue in lower for cue in cues):
            tags.append(role)
    return list(dict.fromkeys(tags))


def role_for_source(source_name: str) -> str | None:
    """Best-effort primary role for a discovered source name, or None."""
    n = _norm_source(source_name)
    # Prefer longer / more specific fragments first.
    for frag, role in sorted(_SOURCE_ROLE_FRAGMENTS, key=lambda x: -len(x[0])):
        if frag in n:
            return role
    return None


def roles_for_source(source_name: str) -> list[str]:
    """All roles a source can satisfy (primary + extras)."""
    n = _norm_source(source_name)
    roles: list[str] = []
    primary = role_for_source(source_name)
    if primary:
        roles.append(primary)
    for frag, role in _SOURCE_EXTRA_ROLES:
        if frag in n and role not in roles:
            roles.append(role)
    return roles


def resolve_source_alias(
    name: str, inventory: Sequence[str] | Mapping[str, Any]
) -> str | None:
    """Map a short/alias name to an inventory source key, or None.

    ``molpy`` → ``molcrafts-molpy`` when that is the configured source name.
    Exact match wins; then alias table; then substring.
    """
    names = (
        list(inventory.keys()) if isinstance(inventory, Mapping) else list(inventory)
    )
    if name in names:
        return name
    n = _norm_source(name)
    # Alias table: preferred canonical short names.
    for canon, aliases in _SOURCE_ALIASES.items():
        if n == canon or n in {_norm_source(a) for a in aliases}:
            for inv in names:
                inv_n = _norm_source(inv)
                if any(a.replace("_", "-") in inv_n for a in aliases):
                    return inv
    # Loose: query is a fragment of inventory name or vice versa.
    for inv in names:
        inv_n = _norm_source(inv)
        if n in inv_n or inv_n in n:
            return inv
    return None


def _norm_source(name: str) -> str:
    return name.lower().replace("_", "-")


def build_routing_guide(
    task: str,
    *,
    sources: Mapping[str, Any] | None = None,
    hits: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a structured routing guide for *task* from live inventory + optional hits.

    Args:
        task: Natural-language experiment or step description.
        sources: ``collection.info()["sources"]`` mapping (name → state).
        hits: Optional ranked search hit dicts (from ``search`` / explore).

    Returns:
        A JSON-serializable guide: checklist, rules, suggested_queries,
        available_sources, preferred_packages, top_hits.
    """
    task = (task or "").strip()
    source_map = dict(sources or {})
    available: list[dict[str, Any]] = []
    packages_by_role: dict[str, list[str]] = {}
    for name, state in sorted(source_map.items()):
        if not isinstance(state, dict):
            state = {}
        status = state.get("status", "unknown")
        role = role_for_source(name)
        entry = {
            "name": name,
            "status": status,
            "role": role,
            "roles": roles_for_source(name),
            "spec": state.get("spec"),
            "freshness": state.get("freshness"),
        }
        available.append(entry)
        if status == "ok":
            for r in roles_for_source(name):
                packages_by_role.setdefault(r, []).append(name)

    intents = intent_tags_for_task(task) if task else []
    checklist: list[dict[str, Any]] = []
    suggested: list[str] = []
    if task:
        suggested.append(task)

    for role in intents or list(packages_by_role.keys()):
        packages = packages_by_role.get(role, [])
        when = _when_for_role(role)
        prefer = packages or _fallback_prefer_hint(role, available)
        avoid = _avoid_for_role(role)
        search_q = (
            " ".join(prefer[:2] + [role, "public API"])
            if prefer
            else f"{role} public API"
        )
        checklist.append(
            {
                "when": when,
                "role": role,
                "prefer_packages": prefer,
                "search_query": search_q,
                "avoid": avoid,
                "available": bool(packages),
            }
        )
        if prefer:
            suggested.append(search_q)
            suggested.append(f"{prefer[0]} public API capabilities")

    # Always probe every OK science-looking source so nothing is dropped only
    # because the draft never mentioned its name.
    for entry in available:
        if entry.get("status") != "ok":
            continue
        name = str(entry["name"])
        if entry.get("role"):
            suggested.append(f"{name} public API")

    preferred_packages = sorted(
        {
            p
            for role in (intents or packages_by_role)
            for p in packages_by_role.get(role, [])
        }
    )

    top_hits: list[dict[str, Any]] = []
    for hit in list(hits or [])[:12]:
        if not isinstance(hit, Mapping):
            continue
        top_hits.append(
            {
                "ref": hit.get("ref"),
                "title": hit.get("title") or hit.get("qualname"),
                "source": hit.get("source"),
                "executable": bool(hit.get("executable")),
                "signature": hit.get("signature"),
                "summary": hit.get("summary"),
            }
        )

    missing_roles = [c["role"] for c in checklist if not c.get("available")]
    warnings: list[str] = []
    for role in missing_roles:
        warnings.append(
            f"intent {role!r} has no installed/ok source — install the matching "
            "MolCrafts package or the plan will invent APIs"
        )

    return {
        "ok": True,
        "code": None,
        "error": None,
        "task": task,
        "intents": intents,
        "checklist": checklist,
        "rules": list(_GLOBAL_RULES),
        "suggested_queries": list(
            dict.fromkeys(q for q in suggested if q and str(q).strip())
        ),
        "available_sources": available,
        "preferred_packages": preferred_packages,
        "top_hits": top_hits,
        "warnings": warnings,
        "how_to_use": (
            "1) molcrafts_packages — pick sources from summaries. "
            "2) molcrafts_outline(source=…) — browse modules. "
            "3) molcrafts_open(ref) before codegen. "
            "4) Bind only executable=true (or APIs confirmed via open)."
        ),
    }


def _when_for_role(role: str) -> str:
    return {
        "packing": ("packing / inserting / solvating molecules into a simulation box"),
        "structure": (
            "building molecular / coarse-grained structure, frames, "
            "topology, force fields"
        ),
        "io_sim": ("writing/reading simulator input-output (data files, trajectories)"),
        "visualization": "plotting or rendering results",
        "scheduling": "queueing jobs on local/HPC backends",
        "workflow": "experiment/run lifecycle, artifacts, workspace operations",
        "analysis": (
            "post-processing and scientific analysis of trajectories/structures"
        ),
    }.get(role, f"tasks related to role {role!r}")


def _avoid_for_role(role: str) -> str:
    return {
        "packing": ("hand-rolled random XYZ placement that breaks bonded geometry"),
        "structure": ("invented accessors (e.g. guessing Bead.type without open)"),
        "io_sim": ("string-building simulator files without the package's writer API"),
        "visualization": ("ad-hoc plotting when a MolCrafts plot package is available"),
        "scheduling": ("raw SSH/subprocess job submission bypassing the queue package"),
        "workflow": "direct filesystem hacks around Run/Experiment identity",
        "analysis": ("reimplementing standard analysis kernels present in the catalog"),
    }.get(role, "inventing APIs not returned by molmcp")


def _fallback_prefer_hint(
    role: str, available: Sequence[Mapping[str, Any]]
) -> list[str]:
    """When no source matches the role, still name the expected package family."""
    # Soft hints only — listed as unavailable in checklist.
    hints = {
        "packing": ["molpack"],
        "structure": ["molpy"],
        "io_sim": ["molpy"],
        "visualization": ["molplot"],
        "scheduling": ["molq"],
        "workflow": ["molexp"],
        "analysis": ["molpy"],
    }.get(role, [])
    present = {str(e.get("name", "")).lower() for e in available}
    # Prefer hint names that appear in inventory under another spelling.
    out = []
    for h in hints:
        if any(h in p for p in present):
            out.append(h)
        else:
            out.append(h)  # still list for the LLM even if missing
    return out


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))
