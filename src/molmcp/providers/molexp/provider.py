"""``molexp`` MCP provider — workspace navigation, scaffold, and adoption.

**Not a science executor.** Scaffold tools create-or-get workspace tree
nodes (materialize / add project / add experiment / seed a pending run).
Layout tools are read-only. Full parameter sweeps, workflow runtime
driving, harvest, and plotting stay in agent-written Python against
the molexp / molplot APIs (see molexp ``examples/agent/code_loop_golden_path.py``).

Adoption (``plan_adoption`` / ``run_adoption`` / ``adoption_status`` /
``ingest_metrics``) lifts a legacy data directory into the four-tier layout
with per-file SHA-256 proof and a resumable ledger — see ``adopt/``. Deleting
the original source is deliberately not a tool.

Provider-design contract:
- Navigation / layout: read-only.
- Scaffold creates: idempotent create-or-get (not arbitrary mutation).
- Adoption writes only under the target workspace; ``move`` unlinks a source
  file only after its copy verified.
- Never drive run batches or invoke workflow runtime from this package.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP

#: Settings key holding the default workspace path.
_WORKSPACE_SETTING = "molexp.workspace"


def _configured_workspace() -> str:
    """Default workspace from settings, or empty when unset."""
    from molmcp.settings import load_settings

    return str(load_settings(Path.cwd()).molexp.get("workspace", "")).strip()


_ALLOWED_SCOPES = frozenset({"workspace", "project", "experiment"})

#: Marker files that identify a directory as a molexp workspace root.
_WORKSPACE_MARKERS = ("workspace.json", "meta.yaml")


def _csv_mapping(step_column: str | None, series_columns: list[str] | None):
    """Build molexp's ``ColumnMapping``, or ``None`` when CSV was not mapped.

    Without a mapping CSV artifacts are skipped with a reason rather than
    guessed — a table of coordinates and a table of training curves look
    identical to a heuristic.
    """
    if step_column is None and not series_columns:
        return None
    from molexp.plugins.metrics_ingest import ColumnMapping

    return ColumnMapping(
        step_column=step_column,
        series_columns=tuple(series_columns or ()),
    )


def _open_workspace(path: str | Path):
    from molexp.workspace import Workspace

    return Workspace(Path(path).expanduser().resolve())


def _resolve_workspace(workspace: str | None = None):
    from molexp.workspace import Workspace

    if workspace:
        return Workspace(Path(workspace).expanduser().resolve())
    configured = _configured_workspace()
    if configured:
        return Workspace(Path(configured).expanduser().resolve())
    cwd = Path.cwd()
    if (cwd / "workspace.json").is_file() or (cwd / "meta.yaml").is_file():
        return Workspace(cwd)
    raise RuntimeError(
        "MolexpProvider could not resolve a workspace. Pass workspace= path, "
        "run `molmcp config set molexp.workspace <path>`, or run from a "
        "directory containing workspace.json."
    )


class MolexpProvider:
    """Provider for molexp domain tools (scaffold + navigation)."""

    name = "molexp"

    def __init__(self, workspace: str | Path | None = None) -> None:
        self._workspace = Path(workspace).expanduser().resolve() if workspace else None

    @staticmethod
    def probe() -> bool:
        """True when the optional ``molexp`` package is importable."""
        try:
            import molexp  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_workspace(self, workspace: str | None = None):
        if workspace:
            return _open_workspace(workspace)
        if self._workspace is not None:
            return _open_workspace(self._workspace)
        return _resolve_workspace(None)

    @staticmethod
    def _ingest_targets(root: Path) -> list[Path]:
        """Run directories under *root* — or *root* itself when it is a run.

        A workspace root fans out to every run beneath it; anything else is
        taken at face value, so a bare run directory works without the caller
        having to know which it handed over.
        """
        if not any((root / marker).is_file() for marker in _WORKSPACE_MARKERS):
            return [root]
        workspace = _open_workspace(root)
        runs: list[Path] = []
        for project in workspace.list_projects():
            for experiment in project.list_experiments():
                runs.extend(Path(run.resolve()) for run in experiment.list_runs())
        return runs

    def register(self, mcp: FastMCP) -> None:
        if not self.probe():
            raise RuntimeError(
                "MolexpProvider requires molexp to be installed in this environment"
            )

        from mcp.types import ToolAnnotations

        read_only = ToolAnnotations(read_only_hint=True, destructive_hint=False)
        # Idempotent scaffold (create-or-get) — not a free-form write surface.
        scaffold = ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
        )
        # Adoption re-run resumes rather than duplicates, but ``move`` unlinks
        # source files, so the destructive hint stays on.
        adoption = ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
        )
        # metrics.jsonl is append-only: a second ingest doubles the curves.
        ingest_annotation = ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
        )

        @mcp.tool(annotations=read_only)
        def list_projects(workspace: str | None = None) -> list[dict[str, Any]]:
            """Enumerate projects in the workspace."""
            ws = self._get_workspace(workspace)
            rows: list[dict[str, Any]] = []
            for p in ws.list_projects():
                rows.append(
                    {
                        "project_id": p.id,
                        "name": p.name,
                        "path": str(p.resolve()),
                    }
                )
            return rows

        @mcp.tool(annotations=read_only)
        def list_experiments(
            project_id: str,
            workspace: str | None = None,
        ) -> list[dict[str, Any]]:
            """List experiments under a project (read-only)."""
            from .scaffold import list_experiments as _list_experiments

            ws = self._get_workspace(workspace)
            return _list_experiments(ws.resolve(), project_id)

        @mcp.tool(annotations=read_only)
        def list_runs(
            scope_kind: Literal["workspace", "project", "experiment"] = "workspace",
            scope_id: str = "",
            status: str | None = None,
            limit: int = 500,
            workspace: str | None = None,
        ) -> list[dict[str, Any]]:
            """Query runs by scope.

            Args:
                scope_kind: ``workspace``, ``project``, or ``experiment``.
                scope_id: Project id (when ``scope_kind='project'``),
                    experiment id (when ``'experiment'``), or empty string
                    (when ``'workspace'``).
                status: Optional status filter.
                limit: Maximum rows to return. Default 500.
            """
            if scope_kind not in _ALLOWED_SCOPES:
                raise ValueError(f"scope_kind must be one of {sorted(_ALLOWED_SCOPES)}")
            ws = self._get_workspace(workspace)
            rows: list[dict[str, Any]] = []
            projects = ws.list_projects()
            if scope_kind == "project":
                projects = [ws.get_project(scope_id)]
            for project in projects:
                experiments = project.list_experiments()
                if scope_kind == "experiment":
                    experiments = [
                        e for e in experiments if e.id == scope_id or e.name == scope_id
                    ]
                for exp in experiments:
                    for run in exp.list_runs():
                        if status is not None and run.status != status:
                            continue
                        rows.append(
                            {
                                "run_id": run.id,
                                "project_id": project.id,
                                "experiment_id": exp.id,
                                "status": run.status,
                                "params": dict(run.parameters),
                            }
                        )
                        if len(rows) >= limit:
                            return rows
            return rows

        @mcp.tool(annotations=read_only)
        def workspace_layout() -> dict[str, Any]:
            """Canonical molexp workspace on-disk layout contract (OKF)."""
            from .layout import layout_spec

            return layout_spec()

        @mcp.tool(annotations=read_only)
        def check_layout(path: str) -> dict[str, Any]:
            """Read-only lint of ``path`` against the layout contract."""
            from .layout import validate_workspace

            root = Path(path).expanduser().resolve()
            findings = validate_workspace(root)
            is_ws = (root / "workspace.json").is_file() or (
                root / "meta.yaml"
            ).is_file()
            return {
                "path": str(root),
                "is_workspace": is_ws,
                "ok": len(findings.items) == 0 and is_ws,
                "violations": findings.items,
            }

        def _scaffold_result(fn, *args: Any, **kwargs: Any) -> dict[str, Any]:
            """Run a scaffold helper; return structured errors instead of tracebacks."""
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — surface to the agent cleanly
                return {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }

        @mcp.tool(annotations=scaffold)
        def materialize_workspace(
            path: str,
            name: str = "workspace",
        ) -> dict[str, Any]:
            """Create or open a top-level molexp Workspace at ``path`` (idempotent).

            Do **not** use this to create a project under the session workspace —
            use ``add_project`` instead. Nesting is rejected.
            """
            from .scaffold import materialize_workspace as _materialize_workspace

            return _scaffold_result(_materialize_workspace, path, name=name)

        @mcp.tool(annotations=scaffold)
        def add_project(
            name: str,
            workspace: str | None = None,
        ) -> dict[str, Any]:
            """Create-or-get a project under the workspace (idempotent on slug).

            Prefer this (or omit workspace to use MOLEXP_WORKSPACE) when the user
            asks to create a project.
            """
            from .scaffold import add_project as _add_project

            ws = self._get_workspace(workspace)
            return _scaffold_result(_add_project, ws.resolve(), name)

        @mcp.tool(annotations=scaffold)
        def add_experiment(
            project_id: str,
            name: str,
            workspace: str | None = None,
        ) -> dict[str, Any]:
            """Create-or-get an experiment under a project (idempotent on slug)."""
            from .scaffold import add_experiment as _add_experiment

            ws = self._get_workspace(workspace)
            return _scaffold_result(_add_experiment, ws.resolve(), project_id, name)

        @mcp.tool(annotations=scaffold)
        def create_run(
            project_id: str,
            experiment_id: str,
            params: dict[str, Any] | None = None,
            workspace: str | None = None,
        ) -> dict[str, Any]:
            """Scaffold a pending run with params — does not drive the workflow."""
            from .scaffold import create_run as _create_run

            ws = self._get_workspace(workspace)
            return _scaffold_result(
                _create_run, ws.resolve(), project_id, experiment_id, params=params
            )

        # ------------------------------------------------------------------
        # Adoption: legacy data directory → four-tier workspace
        # ------------------------------------------------------------------

        @mcp.tool(annotations=read_only)
        def plan_adoption(
            source: str,
            target: str | None = None,
            max_depth: int = 6,
        ) -> dict[str, Any]:
            """Survey a legacy data directory and propose an adoption mapping.

            Read-only: nothing is created, copied, or written. Returns the
            survey (what is there, plus oddities like broken symlinks) and a
            ``Project → Experiment → Run`` proposal the operator can edit and
            hand straight back to ``run_adoption(plan=…)``.

            Args:
                source: The existing data directory.
                target: Where the workspace will live. Defaults to a sibling
                    ``<source>.molexp/``.
                max_depth: Levels below *source* to walk. Default 6.

            Returns:
                ``{ok, survey, plan}``. A non-empty ``plan.conflicts`` must be
                resolved by editing the plan before it can run.
            """
            from .adopt import build_plan, survey_source

            root = Path(source).expanduser().resolve()
            try:
                found = survey_source(root, max_depth=max_depth)
            except NotADirectoryError as exc:
                return {"ok": False, "error": str(exc)}
            proposal = build_plan(found, target=target)
            return {
                "ok": not proposal.conflicts,
                "survey": found.to_dict(),
                "plan": proposal.to_dict(),
            }

        @mcp.tool(annotations=adoption)
        def run_adoption(
            source: str,
            target: str | None = None,
            mode: Literal["copy", "move"] = "copy",
            plan: dict[str, Any] | None = None,
            ingest: list[str] | None = None,
            csv_step_column: str | None = None,
            csv_series_columns: list[str] | None = None,
            workspace_name: str | None = None,
        ) -> dict[str, Any]:
            """Execute an adoption: materialize, transfer, ingest, verify.

            Every file is SHA-256 hashed on write and re-read before its
            ledger entry flips. An existing destination with different bytes
            is refused, never overwritten. Re-running with the same arguments
            resumes from ``<target>/.molexp-migration.json``.

            Deleting the source is **not** offered here — audit the ledger and
            remove the original yourself.

            Args:
                source: The existing data directory.
                target: Workspace root. Defaults to ``<source>.molexp/``.
                mode: ``copy`` leaves the source intact; ``move`` unlinks each
                    source file only after its copy verified.
                plan: An edited plan from ``plan_adoption``. Omit to use the
                    freshly derived proposal.
                ingest: Log formats to convert into each run's metrics buffer
                    (``lammps_log``, ``tensorboard``, ``csv``). Omit to ingest
                    nothing — the buffer is append-only, so this is never
                    implied.
                csv_step_column: Step column for CSV ingestion.
                csv_series_columns: Series columns for CSV ingestion.
                workspace_name: Name for the workspace. Defaults to the target
                    directory name.
            """
            from .adopt import (
                AdoptionBlocked,
                AdoptionPlan,
                build_plan,
                survey_source,
            )
            from .adopt import run_adoption as _run_adoption

            root = Path(source).expanduser().resolve()
            try:
                if plan is not None:
                    approved = AdoptionPlan.from_dict(plan)
                else:
                    approved = build_plan(survey_source(root), target=target)
                outcome = _run_adoption(
                    approved,
                    mode=mode,
                    ingest_formats=frozenset(ingest) if ingest else None,
                    csv_mapping=_csv_mapping(csv_step_column, csv_series_columns),
                    workspace_name=workspace_name,
                )
            except (AdoptionBlocked, NotADirectoryError, KeyError) as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            return outcome.to_dict()

        @mcp.tool(annotations=read_only)
        def adoption_status(target: str, verify: bool = False) -> dict[str, Any]:
            """Read an adoption ledger: what is done, what is outstanding.

            Args:
                target: The workspace root holding
                    ``.molexp-migration.json``.
                verify: Re-hash every transferred file and report divergence.
                    Off by default — it re-reads the whole workspace. Turn it
                    on for the deliberate audit before deleting a source.
            """
            from .adopt import read_ledger, verify_tree

            root = Path(target).expanduser().resolve()
            try:
                ledger = read_ledger(root)
            except (OSError, ValueError) as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            if ledger is None:
                return {
                    "ok": False,
                    "error": f"no adoption ledger under {root}",
                    "target": str(root),
                }
            outstanding = [
                entry.source
                for entry in ledger.entries
                if entry.kind == "file" and not entry.done
            ]
            payload: dict[str, Any] = {
                "ok": True,
                "source": ledger.source,
                "target": ledger.target,
                "mode": ledger.mode,
                "complete": ledger.complete,
                "counts": ledger.counts(),
                "runs": [
                    {
                        "source": entry.source,
                        "run_id": entry.run_id,
                        "run_dir": entry.target,
                    }
                    for entry in ledger.of_kind("run")
                ],
                "outstanding": outstanding[:50],
                "outstanding_total": len(outstanding),
            }
            if verify:
                pairs = [
                    (Path(entry.target), entry.sha256 or "")
                    for entry in ledger.entries
                    if entry.kind == "file" and entry.done
                ]
                problems = verify_tree(pairs)
                payload["verified_files"] = len(pairs)
                payload["problems"] = problems
                payload["ok"] = not problems
            return payload

        @mcp.tool(annotations=ingest_annotation)
        def ingest_metrics(
            path: str,
            formats: list[str] | None = None,
            csv_step_column: str | None = None,
            csv_series_columns: list[str] | None = None,
        ) -> dict[str, Any]:
            """Convert a run's foreign logs into its host metrics buffer.

            Additive and **not idempotent**: ``metrics/metrics.jsonl`` is
            append-only, so ingesting the same run twice doubles its curves.
            Undo by deleting ``<run>/metrics/``. Source logs are never
            deleted, rewritten, moved, or truncated.

            Args:
                path: A run directory, or a workspace root to ingest every run
                    under it.
                formats: ``lammps_log`` / ``tensorboard`` / ``csv``. Omit to
                    ingest every format that has a converter (CSV only when a
                    column mapping is given).
                csv_step_column: Step column name for CSV artifacts.
                csv_series_columns: Series column names for CSV artifacts.
            """
            from .adopt import INGEST_FORMATS, molexp_ingest

            selected = frozenset(formats) if formats else None
            if selected is not None:
                unknown = sorted(selected - INGEST_FORMATS)
                if unknown:
                    return {
                        "ok": False,
                        "error": (
                            f"unknown format(s) {unknown}; "
                            f"expected {sorted(INGEST_FORMATS)}"
                        ),
                    }
            root = Path(path).expanduser().resolve()
            if not root.is_dir():
                return {"ok": False, "error": f"not a directory: {root}"}
            mapping = _csv_mapping(csv_step_column, csv_series_columns)
            targets = self._ingest_targets(root)
            results: dict[str, Any] = {}
            problems: list[str] = []
            for run_dir in targets:
                try:
                    outcome = molexp_ingest(run_dir, selected, mapping)
                except Exception as exc:  # noqa: BLE001 — report, never crash
                    problems.append(f"{run_dir}: {type(exc).__name__}: {exc}")
                    continue
                results[str(run_dir)] = outcome.to_dict()
            return {
                "ok": not problems,
                "path": str(root),
                "runs": len(targets),
                "results": results,
                "problems": problems,
            }

        @mcp.tool(annotations=read_only)
        def validate_workflow(source: str) -> dict[str, Any]:
            """Compile-only validation of workflow source (no task bodies run).

            Provide a Python snippet that builds a ``WorkflowCompiler`` as
            ``wf`` (or any ``WorkflowCompiler`` instance) with ``@wf.task``
            registrations. Returns ok/compiled without running science.
            """
            from .scaffold import validate_workflow_source

            return validate_workflow_source(source)
