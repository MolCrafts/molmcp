"""Canonical molexp workspace layout — the on-disk contract, read-only.

Re-encodes the frozen four-tier ``Folder`` family invariant from molexp's
CLAUDE.md for agent-facing layout queries and lint. Not a migration tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

META_YAML = "meta.yaml"
INDEX_MD = "index.md"
OPS_DIR = "_ops"


@dataclass(frozen=True)
class LayoutLevel:
    kind: str
    concept_type: str
    container: str
    dir_template: str
    entity_file: str
    children_index_file: str
    child_kind: str
    id_rule: str


WORKSPACE_LAYOUT: tuple[LayoutLevel, ...] = (
    LayoutLevel(
        kind="workspace",
        concept_type="workspace.workspace",
        container="",
        dir_template=".",
        entity_file="workspace.json",
        children_index_file="project.json",
        child_kind="project",
        id_rule="workspace root directory; no id in the path",
    ),
    LayoutLevel(
        kind="project",
        concept_type="workspace.project",
        container="projects",
        dir_template="projects/<project_id>",
        entity_file="project.json",
        children_index_file="experiment.json",
        child_kind="experiment",
        id_rule="slug(name), kebab-case, no prefix",
    ),
    LayoutLevel(
        kind="experiment",
        concept_type="workspace.experiment",
        container="experiments",
        dir_template="projects/<project_id>/experiments/<experiment_id>",
        entity_file="experiment.json",
        children_index_file="run.json",
        child_kind="run",
        id_rule="slug(name) or explicit id, kebab-case, no prefix",
    ),
    LayoutLevel(
        kind="run",
        concept_type="workspace.run",
        container="runs",
        dir_template="projects/<project_id>/experiments/<experiment_id>/runs/run-<run_id>",
        entity_file="run.json",
        children_index_file="",
        child_kind="",
        id_rule=(
            "8-char hex or content-addressed config_hash; dir ALWAYS prefixed 'run-'"
        ),
    ),
)

LAYOUT_RULES: tuple[str, ...] = (
    "Container subdir is the child kind pluralized: projects/, experiments/, runs/.",
    "Project/Experiment dir names are slugified ids with no prefix.",
    "Run dirs are always prefixed run- under runs/.",
    "Entity metadata filename is the level's class name snake_case + .json.",
    "Children-index filename in a parent is the *child* class name snake_case + .json.",
    "Every concept dir has meta.yaml with a registered type.",
    "Run hot state lives in _ops/run.json (not in the run.json entity file).",
)


def is_slug(name: str) -> bool:
    return bool(_SLUG_RE.match(name))


def render_tree() -> str:
    """Human-readable layout tree for agent display."""
    return (
        "workspace_root/\n"
        "├── workspace.json\n"
        "├── project.json              # children INDEX of projects (derived)\n"
        "├── meta.yaml\n"
        "└── projects/<project_id>/\n"
        "    ├── project.json\n"
        "    ├── experiment.json       # children INDEX\n"
        "    └── experiments/<experiment_id>/\n"
        "        ├── experiment.json\n"
        "        ├── run.json          # children INDEX\n"
        "        └── runs/run-<run_id>/\n"
        "            ├── run.json\n"
        "            ├── meta.yaml\n"
        "            └── _ops/run.json\n"
    )


def layout_spec() -> dict[str, Any]:
    """Structured, self-contained molexp workspace-layout spec."""
    levels = [
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
    ]
    return {
        "summary": (
            "Canonical molexp workspace on-disk layout (frozen four-tier Folder "
            "hierarchy + OKF concept model). Scaffold with molexp Python API or "
            "the MCP scaffold tools; integrity-checked migration uses "
            "mol:adopt-workspace."
        ),
        "levels": levels,
        "rules": list(LAYOUT_RULES),
        "tree": render_tree(),
        "concept_markers": [META_YAML, INDEX_MD],
        "run_ops_sidecar": f"runs/run-<run_id>/{OPS_DIR}/run.json",
    }


def child_dirs(parent: Path) -> list[Path]:
    if not parent.is_dir():
        return []
    return sorted(
        p for p in parent.iterdir() if p.is_dir() and not p.name.startswith(".")
    )


def validate_workspace(root: Path) -> dict[str, Any]:
    """Lint *root* via molexp's layout checker; return the agent-facing report.

    Thin wrapper around :func:`molexp.workspace.validate_workspace`. The MCP
    tool of the same name (``validate_workspace``) returns this dict so an
    agent can see which errors need fixing.
    """
    from molexp.workspace import validate_workspace as _molexp_validate

    return _molexp_validate(Path(root)).to_dict()
