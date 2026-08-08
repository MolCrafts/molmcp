"""Turn a :class:`~.survey.Survey` into an editable adoption plan.

The plan is the operator's contract: every byte that will move, under which
``Project → Experiment → Run``, and every file that will **not** move with the
reason. It round-trips through plain dicts so an agent can hand it back edited
and ``run_adoption`` executes exactly what was approved — never a re-derived
mapping.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .survey import RUN, DirNode, Survey

#: Name used when a run has no enclosing experiment / project directory.
DEFAULT_NAME = "default"

#: Files whose contents seed a run's parameters, in preference order.
_PARAM_FILES: tuple[str, ...] = ("params.json", "parameters.json", "config.json")

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Lowercase ``a-z0-9-`` slug; empty input becomes ``DEFAULT_NAME``."""
    slug = _SLUG_STRIP.sub("-", name.strip().lower()).strip("-")
    return slug or DEFAULT_NAME


@dataclass(frozen=True, slots=True)
class RunPlan:
    """One source directory that becomes one molexp Run."""

    source: str
    run_id: str
    files: tuple[str, ...] = ()
    parameters: dict[str, Any] | None = None
    logs: tuple[str, ...] = ()
    has_metrics_buffer: bool = False

    @property
    def total_files(self) -> int:
        return len(self.files)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "run_id": self.run_id,
            "files": list(self.files),
            "parameters": dict(self.parameters) if self.parameters else {},
            "logs": list(self.logs),
            "has_metrics_buffer": self.has_metrics_buffer,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunPlan:
        return cls(
            source=str(payload["source"]),
            run_id=str(payload.get("run_id") or slugify(str(payload["source"]))),
            files=tuple(str(f) for f in payload.get("files", ())),
            parameters=dict(payload.get("parameters") or {}) or None,
            logs=tuple(str(f) for f in payload.get("logs", ())),
            has_metrics_buffer=bool(payload.get("has_metrics_buffer", False)),
        )


@dataclass(frozen=True, slots=True)
class ExperimentPlan:
    """One molexp Experiment and the runs beneath it."""

    name: str
    runs: tuple[RunPlan, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "runs": [run.to_dict() for run in self.runs]}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ExperimentPlan:
        return cls(
            name=str(payload["name"]),
            runs=tuple(RunPlan.from_dict(r) for r in payload.get("runs", ())),
        )


