"""Execute an approved :class:`~.plan.AdoptionPlan`.

Order is fixed and journaled: materialize the workspace tree → write the full
ledger → transfer every file with SHA-256 verification → ingest the approved
log formats → re-verify. A failure at any point leaves the source intact
(copy mode) and the ledger readable, so re-running resumes instead of
restarting.

molexp is reached through two injectable seams — a workspace factory and an
ingest function — so the orchestration is testable without the science stack
installed, exactly like the molvis provider's stage factory.

**Deleting the source is not a tool.** The bytes are verified and the ledger
says so; removing the original is an irreversible operator decision made
outside MCP.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from .ledger import (
    FAILED,
    LEDGER_NAME,
    MOVED,
    PENDING,
    SKIPPED,
    VERIFIED,
    Entry,
    Ledger,
    ensure_compatible,
    read_ledger,
    resume_or_create,
    write_error_report,
    write_ledger,
)
from .plan import AdoptionPlan, RunPlan
from .transfer import COPY, MODES, TransferError, transfer_file, verify_present

#: Sub-directory of a run that holds adopted source files.
ARTIFACTS_DIR = "artifacts"

#: Log formats an ingest may be asked for, as agent-facing strings.
INGEST_FORMATS: frozenset[str] = frozenset({"lammps_log", "tensorboard", "csv"})

#: Files transferred between ledger checkpoints.
LEDGER_FLUSH_EVERY = 25


@dataclass(frozen=True, slots=True)
class RunSlot:
    """A materialized molexp Run and where its artifacts go."""

    project_id: str
    experiment_id: str
    run_id: str
    run_dir: Path


class WorkspaceHandle(Protocol):
    """The slice of molexp's workspace API an adoption needs."""

    def ensure_project(self, name: str) -> str: ...

    def ensure_experiment(self, project_id: str, name: str) -> str: ...

    def ensure_run(
        self, project_id: str, experiment_id: str, params: dict[str, Any] | None
    ) -> RunSlot: ...


#: ``(target_root, workspace_name) -> WorkspaceHandle``
WorkspaceFactory = Callable[[Path, str], WorkspaceHandle]


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    """Per-run ingest result, flattened out of molexp's ``IngestResult``."""

    ingested: dict[str, int] = field(default_factory=dict)
    skipped: tuple[tuple[str, str, str], ...] = ()

    @property
    def records(self) -> int:
        return sum(self.ingested.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "ingested": dict(self.ingested),
            "records": self.records,
            "skipped": [
                {"format": fmt, "path": path, "reason": reason}
                for fmt, path, reason in self.skipped
            ],
        }


#: ``(run_dir, formats, csv_mapping) -> IngestOutcome``
IngestFn = Callable[[Path, frozenset[str] | None, Any], IngestOutcome]


@dataclass(frozen=True, slots=True)
class AdoptionOutcome:
    """Everything one ``run_adoption`` call did."""

    ok: bool
    source: str
    target: str
    mode: str
    ledger_path: str
    files_transferred: int
    files_reused: int
    bytes_transferred: int
    runs: tuple[dict[str, Any], ...] = ()
    ingest: dict[str, dict[str, Any]] = field(default_factory=dict)
    problems: tuple[str, ...] = ()
    skipped: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "source": self.source,
            "target": self.target,
            "mode": self.mode,
            "ledger": self.ledger_path,
            "files_transferred": self.files_transferred,
            "files_reused": self.files_reused,
            "bytes_transferred": self.bytes_transferred,
            "runs": list(self.runs),
            "ingest": dict(self.ingest),
            "problems": list(self.problems),
            "skipped": list(self.skipped),
            "source_intact": self.mode == COPY,
            "note": (
                "Source files are untouched; delete the original yourself once "
                "you have audited the ledger."
                if self.mode == COPY
                else "Move mode unlinked each source file only after its copy "
                "verified; the ledger records which."
            ),
        }


class AdoptionBlocked(RuntimeError):
    """A precondition failed — nothing was written."""


def molexp_workspace_factory(target: Path, name: str) -> WorkspaceHandle:
    """Default handle backed by molexp's public ``Workspace`` API."""
    from molexp.workspace import Workspace

    target.mkdir(parents=True, exist_ok=True)
    workspace = Workspace(target, name=name)
    workspace.materialize()
    return _MolexpWorkspace(workspace)


