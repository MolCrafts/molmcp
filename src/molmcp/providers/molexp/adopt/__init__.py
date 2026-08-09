"""Adopt a legacy data directory into a molexp workspace.

Four steps, four tools on the ``molexp`` plane:

``plan_adoption``
    Read-only survey + proposed ``Project → Experiment → Run`` mapping.
``run_adoption``
    Execute an approved plan: materialize, transfer with SHA-256 proof,
    optionally ingest logs, verify. Resumable via the ledger.
``adoption_status``
    Read the ledger — what is done, what is outstanding, optional re-hash.
``ingest_metrics``
    Convert a run's foreign logs into its metrics buffer, standalone.

Deleting the source directory is deliberately **not** here. Every other step
is provable and resumable; an irreversible delete is the operator's to make.
"""

from __future__ import annotations

from .ledger import (
    LEDGER_NAME,
    LEDGER_VERSION,
    Entry,
    Ledger,
    LedgerMismatch,
    ensure_compatible,
    ledger_path,
    read_ledger,
    resume_or_create,
    write_ledger,
)
from .plan import (
    AdoptionPlan,
    ExperimentPlan,
    ProjectPlan,
    RunPlan,
    SkippedPath,
    build_plan,
    default_target,
    find_conflicts,
    slugify,
)
from .runner import (
    ARTIFACTS_DIR,
    INGEST_FORMATS,
    AdoptionBlocked,
    AdoptionOutcome,
    IngestOutcome,
    RunSlot,
    check_preconditions,
    molexp_ingest,
    molexp_workspace_factory,
    run_adoption,
)
from .survey import (
    DEFAULT_EXCLUDES,
    DEFAULT_MAX_DEPTH,
    EXPERIMENT,
    LOOSE,
    PROJECT,
    RUN,
    DirNode,
    FileInfo,
    LogHit,
    Oddity,
    Survey,
    survey_source,
)
from .transfer import (
    COPY,
    MODES,
    MOVE,
    HashMismatch,
    TransferError,
    sha256_file,
    transfer_file,
    verify_present,
    verify_tree,
)

__all__ = [
    "ARTIFACTS_DIR",
    "COPY",
    "DEFAULT_EXCLUDES",
    "DEFAULT_MAX_DEPTH",
    "EXPERIMENT",
    "INGEST_FORMATS",
    "LEDGER_NAME",
    "LEDGER_VERSION",
    "LOOSE",
    "MODES",
    "MOVE",
    "PROJECT",
    "RUN",
    "AdoptionBlocked",
    "AdoptionOutcome",
    "AdoptionPlan",
    "DirNode",
    "Entry",
    "ExperimentPlan",
    "FileInfo",
    "HashMismatch",
    "IngestOutcome",
    "Ledger",
    "LedgerMismatch",
    "LogHit",
    "Oddity",
    "ProjectPlan",
    "RunPlan",
    "RunSlot",
    "SkippedPath",
    "Survey",
    "TransferError",
    "build_plan",
    "check_preconditions",
    "default_target",
    "ensure_compatible",
    "find_conflicts",
    "ledger_path",
    "molexp_ingest",
    "molexp_workspace_factory",
    "read_ledger",
    "resume_or_create",
    "run_adoption",
    "sha256_file",
    "slugify",
    "survey_source",
    "transfer_file",
    "verify_present",
    "verify_tree",
    "write_ledger",
]