@dataclass(frozen=True, slots=True)
class ProjectPlan:
    """One molexp Project and the experiments beneath it."""

    name: str
    experiments: tuple[ExperimentPlan, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "experiments": [exp.to_dict() for exp in self.experiments],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProjectPlan:
        return cls(
            name=str(payload["name"]),
            experiments=tuple(
                ExperimentPlan.from_dict(e) for e in payload.get("experiments", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class SkippedPath:
    """A source path the plan will not adopt, and why."""

    path: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class AdoptionPlan:
    """The complete, editable proposal for one adoption."""

    source: str
    target: str
    projects: tuple[ProjectPlan, ...] = ()
    skipped: tuple[SkippedPath, ...] = ()
    conflicts: tuple[str, ...] = ()

    def iter_runs(self):
        """Yield ``(project, experiment, run)`` triples in stable order."""
        for project in self.projects:
            for experiment in project.experiments:
                for run in experiment.runs:
                    yield project, experiment, run

    @property
    def total_files(self) -> int:
        return sum(run.total_files for _, _, run in self.iter_runs())

    def to_dict(self) -> dict[str, Any]:
        runs = [run for _, _, run in self.iter_runs()]
        log_counts: dict[str, int] = {}
        for run in runs:
            for fmt in run.logs:
                log_counts[fmt] = log_counts.get(fmt, 0) + 1
        return {
            "source": self.source,
            "target": self.target,
            "counts": {
                "projects": len(self.projects),
                "experiments": sum(len(p.experiments) for p in self.projects),
                "runs": len(runs),
                "files": self.total_files,
            },
            "ingestible": {
                "by_format": log_counts,
                "runs_with_buffer": sum(1 for r in runs if r.has_metrics_buffer),
            },
            "projects": [project.to_dict() for project in self.projects],
            "skipped": [skip.to_dict() for skip in self.skipped],
            "conflicts": list(self.conflicts),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AdoptionPlan:
        """Rebuild a plan from an edited manifest. Conflicts are re-derived."""
        plan = cls(
            source=str(payload["source"]),
            target=str(payload["target"]),
            projects=tuple(
                ProjectPlan.from_dict(p) for p in payload.get("projects", ())
            ),
            skipped=tuple(
                SkippedPath(str(s["path"]), str(s.get("reason", "")))
                for s in payload.get("skipped", ())
            ),
        )
        return replace(plan, conflicts=find_conflicts(plan))


def default_target(source: Path | str) -> Path:
    """Sibling ``<source>.molexp/`` — never inside *source* itself."""
    root = Path(source).expanduser().resolve()
    return root.with_name(f"{root.name}.molexp")


def build_plan(
    survey: Survey,
    *,
    target: Path | str | None = None,
) -> AdoptionPlan:
    """Propose a four-tier mapping for every run candidate in *survey*.

    Runs keep their directory name as slug. The enclosing directories supply
    the experiment and project names; a run with no enclosing directory lands
    under ``default`` so it is adopted rather than dropped.
    """
    root = Path(survey.root)
    if target:
        target_root = Path(target).expanduser().resolve()
    else:
        target_root = default_target(root)

    by_rel = {node.rel: node for node in survey.nodes}
    adopted: set[str] = set()
    grouped: dict[tuple[str, str], list[RunPlan]] = {}
    order: list[tuple[str, str]] = []

    for node in survey.by_kind(RUN):
        project_name, experiment_name = _ancestor_names(node.rel, root)
        files = _run_files(node, survey)
        adopted.add(node.rel)
        adopted.update(_descendant_rels(node.rel, by_rel))
        run = RunPlan(
            source=node.rel,
            run_id=slugify(_leaf_name(node.rel, root)),
            files=files,
            parameters=_read_parameters(root, node),
            logs=tuple(sorted({hit.format for hit in node.logs})),
            has_metrics_buffer=node.has_metrics_buffer,
        )
        key = (project_name, experiment_name)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(run)

    projects: dict[str, list[ExperimentPlan]] = {}
    project_order: list[str] = []
    for project_name, experiment_name in order:
        members = grouped[(project_name, experiment_name)]
        runs = tuple(sorted(members, key=lambda r: r.source))
        if project_name not in projects:
            projects[project_name] = []
            project_order.append(project_name)
        projects[project_name].append(ExperimentPlan(name=experiment_name, runs=runs))

    plan = AdoptionPlan(
        source=str(root),
        target=str(target_root),
        projects=tuple(
            ProjectPlan(name=name, experiments=tuple(projects[name]))
            for name in project_order
        ),
        skipped=_skipped(survey, adopted),
    )
    return replace(plan, conflicts=find_conflicts(plan))


def find_conflicts(plan: AdoptionPlan) -> tuple[str, ...]:
    """Slug collisions and duplicate sources that must be resolved by hand."""
    problems: list[str] = []
    seen_sources: dict[str, str] = {}
    project_slugs: dict[str, str] = {}
    for project in plan.projects:
        slug = slugify(project.name)
        if slug in project_slugs and project_slugs[slug] != project.name:
            problems.append(
                f"project slug {slug!r} claimed by {project_slugs[slug]!r} "
                f"and {project.name!r}"
            )
        project_slugs[slug] = project.name
        experiment_slugs: dict[str, str] = {}
        for experiment in project.experiments:
            exp_slug = slugify(experiment.name)
            if (
                exp_slug in experiment_slugs
                and experiment_slugs[exp_slug] != experiment.name
            ):
                problems.append(
                    f"experiment slug {exp_slug!r} in project {project.name!r} "
                    f"claimed by {experiment_slugs[exp_slug]!r} and {experiment.name!r}"
                )
            experiment_slugs[exp_slug] = experiment.name
            run_ids: dict[str, str] = {}
            for run in experiment.runs:
                if run.run_id in run_ids and run_ids[run.run_id] != run.source:
                    problems.append(
                        f"run id {run.run_id!r} in {project.name}/{experiment.name} "
                        f"claimed by {run_ids[run.run_id]!r} and {run.source!r}"
                    )
                run_ids[run.run_id] = run.source
                for rel in run.files:
                    if rel in seen_sources and seen_sources[rel] != run.source:
                        problems.append(
                            f"file {rel!r} claimed by runs {seen_sources[rel]!r} "
                            f"and {run.source!r}"
                        )
                    seen_sources[rel] = run.source
    return tuple(dict.fromkeys(problems))


def _leaf_name(rel: str, root: Path) -> str:
    return rel.rsplit("/", 1)[-1] if rel else root.name


def _ancestor_names(rel: str, root: Path) -> tuple[str, str]:
    """``(project, experiment)`` names implied by a run's position.

    A run shallower than three levels borrows the source directory name for
    its project rather than a placeholder — ``results/r1`` reads better as
    project ``results`` than as project ``default``.
    """
    parts = rel.split("/") if rel else []
    experiment = parts[-2] if len(parts) >= 2 else DEFAULT_NAME
    project = parts[-3] if len(parts) >= 3 else root.name
    return project, experiment


def _descendant_rels(rel: str, by_rel: dict[str, DirNode]) -> set[str]:
    if not rel:
        return {other for other in by_rel if other}
    prefix = f"{rel}/"
    return {other for other in by_rel if other.startswith(prefix)}


def _run_files(node: DirNode, survey: Survey) -> tuple[str, ...]:
    """Every file under a run node, including its loose subdirectories."""
    prefix = f"{node.rel}/" if node.rel else ""
    files = [f.rel for f in node.files]
    for other in survey.nodes:
        if other.rel == node.rel:
            continue
        if prefix and not other.rel.startswith(prefix):
            continue
        if not prefix and not other.rel:
            continue
        files.extend(f.rel for f in other.files)
    return tuple(sorted(set(files)))


def _read_parameters(root: Path, node: DirNode) -> dict[str, Any] | None:
    """Lift ``params.json`` (or a sibling spelling) into the run's parameters."""
    names = {f.name: f.rel for f in node.files}
    for candidate in _PARAM_FILES:
        rel = names.get(candidate)
        if rel is None:
            continue
        try:
            payload = json.loads((root / rel).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None
    return None


def _skipped(survey: Survey, adopted: set[str]) -> tuple[SkippedPath, ...]:
    """Files outside every run, reported instead of silently dropped."""
    skipped: list[SkippedPath] = []
    for node in survey.nodes:
        if node.rel in adopted:
            continue
        for info in node.files:
            skipped.append(
                SkippedPath(info.rel, f"file in {node.kind} directory, outside any run")
            )
    for rel in survey.excluded:
        skipped.append(SkippedPath(rel, "excluded directory"))
    return tuple(sorted(skipped, key=lambda s: s.path))