@dataclass(frozen=True, slots=True)
class _MolexpWorkspace:
    """Adapter over ``molexp.workspace.Workspace`` (create-or-get only)."""

    workspace: Any

    def ensure_project(self, name: str) -> str:
        return self.workspace.add_project(name).id

    def ensure_experiment(self, project_id: str, name: str) -> str:
        project = self.workspace.get_project(project_id)
        return project.add_experiment(name).id

    def ensure_run(
        self, project_id: str, experiment_id: str, params: dict[str, Any] | None
    ) -> RunSlot:
        project = self.workspace.get_project(project_id)
        experiment = project.get_experiment(experiment_id)
        run = experiment.add_run(params=params or {})
        return RunSlot(
            project_id=project_id,
            experiment_id=experiment_id,
            run_id=run.id,
            run_dir=Path(run.resolve()),
        )


def molexp_ingest(
    run_dir: Path,
    formats: frozenset[str] | None,
    csv_mapping: Any = None,
) -> IngestOutcome:
    """Default ingest: one call into ``molexp.plugins.metrics_ingest``."""
    from molexp.plugins.metrics_ingest import LogFormat, ingest_run

    selected = None
    if formats is not None:
        selected = {LogFormat(fmt) for fmt in formats}
    result = ingest_run(run_dir, formats=selected, csv_mapping=csv_mapping)
    return IngestOutcome(
        ingested={str(fmt): count for fmt, count in result.ingested.items()},
        skipped=tuple(
            (str(skip.format), str(skip.path), skip.reason) for skip in result.skipped
        ),
    )


def check_preconditions(source: Path, target: Path, mode: str) -> None:
    """Refuse anything that could destroy or duplicate data. Never writes."""
    if mode not in MODES:
        raise AdoptionBlocked(f"mode must be one of {sorted(MODES)}, got {mode!r}")
    if not source.is_dir():
        raise AdoptionBlocked(f"source is not a directory: {source}")
    if (source / "workspace.json").is_file():
        raise AdoptionBlocked(
            f"{source} is already a molexp workspace. Copying a workspace is "
            "`cp -a`, not an adoption; to add metrics to it call ingest_metrics."
        )
    if target == source:
        raise AdoptionBlocked("target and source are the same directory")
    if source in target.parents:
        raise AdoptionBlocked(f"target {target} is inside source {source}")
    if target in source.parents:
        raise AdoptionBlocked(f"source {source} is inside target {target}")
    if not target.parent.exists():
        raise AdoptionBlocked(f"target parent does not exist: {target.parent}")


def run_adoption(
    plan: AdoptionPlan,
    *,
    mode: str = COPY,
    ingest_formats: frozenset[str] | None = None,
    csv_mapping: Any = None,
    workspace_name: str | None = None,
    workspace_factory: WorkspaceFactory = molexp_workspace_factory,
    ingest: IngestFn = molexp_ingest,
) -> AdoptionOutcome:
    """Materialize, transfer, ingest, verify — journaling every step.

    Args:
        plan: An approved plan. A plan carrying conflicts is refused.
        mode: ``copy`` (source stays intact) or ``move`` (copy → verify →
            unlink, per file).
        ingest_formats: Which log formats to convert into each run's metrics
            buffer. ``None`` ingests nothing — silence is never consent.
        csv_mapping: molexp ``ColumnMapping`` for CSV ingestion.
        workspace_name: Name for the created workspace. Defaults to the target
            directory name.
        workspace_factory: Seam for tests; defaults to real molexp.
        ingest: Seam for tests; defaults to molexp's converters.

    Raises:
        AdoptionBlocked: a precondition failed. Nothing was written.
    """
    source = Path(plan.source).expanduser().resolve()
    target = Path(plan.target).expanduser().resolve()
    check_preconditions(source, target, mode)
    if plan.conflicts:
        raise AdoptionBlocked(
            "plan has unresolved conflicts; edit the plan and re-run: "
            + "; ".join(plan.conflicts)
        )
    if ingest_formats is not None:
        unknown = sorted(set(ingest_formats) - INGEST_FORMATS)
        if unknown:
            raise AdoptionBlocked(
                f"unknown ingest format(s) {unknown}; expected {sorted(INGEST_FORMATS)}"
            )

    prior = read_ledger(target)
    if prior is not None:
        ensure_compatible(prior, source=str(source), target=str(target), mode=mode)
    slots = _materialize(
        plan,
        target=target,
        prior=prior,
        workspace_name=workspace_name or target.name,
        workspace_factory=workspace_factory,
    )
    entries = _entries(plan, source, slots, want_ingest=bool(ingest_formats))
    ledger = resume_or_create(Ledger(str(source), str(target), mode, entries))
    write_ledger(ledger)

    ledger, transferred, reused, moved_bytes, problems = _transfer_all(ledger, mode)
    ingest_report: dict[str, dict[str, Any]] = {}
    if ingest_formats:
        ledger, ingest_report = _ingest_all(ledger, ingest_formats, csv_mapping, ingest)
    problems.extend(_verify(ledger))
    write_ledger(ledger)

    return AdoptionOutcome(
        ok=not problems,
        source=str(source),
        target=str(target),
        mode=mode,
        ledger_path=str(target / LEDGER_NAME),
        files_transferred=transferred,
        files_reused=reused,
        bytes_transferred=moved_bytes,
        runs=tuple(
            {
                "source": run.source,
                "run_id": slot.run_id,
                "project_id": slot.project_id,
                "experiment_id": slot.experiment_id,
                "run_dir": str(slot.run_dir),
                "files": run.total_files,
            }
            for run, slot in _pairs(plan, slots)
        ),
        ingest=ingest_report,
        problems=tuple(problems),
        skipped=tuple(skip.to_dict() for skip in plan.skipped),
    )


