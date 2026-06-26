"""Canonical molexp workspace layout — the on-disk contract, read-only.

This module re-encodes the **frozen** four-tier ``Folder`` family invariant
documented in molexp's CLAUDE.md ("On-disk layout" / "Layout naming law")
together with the **Open Knowledge Format (OKF)** concept model that molexp
now layers on top of it: ``Workspace → Project → Experiment → Run`` are OKF
Concepts, every concept directory carries a ``meta.yaml`` type marker and an
optional ``index.md`` narrative, and notes/literature are first-class OKF
Concepts (``Note`` / ``ReferenceConcept``) reached through the ``Bundle``
façade. molexp is the source of truth; this is a vetted mirror so an agent
restructuring an arbitrary data directory can, without writing a byte:

* read the spec (:func:`layout_spec`) — the tree, the naming derivations,
  the OKF concept markers, the knowledge concepts, and the
  authoritative-vs-derived file classification; and
* lint a candidate directory (:func:`validate_workspace`) — conformance and
  concrete violations, consumed by :mod:`.curate` to build the OKF curation
  plan it hands to the ``mol:adopt-workspace`` skill (which owns the actual,
  integrity-checked migration).

The layout being mirrored is a *frozen* invariant, so drift risk is low;
``tests/providers/test_molexp_layout.py`` additionally asserts these
constants match the live molexp classes whenever the real package is
installed. Mutating the on-disk tree is deliberately **not** offered here:
per molmcp's provider-design contract, file writes belong in the upstream
API / the migration skill, never an MCP tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Slug charset molexp uses for project/experiment ids (kebab-case). An
# approximation of molexp's ``slugify`` contract — good enough to flag an
# obviously non-conforming directory name, not to re-implement slugify.
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# OKF concept markers (every concept directory carries these). Names mirror
# molexp's ``workspace.folder`` constants (META_YAML_FILENAME / INDEX_FILENAME)
# and the ``_ops`` operational sidecar.
META_YAML = "meta.yaml"
INDEX_MD = "index.md"
OPS_DIR = "_ops"


@dataclass(frozen=True, slots=True)
class LayoutLevel:
    """One tier of the molexp Folder hierarchy and its naming derivations."""

    kind: str
    """Folder kind: ``workspace`` | ``project`` | ``experiment`` | ``run``."""

    concept_type: str
    """OKF concept ``type`` stamped in this level's ``meta.yaml`` (registry id)."""

    container: str | None
    """Parent-relative subdir holding this level's dirs (``None`` at root)."""

    dir_template: str | None
    """Directory-name template within ``container`` (``None`` at root)."""

    entity_file: str
    """Authoritative metadata filename in this level's own directory."""

    children_index_file: str | None
    """Derived children-index filename written in this level's directory."""

    child_kind: str | None
    """Kind of this level's children, or ``None`` for a leaf (run)."""

    id_rule: str
    """How this level's id is formed."""


# The frozen contract. Order is the dependency chain root → leaf. ``concept_type``
# mirrors molexp's WORKSPACE_*_KIND constants (workspace.folder).
WORKSPACE_LAYOUT: tuple[LayoutLevel, ...] = (
    LayoutLevel(
        kind="workspace",
        concept_type="workspace.root",
        container=None,
        dir_template=None,
        entity_file="workspace.json",
        children_index_file="project.json",
        child_kind="project",
        id_rule="workspace root directory; no id in the path",
    ),
    LayoutLevel(
        kind="project",
        concept_type="workspace.project",
        container="projects",
        dir_template="<project_id>",
        entity_file="project.json",
        children_index_file="experiment.json",
        child_kind="experiment",
        id_rule="slug(name), kebab-case, no prefix",
    ),
    LayoutLevel(
        kind="experiment",
        concept_type="workspace.experiment",
        container="experiments",
        dir_template="<experiment_id>",
        entity_file="experiment.json",
        children_index_file="run.json",
        child_kind="run",
        id_rule="slug(name) or explicit id, kebab-case, no prefix",
    ),
    LayoutLevel(
        kind="run",
        concept_type="workspace.run",
        container="runs",
        dir_template="run-<run_id>",
        entity_file="run.json",
        children_index_file=None,
        child_kind=None,
        id_rule="8-char hex or content-addressed config_hash; dir is "
        "ALWAYS prefixed 'run-'",
    ),
)

# OKF markers present in *every* concept directory (the four tiers above plus
# the knowledge concepts below). meta.yaml is mandatory and written eagerly;
# index.md is the additive narrative and appears only once content is added.
CONCEPT_MARKERS: tuple[dict[str, str], ...] = (
    {
        "path": "<concept>/meta.yaml",
        "what": "OKF concept type marker: the registered 'type' + 'id'. "
        "Mandatory — every concept dir has one.",
    },
    {
        "path": "<concept>/index.md",
        "what": "OKF narrative; its markdown links ARE the knowledge graph "
        "(the concept's out-edges). Additive — written when content/links exist.",
    },
)

