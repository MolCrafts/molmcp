"""Heuristic free-text → doc-page list.

Pure function over a keyword/synonym table. The router does not
"understand" the task; it pattern-matches against keywords seeded from
common LAMMPS workflows. The LLM is responsible for refining the
shortlist via its own reasoning + WebFetch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import urls


@dataclass(frozen=True)
class DocQuery:
    kind: str  # "command" | "fix" | "pair_style" | "howto_topic" | "style"
    name: str | None
    category: str | None  # for "style" with name pattern
    name_pattern: str | None  # for fuzzy hints (e.g. "*coul/long")
    reason: str

    def to_dict(self, version: str) -> dict:
        out: dict[str, object] = {"kind": self.kind, "reason": self.reason}
        if self.name is not None:
            out["name"] = self.name
        if self.category is not None:
            out["category"] = self.category
        if self.name_pattern is not None:
            out["name_pattern"] = self.name_pattern
        # build URL when we have a concrete (kind, name) hit
        if self.kind == "command" and self.name is not None:
            key = ("command", self.name)
            if key in urls.PAGE_SLUGS:
                out["url"] = urls.build_url(urls.PAGE_SLUGS[key], version)
        elif self.kind in {"fix", "compute", "dump", "pair_style", "bond_style",
                           "angle_style", "dihedral_style", "improper_style",
                           "kspace_style", "atom_style", "region"} and self.name:
            key = (self.kind, self.name)
            if key in urls.PAGE_SLUGS:
                out["url"] = urls.build_url(urls.PAGE_SLUGS[key], version)
        elif self.kind == "howto_topic" and self.name:
            if self.name in urls.HOWTO_TOPICS:
                out["url"] = urls.build_url(f"Howto_{self.name}", version)
        elif self.kind == "style" and self.category and self.name_pattern:
            out["url_hint_template"] = f"{self.category}_<style>.html"
        return out


# Concrete query → reason, indexed by lowercased keyword. Values are
# tuples to allow several queries per keyword. Keep this list small and
# heavily biased toward common protocols.
KEYWORD_TO_QUERIES: dict[str, tuple[DocQuery, ...]] = {
    "npt": (
        DocQuery("fix", "npt", None, None, "NPT ensemble (shared fix_nh page)"),
        DocQuery("howto_topic", "thermostat", None, None, "ensemble choice rationale"),
        DocQuery("howto_topic", "barostat", None, None, "barostat options"),
    ),
    "nvt": (
        DocQuery("fix", "nvt", None, None, "NVT ensemble (shared fix_nh page)"),
        DocQuery("howto_topic", "thermostat", None, None, "ensemble choice rationale"),
    ),
    "nve": (
        DocQuery("fix", "nve", None, None, "constant-energy integrator"),
    ),
    "nph": (
        DocQuery("fix", "nph", None, None, "constant-pressure (shared fix_nh page)"),
    ),
    "minimization": (
        DocQuery("command", "minimize", None, None, "energy minimization"),
        DocQuery("command", "min_style", None, None, "minimization algorithms"),
    ),
    "minimize": (
        DocQuery("command", "minimize", None, None, "energy minimization"),
        DocQuery("command", "min_style", None, None, "minimization algorithms"),
    ),
    "energy minimization": (
        DocQuery("command", "minimize", None, None, "energy minimization"),
    ),
    "deformation": (
        DocQuery("fix", "deform", None, None, "applied deformation"),
        DocQuery("howto_topic", "elastic", None, None, "elastic constants protocol"),
    ),
    "deform": (
        DocQuery("fix", "deform", None, None, "applied deformation"),
    ),
    "elastic": (
        DocQuery("howto_topic", "elastic", None, None, "elastic constants protocol"),
        DocQuery("fix", "deform", None, None, "strain application"),
    ),
    "stress": (
        DocQuery("compute", "stress/atom", None, None, "per-atom stress tensor"),
        DocQuery("compute", "pressure", None, None, "system pressure"),
    ),
    "strain": (
        DocQuery("fix", "deform", None, None, "imposed strain"),
    ),
    "long-range": (
        DocQuery("command", "kspace_style", None, None, "long-range solvers"),
    ),
    "long range": (
        DocQuery("command", "kspace_style", None, None, "long-range solvers"),
    ),
    "coulomb": (
        DocQuery("command", "kspace_style", None, None, "long-range Coulomb"),
        DocQuery("style", None, "pair_style", "*coul*",
                 "pair styles with explicit Coulomb"),
    ),
    "ewald": (
        DocQuery("command", "kspace_style", None, None, "Ewald summation"),
    ),
    "pppm": (
        DocQuery("command", "kspace_style", None, None, "P3M solver"),
    ),
    "thermostat": (
        DocQuery("howto_topic", "thermostat", None, None, "thermostat options"),
        DocQuery("fix", "langevin", None, None, "Langevin thermostat"),
        DocQuery("fix", "temp/csvr", None, None, "stochastic velocity rescale"),
    ),
    "barostat": (
        DocQuery("howto_topic", "barostat", None, None, "barostat options"),
        DocQuery("fix", "press/berendsen", None, None, "Berendsen barostat"),
    ),
    "langevin": (
        DocQuery("fix", "langevin", None, None, "Langevin thermostat"),
    ),
    "rerun": (
        DocQuery("command", "rerun", None, None, "post-hoc trajectory analysis"),
        DocQuery("command", "read_dump", None, None, "load trajectory frames"),
    ),
    "trajectory": (
        DocQuery("command", "rerun", None, None, "post-hoc analysis"),
        DocQuery("command", "dump", None, None, "trajectory output"),
    ),
    "polymer": (
        DocQuery("bond_style", "fene", None, None, "FENE bonds for chains"),
        DocQuery("bond_style", "harmonic", None, None, "harmonic bonds"),
        DocQuery("howto_topic", "bpm", None, None, "bonded particle models"),
    ),
    "polymer melt": (
        DocQuery("bond_style", "fene", None, None, "FENE bonds for melts"),
    ),
    "tip3p": (
        DocQuery("howto_topic", "tip3p", None, None, "TIP3P water setup"),
    ),
    "tip4p": (
        DocQuery("howto_topic", "tip4p", None, None, "TIP4P water setup"),
        DocQuery("pair_style", "lj/cut/tip4p/long", None, None, "TIP4P pair_style"),
    ),
    "spc": (
        DocQuery("howto_topic", "spc", None, None, "SPC/SPC-E water setup"),
    ),
    "amber": (
        DocQuery("howto_topic", "amber2lammps", None, None, "AMBER → LAMMPS"),
        DocQuery("howto_topic", "bioFF", None, None, "biomolecular force fields"),
    ),
    "charmm": (
        DocQuery("howto_topic", "bioFF", None, None, "CHARMM in LAMMPS"),
        DocQuery("pair_style", "lj/charmm/coul/long", None, None, "CHARMM pair_style"),
    ),
    "opls": (
        DocQuery("howto_topic", "bioFF", None, None, "OPLS in LAMMPS"),
        DocQuery("dihedral_style", "opls", None, None, "OPLS dihedrals"),
    ),
    "reaxff": (
        DocQuery("pair_style", "reaxff", None, None, "ReaxFF pair_style"),
        DocQuery("fix", "qeq/reaxff", None, None, "charge equilibration"),
    ),
    "eam": (
        DocQuery("pair_style", "eam", None, None, "EAM metallic potentials"),
    ),
    "viscosity": (
        DocQuery("howto_topic", "viscosity", None, None, "viscosity calculation"),
    ),
    "thermal conductivity": (
        DocQuery("howto_topic", "kappa", None, None, "thermal conductivity"),
    ),
    "diffusion": (
        DocQuery("howto_topic", "diffusion", None, None, "diffusion coefficient"),
        DocQuery("compute", "msd", None, None, "mean-squared displacement"),
    ),
    "rdf": (
        DocQuery("compute", "rdf", None, None, "radial distribution"),
    ),
    "msd": (
        DocQuery("compute", "msd", None, None, "mean-squared displacement"),
    ),
    "shake": (
        DocQuery("fix", "shake", None, None, "constrain bonds/angles"),
    ),
    "rigid": (
        DocQuery("fix", "rigid", None, None, "rigid bodies"),
    ),
    "wall": (
        DocQuery("fix", "wall/lj93", None, None, "LJ 9-3 wall"),
        DocQuery("howto_topic", "walls", None, None, "wall protocols"),
    ),
    "nemd": (
        DocQuery("howto_topic", "nemd", None, None, "non-equilibrium MD"),
        DocQuery("fix", "nvt/sllod", None, None, "SLLOD integrator"),
    ),
    "shear": (
        DocQuery("fix", "deform", None, None, "shear via deform"),
        DocQuery("howto_topic", "nemd", None, None, "shear flow"),
    ),
    "2d": (
        DocQuery("howto_topic", "2d", None, None, "two-dimensional simulations"),
    ),
    "triclinic": (
        DocQuery("howto_topic", "triclinic", None, None, "non-orthogonal boxes"),
    ),
    "replica": (
        DocQuery("howto_topic", "replica", None, None, "replica-exchange"),
    ),
    "data file": (
        DocQuery("command", "read_data", None, None, "load system from data file"),
    ),
    "restart": (
        DocQuery("command", "read_restart", None, None, "resume from restart"),
        DocQuery("command", "write_restart", None, None, "write restart"),
        DocQuery("command", "restart", None, None, "periodic restart writing"),
    ),
}


WORKFLOW_KEYWORDS: dict[str, str] = {
    "npt": "npt",
    "nvt": "nvt",
    "nve": "nve",
    "minimize": "minimize",
    "minimization": "minimize",
    "energy minimization": "minimize",
    "deform": "deform",
    "deformation": "deform",
    "rerun": "rerun",
    "trajectory analysis": "rerun",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _hits(text: str) -> tuple[list[DocQuery], list[str], str | None]:
    norm = _normalize(text)
    seen: set[tuple[str, str | None, str | None]] = set()
    hits: list[DocQuery] = []
    matched_keywords: list[str] = []
    workflow: str | None = None
    # Multi-word keywords first to avoid prefix-stealing.
    for kw in sorted(KEYWORD_TO_QUERIES, key=lambda s: -len(s)):
        if kw in norm:
            matched_keywords.append(kw)
            for q in KEYWORD_TO_QUERIES[kw]:
                key = (q.kind, q.name, q.name_pattern)
                if key in seen:
                    continue
                seen.add(key)
                hits.append(q)
    for kw, wf in WORKFLOW_KEYWORDS.items():
        if kw in norm:
            workflow = wf
            break
    return hits, matched_keywords, workflow


def _unmatched_keywords(text: str, matched: list[str]) -> list[str]:
    # crude residual: words from the input not contained in any matched keyword
    norm = _normalize(text)
    residual = norm
    for kw in matched:
        residual = residual.replace(kw, " ")
    candidates = [
        w for w in re.findall(r"[a-z][a-z0-9/_\-]+", residual) if len(w) >= 4
    ]
    return sorted(set(candidates))


def plan(description: str, version: str = urls.DEFAULT_VERSION) -> dict:
    """Plan a free-text task into doc URLs + workflow tag."""
    urls._validate_version(version)
    queries, matched_kws, workflow = _hits(description)
    return {
        "task": description,
        "version": version,
        "matched_workflow": workflow,
        "matched_keywords": matched_kws,
        "doc_queries": [q.to_dict(version) for q in queries],
        "unmatched_keywords": _unmatched_keywords(description, matched_kws),
        "next_action": (
            "Fetch the doc URLs in order; if matched_workflow is set, "
            "combine with get_workflow_outline(matched_workflow)."
        ),
    }