def _materialize(
    plan: AdoptionPlan,
    *,
    target: Path,
    prior: Ledger | None,
    workspace_name: str,
    workspace_factory: WorkspaceFactory,
) -> dict[str, RunSlot]:
    """Create-or-reuse the workspace tree; returns run source → slot."""
    done = {
        entry.source: entry
        for entry in (prior.of_kind("run") if prior else ())
        if entry.done and Path(entry.target).is_dir()
    }
    handle = workspace_factory(target, workspace_name)
    slots: dict[str, RunSlot] = {}
    for project, experiment, run in plan.iter_runs():
        previous = done.get(run.source)
        if previous is not None:
            slots[run.source] = RunSlot(
                project_id=previous.detail.split("/", 1)[0],
                experiment_id=previous.detail.split("/", 1)[-1],
                run_id=previous.run_id,
                run_dir=Path(previous.target),
            )
            continue
        project_id = handle.ensure_project(project.name)
        experiment_id = handle.ensure_experiment(project_id, experiment.name)
        slots[run.source] = handle.ensure_run(project_id, experiment_id, run.parameters)
    return slots


def _entries(
    plan: AdoptionPlan,
    source: Path,
    slots: dict[str, RunSlot],
    *,
    want_ingest: bool,
) -> tuple[Entry, ...]:
    """Ledger entries in deterministic order: run node, its files, its ingest.

    The ingest entry is planned up front so a resumed adoption can see it is
    already done — ``metrics.jsonl`` is append-only, and re-ingesting a run
    would double every curve in it.
    """
    entries: list[Entry] = []
    for run, slot in _pairs(plan, slots):
        entries.append(
            Entry(
                kind="run",
                source=run.source,
                target=str(slot.run_dir),
                status=VERIFIED,
                detail=f"{slot.project_id}/{slot.experiment_id}",
                run_id=slot.run_id,
            )
        )
        if want_ingest:
            entries.append(
                Entry(
                    kind="ingest",
                    source=run.source,
                    target=str(slot.run_dir),
                    status=PENDING,
                    run_id=slot.run_id,
                )
            )
        for rel in run.files:
            entries.append(
                Entry(
                    kind="file",
                    source=rel,
                    target=str(_target_for(rel, run, slot)),
                    status=PENDING,
                    size=_size_of(source / rel),
                    run_id=slot.run_id,
                )
            )
    return tuple(entries)


def _size_of(path: Path) -> int:
    try:
        return path.lstat().st_size
    except OSError:
        return 0


def _target_for(rel: str, run: RunPlan, slot: RunSlot) -> Path:
    prefix = f"{run.source}/" if run.source else ""
    inner = rel[len(prefix) :] if prefix and rel.startswith(prefix) else rel
    return slot.run_dir / ARTIFACTS_DIR / inner


def _pairs(plan: AdoptionPlan, slots: dict[str, RunSlot]):
    for _project, _experiment, run in plan.iter_runs():
        slot = slots.get(run.source)
        if slot is not None:
            yield run, slot