# Notes & literature are OKF Concepts, NOT the removed per-scope library/.
# Each is a directory whose path is its identity, reached via the Bundle façade.
KNOWLEDGE_CONCEPTS: tuple[dict[str, str], ...] = (
    {
        "concept_type": "note.note",
        "class": "Note",
        "shape": "a concept dir with meta.yaml (type: note.note) + index.md "
        "(the note body); cite(ref) appends a markdown link → out-edge.",
    },
    {
        "concept_type": "reference.reference",
        "class": "ReferenceConcept",
        "shape": "a concept dir with meta.yaml carrying ReferenceMeta bib "
        "fields (title/authors/year/doi/venue/url/pdf_path/source/source_key) "
        "+ index.md (citation text). PDFs are POINTED-AT via pdf_path, never "
        "copied.",
    },
)

# Files that are the single source of truth (never regenerated from elsewhere).
AUTHORITATIVE_FILES: tuple[dict[str, str], ...] = (
    {"path": "<level>/<entity_file>", "what": "per-node entity metadata"},
    {"path": "<concept>/meta.yaml", "what": "OKF concept type marker (type + id)"},
    {"path": "<concept>/index.md", "what": "OKF narrative + markdown-link graph"},
    {"path": "<scope>/assets.json", "what": "per-scope asset manifest (lazy)"},
    {
        "path": "runs/run-<run_id>/_ops/run.json",
        "what": "run hot-state sidecar — status / ownership / heartbeat / "
        "executions; the read source for run status (lazy-created, not "
        "derivable from run.json)",
    },
)

# Files that are derived and rebuildable by scanning the authoritative ones.
DERIVED_FILES: tuple[dict[str, str], ...] = (
    {"path": "catalog/index.sqlite", "what": "workspace-wide asset catalog"},
    {"path": "<parent>/<child_index_file>", "what": "children index"},
    {"path": "<knowledge_bundle>/index.json", "what": "machine bundle index"},
    {"path": "<knowledge_bundle>/INDEX.md", "what": "human/agent bundle index"},
)

LAYOUT_RULES: tuple[str, ...] = (
    "Hierarchy is exactly four tiers: workspace > project > experiment > run.",
    "A level's children live under a container subdir named for the child "
    "kind pluralized: projects/, experiments/, runs/.",
    "Project and experiment directory names are the slugified id with NO "
    "prefix; a run directory is ALWAYS named 'run-<run_id>'.",
    "The entity metadata file is the level's own class name snake_case + "
    "'.json' (workspace.json / project.json / experiment.json / run.json).",
    "The children-index file in a parent dir is the CHILD class name "
    "snake_case + '.json'; same basename as the child's entity file but in "
    "the parent dir and a different role.",
    "Every concept directory carries an OKF meta.yaml (its registered 'type' "
    "+ 'id'); workspace/project/experiment/run map to types workspace.root / "
    "workspace.project / workspace.experiment / workspace.run.",
    "index.md is the optional OKF narrative whose markdown links ARE the "
    "knowledge graph (a concept's out-edges).",
    "Notes and literature are OKF Concepts (Note=note.note, "
    "ReferenceConcept=reference.reference) reached via the Bundle façade — "
    "directories whose path is their identity; PDFs are pointed-at via "
    "meta.yaml pdf_path, never copied. The legacy per-scope library/ "
    "subsystem was removed (wsokf-11).",
    "A run's hot operational state (status / ownership / heartbeat / "
    "executions) lives in its _ops/run.json sidecar — the read source — not "
    "in the run.json entity file.",
    "Entity *.json and per-scope assets.json + every meta.yaml/index.md are "
    "authoritative; every index (catalog/index.sqlite, children indexes, the "
    "knowledge bundle index.json/INDEX.md) is derived and rebuildable.",
    "Per-attempt state lives under runs/run-<id>/executions/<exec_id>/ "
    "(exec_id = 'exec-<run_id>' with an optional '-N' for reruns).",
)


