"""Canonical molexp workspace layout — the on-disk contract, read-only.

This module re-encodes the **frozen** four-tier ``Folder`` family invariant
documented in molexp's CLAUDE.md ("On-disk layout" / "Layout naming law"):
``Workspace → Project → Experiment → Run``. molexp is the source of truth;
this is a vetted mirror so an agent restructuring an arbitrary data
directory can, without writing a byte:

* read the spec (:func:`layout_spec`) — the tree, the four naming
  derivations, and the authoritative-vs-derived file classification; and
* lint a candidate directory (:func:`check_layout`) — conformance,
  concrete violations, and a heuristic project/experiment/run mapping it
  can hand to the ``mol:adopt-workspace`` skill (which owns the actual,
  integrity-checked migration).

The layout being mirrored is a *frozen* invariant, so drift risk is low;
``tests/providers/test_molexp_layout.py`` additionally asserts this
constant matches the live molexp classes whenever the real package is
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

# Bounds for the heuristic mapping of an arbitrary directory, so the tool
# can never return an unbounded payload (the response-limit middleware
# would otherwise truncate it opaquely). Exceeding any bound sets the
# ``truncated`` flag — never a silent cap.
_MAX_PROJECTS = 100
_MAX_EXPERIMENTS = 100
_MAX_RUNS = 200


@dataclass(frozen=True, slots=True)
class LayoutLevel:
    """One tier of the molexp Folder hierarchy and its naming derivations."""

    kind: str
    """Folder kind: ``workspace`` | ``project`` | ``experiment`` | ``run``."""

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


# The frozen contract. Order is the dependency chain root → leaf.
WORKSPACE_LAYOUT: tuple[LayoutLevel, ...] = (
    LayoutLevel(
        kind="workspace",
        container=None,
        dir_template=None,
        entity_file="workspace.json",
        children_index_file="project.json",
        child_kind="project",
        id_rule="workspace root directory; no id in the path",
    ),
    LayoutLevel(
        kind="project",
        container="projects",
        dir_template="<project_id>",
        entity_file="project.json",
        children_index_file="experiment.json",
        child_kind="experiment",
        id_rule="slug(name), kebab-case, no prefix",
    ),
    LayoutLevel(
        kind="experiment",
        container="experiments",
        dir_template="<experiment_id>",
        entity_file="experiment.json",
        children_index_file="run.json",
        child_kind="run",
        id_rule="slug(name) or explicit id, kebab-case, no prefix",
    ),
    LayoutLevel(
        kind="run",
        container="runs",
        dir_template="run-<run_id>",
        entity_file="run.json",
        children_index_file=None,
        child_kind=None,
        id_rule="8-char hex or content-addressed config_hash; dir is "
        "ALWAYS prefixed 'run-'",
    ),
)

# Files that are the single source of truth (never regenerated from elsewhere).
AUTHORITATIVE_FILES: tuple[dict[str, str], ...] = (
    {"path": "<level>/<entity_file>", "what": "per-node entity metadata"},
    {"path": "<scope>/assets.json", "what": "per-scope asset manifest"},
    {"path": "<scope>/library/references.json", "what": "molexp-native bib records"},
    {"path": "<scope>/library/notes/<slug>.md", "what": "NoteAsset files"},
)

# Files that are derived and rebuildable by scanning the authoritative ones.
DERIVED_FILES: tuple[dict[str, str], ...] = (
    {"path": "catalog/index.sqlite", "what": "workspace-wide asset catalog"},
    {"path": "<parent>/<child_index_file>", "what": "children index"},
    {"path": "<scope>/library/index.json", "what": "machine library index"},
    {"path": "<scope>/library/INDEX.md", "what": "human/agent library index"},
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
    "Entity *.json and per-scope assets.json are authoritative; every index "
    "(catalog/index.sqlite, children indexes, library/index.json, INDEX.md) "
    "is derived and rebuildable.",
    "Per-attempt state lives under runs/run-<id>/executions/<exec_id>/ "
    "(exec_id = 'exec-<run_id>' with an optional '-N' for reruns).",
)


def render_tree() -> str:
    """A compact ASCII rendering of the canonical workspace tree."""
    return (
        "workspace_root/\n"
        "├── workspace.json                # workspace entity metadata\n"
        "├── project.json                  # children index of projects (derived)\n"
        "├── assets.json                   # workspace-scoped asset manifest\n"
        "├── catalog/index.sqlite          # ws.catalog (derived)\n"
        "├── library/                      # per-scope notes + literature\n"
        "└── projects/<project_id>/        # container 'projects/', slug, no prefix\n"
        "    ├── project.json              # project entity metadata\n"
        "    ├── experiment.json           # children index of experiments (derived)\n"
        "    └── experiments/<experiment_id>/\n"
        "        ├── experiment.json       # experiment entity metadata\n"
        "        ├── run.json              # children index of runs (derived)\n"
        "        └── runs/run-<run_id>/    # 'run-' prefix is mandatory\n"
        "            ├── run.json          # run entity metadata\n"
        "            ├── assets.json       # run-scoped asset manifest\n"
        "            ├── artifacts/        # final products\n"
        "            ├── cache/            # per-run cache\n"
        "            └── executions/<exec_id>/   # exec-<run_id>[-N]\n"
    )


def layout_spec() -> dict[str, Any]:
    """Structured, self-contained molexp workspace-layout spec."""
    return {
        "summary": "Canonical molexp workspace on-disk layout (frozen "
        "four-tier Folder hierarchy). Restructure a directory to match this; "
        "the mol:adopt-workspace skill or molexp's Python API performs the "
        "actual, integrity-checked migration.",
        "hierarchy": ["workspace", "project", "experiment", "run"],
        "levels": [
            {
                "kind": lvl.kind,
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
        "authoritative_files": [dict(f) for f in AUTHORITATIVE_FILES],
        "derived_files": [dict(f) for f in DERIVED_FILES],
        "tree": render_tree(),
    }


@dataclass(slots=True)
class _Findings:
    violations: list[dict[str, str]] = field(default_factory=list)
    truncated: bool = False

    def add(self, path: Path, rule: str, detail: str) -> None:
        self.violations.append({"path": str(path), "rule": rule, "detail": detail})


def _is_slug(name: str) -> bool:
    return bool(_SLUG_RE.match(name))


def _child_dirs(parent: Path) -> list[Path]:
    """Sorted real subdirectories (no symlinks, no dotfiles)."""
    if not parent.is_dir():
        return []
    out = [
        p
        for p in sorted(parent.iterdir())
        if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")
    ]
    return out


def _validate_workspace(root: Path, found: _Findings) -> None:
    """Lint an existing molexp workspace against the naming law."""
    projects_dir = root / "projects"
    if not projects_dir.is_dir():
        return  # an empty workspace is conformant; nothing to walk
    for proj in _child_dirs(projects_dir):
        if not _is_slug(proj.name):
            found.add(proj, "project_dir_name", "project dir is not a kebab slug")
        if not (proj / "project.json").is_file():
            found.add(proj, "missing_entity_file", "missing project.json")
        exps_dir = proj / "experiments"
        for exp in _child_dirs(exps_dir):
            if not _is_slug(exp.name):
                found.add(exp, "experiment_dir_name", "experiment dir is not a slug")
            if not (exp / "experiment.json").is_file():
                found.add(exp, "missing_entity_file", "missing experiment.json")
            runs_dir = exp / "runs"
            for run in _child_dirs(runs_dir):
                if not run.name.startswith("run-"):
                    found.add(
                        run,
                        "run_prefix",
                        "run dir must be named 'run-<run_id>' (missing 'run-')",
                    )
                if not (run / "run.json").is_file():
                    found.add(run, "missing_entity_file", "missing run.json")


def _propose_mapping(root: Path) -> tuple[dict[str, Any], bool]:
    """Heuristic project/experiment/run mapping for an arbitrary directory.

    Depth-based and intentionally simple: top-level dirs become projects,
    their subdirs experiments, and the next level runs. It is a *suggestion*
    to seed an operator-reviewed migration, never an assertion of intent.
    """
    truncated = False
    projects: list[dict[str, Any]] = []
    for proj in _child_dirs(root):
        if len(projects) >= _MAX_PROJECTS:
            truncated = True
            break
        experiments: list[dict[str, Any]] = []
        for exp in _child_dirs(proj):
            if len(experiments) >= _MAX_EXPERIMENTS:
                truncated = True
                break
            runs: list[dict[str, str]] = []
            for run in _child_dirs(exp):
                if len(runs) >= _MAX_RUNS:
                    truncated = True
                    break
                runs.append({"source_dir": run.name, "target_dir": f"run-{run.name}"})
            experiments.append({"name": exp.name, "target_id": exp.name, "runs": runs})
        projects.append(
            {"name": proj.name, "target_id": proj.name, "experiments": experiments}
        )
    return {"projects": projects}, truncated


def check_layout(path: str | Path) -> dict[str, Any]:
    """Read-only conformance check + restructuring proposal for ``path``.

    Returns a single dict: whether ``path`` is already a molexp workspace,
    whether it conforms to the naming law, a list of concrete violations,
    and — for a directory that is not yet a workspace — a heuristic
    project/experiment/run mapping to feed an operator-reviewed migration.
    No filesystem writes occur.
    """
    root = Path(path)
    if not root.exists():
        return {
            "path": str(root),
            "exists": False,
            "is_workspace": False,
            "conforms": False,
            "violations": [
                {"path": str(root), "rule": "exists", "detail": "path does not exist"}
            ],
            "proposed_mapping": None,
            "truncated": False,
            "summary": "Path does not exist.",
        }
    if not root.is_dir():
        return {
            "path": str(root),
            "exists": True,
            "is_workspace": False,
            "conforms": False,
            "violations": [
                {
                    "path": str(root),
                    "rule": "is_dir",
                    "detail": "path is not a directory",
                }
            ],
            "proposed_mapping": None,
            "truncated": False,
            "summary": "Path is not a directory.",
        }

    found = _Findings()
    is_workspace = (root / "workspace.json").is_file()
    proposed: dict[str, Any] | None = None

    if is_workspace:
        _validate_workspace(root, found)
        conforms = not found.violations
        summary = (
            "Conforms to the molexp layout spec."
            if conforms
            else f"molexp workspace with {len(found.violations)} layout violation(s)."
        )
    else:
        found.add(
            root,
            "missing_workspace_json",
            "no workspace.json — not a molexp workspace; see proposed_mapping",
        )
        proposed, found.truncated = _propose_mapping(root)
        conforms = False
        n_proj = len(proposed["projects"])
        summary = (
            f"Not a molexp workspace. Proposed {n_proj} project(s) from "
            "directory structure; hand to mol:adopt-workspace to materialize."
        )

    return {
        "path": str(root),
        "exists": True,
        "is_workspace": is_workspace,
        "conforms": conforms,
        "violations": found.violations,
        "proposed_mapping": proposed,
        "truncated": found.truncated,
        "summary": summary,
    }