def _transfer_all(ledger: Ledger, mode: str) -> tuple[Ledger, int, int, int, list[str]]:
    """Transfer every outstanding file entry, checkpointing the ledger.

    The journal is flushed every :data:`LEDGER_FLUSH_EVERY` files rather than
    after each one — rewriting a 10k-entry document per file is quadratic. A
    resume that redoes a few already-copied files is free and safe: the
    destination hash matches, so the copy is reused, never overwritten.
    """
    source_root = Path(ledger.source)
    transferred = 0
    reused = 0
    moved_bytes = 0
    problems: list[str] = []
    since_flush = 0
    for index, entry in enumerate(ledger.entries):
        if entry.kind != "file" or entry.done:
            continue
        src = source_root / entry.source
        dst = Path(entry.target)
        if not src.exists() and not src.is_symlink():
            ledger = ledger.replace_entry(
                index, _with(entry, status=SKIPPED, detail="source vanished")
            )
            problems.append(f"source vanished before transfer: {entry.source}")
            write_ledger(ledger)
            since_flush = 0
            continue
        try:
            result = transfer_file(src, dst, mode=mode)
        except (TransferError, OSError) as exc:
            ledger = ledger.replace_entry(
                index, _with(entry, status=FAILED, detail=str(exc))
            )
            write_ledger(ledger)
            write_error_report(
                ledger.target,
                {"entry": entry.to_dict(), "error": str(exc)},
            )
            problems.append(str(exc))
            break
        status = MOVED if result.moved else VERIFIED
        ledger = ledger.replace_entry(
            index, _with(entry, status=status, sha256=result.sha256)
        )
        if result.reused:
            reused += 1
        else:
            transferred += 1
            moved_bytes += result.size
        since_flush += 1
        if since_flush >= LEDGER_FLUSH_EVERY:
            write_ledger(ledger)
            since_flush = 0
    if since_flush:
        write_ledger(ledger)
    return ledger, transferred, reused, moved_bytes, problems


def _ingest_all(
    ledger: Ledger,
    formats: frozenset[str],
    csv_mapping: Any,
    ingest: IngestFn,
) -> tuple[Ledger, dict[str, dict[str, Any]]]:
    """Ingest every not-yet-ingested run.

    A failed ingest never fails the adoption — the bytes are already
    transferred and verified. It is also not retried automatically: the buffer
    is append-only, so a converter that died partway must be re-run
    deliberately through ``ingest_metrics`` once the cause is fixed.
    """
    report: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(ledger.entries):
        if entry.kind != "ingest":
            continue
        if entry.done:
            report[entry.run_id] = {"ok": True, "already_ingested": True}
            continue
        try:
            outcome = ingest(Path(entry.target), formats, csv_mapping)
        except Exception as exc:  # noqa: BLE001 — a bad log must not lose bytes
            reason = f"{type(exc).__name__}: {exc}"
            ledger = ledger.replace_entry(
                index, _with(entry, status=SKIPPED, detail=reason)
            )
            report[entry.run_id] = {"ok": False, "error": reason}
            write_ledger(ledger)
            continue
        counts = ", ".join(f"{k}={v}" for k, v in sorted(outcome.ingested.items()))
        ledger = ledger.replace_entry(
            index, _with(entry, status=VERIFIED, detail=counts)
        )
        report[entry.run_id] = {"ok": True, **outcome.to_dict()}
        write_ledger(ledger)
    return ledger, report


def _verify(ledger: Ledger) -> list[str]:
    """Post-pass over the ledger: destinations present, nothing left pending.

    Each file was hashed on write and re-read before its entry flipped, so a
    third full hash here would only re-measure the same bytes. ``verify_files``
    exists for the deliberate audit (before deleting a source, say).
    """
    pairs = [
        (Path(entry.target), entry.size)
        for entry in ledger.entries
        if entry.kind == "file" and entry.status in (VERIFIED, MOVED)
    ]
    problems = verify_present(pairs)
    outstanding = [
        entry.source
        for entry in ledger.entries
        if entry.kind == "file" and not entry.done
    ]
    if outstanding:
        problems.append(
            f"{len(outstanding)} file(s) not transferred; re-run to resume "
            f"(first: {outstanding[0]})"
        )
    return problems


def _with(entry: Entry, **changes: Any) -> Entry:
    return replace(entry, **changes)