def render_tree() -> str:
    """A compact ASCII rendering of the canonical OKF workspace tree."""
    return (
        "workspace_root/\n"
        "├── workspace.json          # entity metadata\n"
        "├── meta.yaml               # OKF marker (workspace.root)\n"
        "├── index.md                # OKF narrative; links = knowledge graph\n"
        "├── project.json            # children index (derived)\n"
        "├── catalog/index.sqlite    # ws.catalog (derived)\n"
        "├── <note>/                 # OKF Note (meta.yaml + index.md)\n"
        "├── <reference>/            # OKF Reference (meta.yaml + index.md)\n"
        "└── projects/<project_id>/  # 'projects/' container, slug, no prefix\n"
        "    ├── project.json        # project entity metadata\n"
        "    ├── meta.yaml           # OKF marker (workspace.project)\n"
        "    ├── experiment.json     # children index (derived)\n"
        "    └── experiments/<experiment_id>/\n"
        "        ├── experiment.json # experiment entity metadata\n"
        "        ├── meta.yaml       # OKF marker (workspace.experiment)\n"
        "        ├── run.json        # children index (derived)\n"
        "        └── runs/run-<run_id>/      # 'run-' prefix mandatory\n"
        "            ├── run.json    # run entity (identity/provenance)\n"
        "            ├── meta.yaml   # OKF marker (workspace.run)\n"
        "            ├── _ops/run.json       # hot-state (status/heartbeat)\n"
        "            ├── assets.json # run-scoped asset manifest\n"
        "            └── executions/<exec_id>/   # exec-<run_id>[-N]\n"
    )


def layout_spec() -> dict[str, Any]:
    """Structured, self-contained molexp workspace-layout spec."""
    return {
        "summary": "Canonical molexp workspace on-disk layout (frozen "
        "four-tier Folder hierarchy + OKF concept model). Restructure a "
        "directory to match this; the mol:adopt-workspace skill or molexp's "
        "Python API performs the actual, integrity-checked migration.",
        "hierarchy": ["workspace", "project", "experiment", "run"],
        "levels": [
            {
                "kind": lvl.kind,
                "concept_type": lvl.concept_type,
                "container": lvl.container,
                "dir_template": lvl.dir_template,
                "entity_file": lvl.entity_file,
                "children_index_file": lvl.children_index_file,
                "child_kind": lvl.child_kind,
                "id_rule": lvl.id_rule,
            }
            for lvl in WORKSPACE_LAYOUT
        ],
        "rules": list(LAYOUT_RULES),
        "concept_markers": [dict(m) for m in CONCEPT_MARKERS],
        "knowledge_concepts": [dict(c) for c in KNOWLEDGE_CONCEPTS],
        "authoritative_files": [dict(f) for f in AUTHORITATIVE_FILES],
        "derived_files": [dict(f) for f in DERIVED_FILES],
        "tree": render_tree(),
    }


@dataclass(slots=True)
class Findings:
    """Accumulator for conformance violations during a lint pass."""

    violations: list[dict[str, str]] = field(default_factory=list)
    truncated: bool = False

    def add(self, path: Path, rule: str, detail: str) -> None:
        self.violations.append({"path": str(path), "rule": rule, "detail": detail})


def is_slug(name: str) -> bool:
    return bool(_SLUG_RE.match(name))


def child_dirs(parent: Path) -> list[Path]:
    """Sorted real subdirectories (no symlinks, no dotfiles, no _ops)."""
    if not parent.is_dir():
        return []
    return [
        p
        for p in sorted(parent.iterdir())
        if p.is_dir()
        and not p.is_symlink()
        and not p.name.startswith(".")
        and p.name != OPS_DIR
    ]


def _require(dir_path: Path, *, entity_file: str, found: Findings) -> None:
    """Flag a concept dir missing its entity file or OKF meta.yaml marker."""
    if not (dir_path / entity_file).is_file():
        found.add(dir_path, "missing_entity_file", f"missing {entity_file}")
    if not (dir_path / META_YAML).is_file():
        found.add(
            dir_path,
            "missing_meta_yaml",
            f"missing OKF {META_YAML} concept marker (type + id)",
        )


def validate_workspace(root: Path, found: Findings) -> None:
    """Lint an existing molexp workspace against the naming + OKF laws.

    Checks the mandatory, eagerly-written files only — entity ``*.json`` and
    the OKF ``meta.yaml`` marker at every tier. ``index.md``, ``_ops/run.json``
    and ``assets.json`` are additive/lazy and their absence is NOT a violation.
    """
    if not (root / META_YAML).is_file():
        found.add(
            root,
            "missing_meta_yaml",
            f"workspace root missing OKF {META_YAML} (type: workspace.root)",
        )
    projects_dir = root / "projects"
    if not projects_dir.is_dir():
        return  # an empty workspace is conformant; nothing to walk
    for proj in child_dirs(projects_dir):
        if not is_slug(proj.name):
            found.add(proj, "project_dir_name", "project dir is not a kebab slug")
        _require(proj, entity_file="project.json", found=found)
        for exp in child_dirs(proj / "experiments"):
            if not is_slug(exp.name):
                found.add(exp, "experiment_dir_name", "experiment dir is not a slug")
            _require(exp, entity_file="experiment.json", found=found)
            for run in child_dirs(exp / "runs"):
                if not run.name.startswith("run-"):
                    found.add(
                        run,
                        "run_prefix",
                        "run dir must be named 'run-<run_id>' (missing 'run-')",
                    )
                _require(run, entity_file="run.json", found=found)
