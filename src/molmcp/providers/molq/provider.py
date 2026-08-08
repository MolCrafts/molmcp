"""``molq`` MCP provider — job lifecycle tools for agents.

Tools register bare on the ``molq`` plane server; a client sees
``molq__<name>``:

Read-only
  * ``list_jobs`` — job-store dashboard
  * ``get_job`` — single-job status (+ optional refresh / transitions)
  * ``job_logs`` — stdout/stderr text (tail; no follow)
  * ``list_destinations`` — profiles + SSH Host aliases
  * ``list_queue`` — live scheduler queue snapshot

Controlled mutations (opt-in via ``MolqProvider(allow_submit=True)``):
  * ``submit_job`` — single argv submit, no block-wait
  * ``cancel_job`` — cancel one job by id

DB resolution (in order):

1. The ``db_path`` constructor argument.
2. The ``molq.database`` setting.
3. molq's canonical default via :func:`molq.store.default_jobs_db_path`.

Every upstream object this plane needs comes from one of two factories —
:func:`_molq_store` and :func:`_molq_submitor` — both injectable through
the constructor and both importing ``molq`` only when actually called. So
the heavy import happens on the first tool call, never at module import or
provider construction, and a caller with its own store/submitor (tests, an
embedder) never needs molq installed at all.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from ..annotations import MUTATION, READ_ONLY, READ_REMOTE
from ..base import ProviderBase, tool

#: Settings key holding an override for the molq job database.
_DB_SETTING = "molq.database"
_ALLOWED_SCHEDULERS = frozenset({"local", "slurm", "pbs", "lsf"})
_LOG_STREAMS = frozenset({"stdout", "stderr", "both"})
_LOG_KEYS = {"stdout": "molq.stdout_path", "stderr": "molq.stderr_path"}

#: Builds the job store for a resolved database path.
StoreFactory = Callable[[Path | str], Any]

#: Builds a submitor. Keyword-only: ``scheduler``, ``cluster``, ``profile``,
#: ``store``, ``jobs_dir``.
SubmitorFactory = Callable[..., Any]


def _serialize(value: Any) -> Any:
    """Best-effort JSON-friendly conversion for molq frozen dataclasses."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _serialize(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int)):
        return enum_value
    return str(value)


def _resolve_db_path(arg: str | Path | None) -> Path | str:
    """Resolve the JobStore path (always concrete; never ``None``)."""
    if arg == ":memory:":
        return ":memory:"
    if arg is not None:
        return Path(arg).expanduser()
    from molmcp.settings import load_settings

    configured = str(load_settings(Path.cwd()).molq.get("database", "")).strip()
    if configured:
        return Path(configured).expanduser()
    from molq.store import default_jobs_db_path

    return default_jobs_db_path()


def _is_unsafe_path(value: str) -> bool:
    if "\x00" in value:
        return True
    parts = list(PurePosixPath(value).parts) + list(PureWindowsPath(value).parts)
    return any(p == ".." for p in parts)


def _validate_argv(argv: list[str]) -> list[str]:
    if not isinstance(argv, list) or not argv:
        raise ValueError("argv must be a non-empty list of strings")
    if not all(isinstance(item, str) and item for item in argv):
        raise ValueError("argv items must be non-empty strings (no shell string)")
    return list(argv)


def _normalize_scheduler(scheduler: str) -> str:
    sched = scheduler.strip().lower()
    if sched not in _ALLOWED_SCHEDULERS:
        raise ValueError(
            f"scheduler must be one of {sorted(_ALLOWED_SCHEDULERS)}, got {scheduler!r}"
        )
    return sched


def _record_payload(
    record: Any, *, transitions: list[Any] | None = None
) -> dict[str, Any]:
    """Serialize a JobRecord plus log-path convenience fields."""
    meta = getattr(record, "metadata", None) or {}
    payload = _serialize(record)
    if not isinstance(payload, dict):
        payload = {"value": payload}
    payload["stdout_path"] = meta.get("molq.stdout_path")
    payload["stderr_path"] = meta.get("molq.stderr_path")
    payload["job_dir"] = meta.get("molq.job_dir")
    if transitions is not None:
        payload["transitions"] = [_serialize(t) for t in transitions]
    return payload


def _read_log_text(path: Path, *, tail: int | None) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if tail is None:
        return text
    if tail < 0:
        raise ValueError("tail must be >= 0")
    lines = text.splitlines(keepends=True)
    return "".join(lines[-tail:])


def _close(resource: Any) -> None:
    """Close a store or submitor that has a ``close``; ignore ones that don't."""
    close = getattr(resource, "close", None)
    if callable(close):
        close()


def _molq_store(db_path: Path | str) -> Any:
    """Default store factory: a real :class:`molq.store.JobStore`."""
    from molq.store import JobStore

    return JobStore(db_path=db_path)


def _molq_submitor(
    *,
    scheduler: str,
    cluster: str | None,
    profile: str | None,
    store: Any,
    jobs_dir: Path | None,
) -> Any:
    """Default submitor factory (mirrors molq CLI ``_open_submitor``)."""
    from molq import Cluster, Submitor
    from molq.config import load_profile

    if profile:
        loaded = load_profile(profile)
        if loaded.scheduler != scheduler:
            raise ValueError(
                f"profile {profile!r} uses scheduler {loaded.scheduler!r}, "
                f"not {scheduler!r}"
            )
        cluster_name = cluster or loaded.cluster_name
        target = Cluster(
            cluster_name,
            scheduler,
            scheduler_options=loaded.scheduler_options,
        )
        return Submitor(
            target,
            defaults=loaded.defaults,
            store=store,
            jobs_dir=jobs_dir if jobs_dir is not None else loaded.jobs_dir,
            default_retry_policy=loaded.retry,
            retention_policy=loaded.retention,
            profile_name=loaded.name,
        )

    cluster_name = cluster or f"cli_{scheduler}"
    # Local jobs stay on LocalTransport — never resolve the label as an
    # SSH Host (would expand blast radius for an opt-in MCP mutation).
    if scheduler == "local":
        target = Cluster(cluster_name, "local")
    else:
        try:
            target = Cluster.from_ssh_alias(cluster_name, scheduler=scheduler)
        except Exception:
            target = Cluster(cluster_name, scheduler)
    return Submitor(target=target, store=store, jobs_dir=jobs_dir)


class MolqProvider(ProviderBase):
    """Provider for molq job dashboard, logs, destinations, and opt-in mutate.

    Args:
        db_path: Override for the jobs database. ``":memory:"`` is honored
            for testing. When omitted, the ``molq.database`` setting then
            molq's canonical default apply.
        allow_submit: Explicitly enable ``submit_job`` and ``cancel_job``.
            Defaults to ``False``.
        jobs_dir: Optional override for per-job artifact directory (tests).
        store_factory: Callable building the job store from a resolved db
            path. Defaults to a real ``molq.store.JobStore``.
        submitor_factory: Callable building a submitor from keyword
            ``scheduler`` / ``cluster`` / ``profile`` / ``store`` /
            ``jobs_dir``. Defaults to a real ``molq.Submitor``.

    Injecting both factories removes the molq dependency from this plane
    entirely, which is what lets the tools be tested without a scheduler.
    """

    name = "molq"
    upstream = "molcrafts-molq"
    import_name = "molq"

    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        allow_submit: bool = False,
        jobs_dir: str | Path | None = None,
        store_factory: StoreFactory | None = None,
        submitor_factory: SubmitorFactory | None = None,
    ) -> None:
        self._db_path_arg = db_path
        self._allow_submit = allow_submit
        self._jobs_dir = Path(jobs_dir).expanduser() if jobs_dir is not None else None
        self._store_factory = store_factory
        self._submitor_factory = submitor_factory

    # -- upstream plumbing ----------------------------------------------

    def probe(self) -> bool:
        """True when both backends are injected, or ``molq`` is importable.

        An injected backend *is* the plane. This mirrors the molvis stage
        factory: a provider handed its own store and submitor never reaches
        for the upstream package, so refusing to serve it because that
        package is absent would make the seam useless for exactly the
        embedders and tests it exists for.

        Both seams are required. One alone still leaves the other half
        importing molq on first use, which would fail later and less
        clearly than failing here.
        """
        if self._store_factory is not None and self._submitor_factory is not None:
            return True
        return super().probe()

    def _mutate_enabled(self) -> bool:
        return self._allow_submit

    def _require_mutate(self, op: str) -> None:
        if not self._mutate_enabled():
            raise RuntimeError(
                f"molq {op} is disabled. Opt in with MolqProvider(allow_submit=True)."
            )

    def _open_store(self) -> Any:
        factory = self._store_factory or _molq_store
        return factory(_resolve_db_path(self._db_path_arg))

    def _get_record(self, job_id: str) -> Any:
        store = self._open_store()
        try:
            record = store.get_record(job_id)
            if record is None:
                # Retry lineage: cancel/status may need the latest attempt.
                get_latest = getattr(store, "get_latest_attempt_record", None)
                if callable(get_latest):
                    record = get_latest(job_id)
            if record is None:
                raise LookupError(f"job not found: {job_id}")
            return record
        finally:
            _close(store)

    def _open_submitor(
        self,
        *,
        scheduler: str,
        cluster: str | None,
        profile: str | None = None,
    ) -> Any:
        """Build a Submitor over this provider's store."""
        factory = self._submitor_factory or _molq_submitor
        return factory(
            scheduler=scheduler,
            cluster=cluster,
            profile=profile,
            store=self._open_store(),
            jobs_dir=self._jobs_dir,
        )

    def _open_submitor_for_job(self, job_id: str) -> tuple[Any, Any]:
        """Return ``(submitor, record)`` for a known job_id."""
        record = self._get_record(job_id)
        submitor = self._open_submitor(
            scheduler=record.scheduler,
            cluster=record.cluster_name,
        )
        return submitor, record

    # -- tools -----------------------------------------------------------

    @tool(READ_ONLY)
    def list_jobs(
        self,
        cluster_name: str | None = None,
        include_terminal: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """List job records from the local molq DB.

        Args:
            cluster_name: Restrict to one cluster. ``None`` returns
                jobs across all clusters in the DB.
            include_terminal: Include terminal states. Defaults to False.
            limit: Max rows when listing all clusters. Default 200.

        Returns:
            Serialized JobRecord dicts (newest first).
        """
        store = self._open_store()
        try:
            if cluster_name is not None:
                records = store.list_records(
                    cluster_name, include_terminal=include_terminal
                )
            else:
                records = store.list_all_records(
                    include_terminal=include_terminal, limit=limit
                )
        finally:
            _close(store)
        return [_record_payload(r) for r in records]

    @tool(READ_REMOTE)
    def get_job(
        self,
        job_id: str,
        refresh: bool = True,
        include_transitions: bool = True,
    ) -> dict[str, Any]:
        """Get one job by id (optionally refresh from the scheduler).

        Args:
            job_id: molq UUID job id.
            refresh: When True (default), reconcile active jobs against
                the scheduler before reading.
            include_transitions: Include status transition timeline.

        Returns:
            JobRecord fields plus ``stdout_path``, ``stderr_path``,
            ``job_dir``, and optional ``transitions``.
        """
        if not job_id or not str(job_id).strip():
            raise ValueError("job_id is required")

        if not refresh and not include_transitions:
            record = self._get_record(job_id)
            return _record_payload(record, transitions=None)

        submitor, _seed = self._open_submitor_for_job(job_id)
        try:
            if refresh:
                submitor.refresh_jobs()
            record = submitor.get_job(job_id)
            transitions = None
            if include_transitions:
                transitions = submitor.get_transitions(job_id)
            return _record_payload(record, transitions=transitions)
        finally:
            _close(submitor)

    @tool(READ_REMOTE)
    def job_logs(
        self,
        job_id: str,
        stream: Literal["stdout", "stderr", "both"] = "stdout",
        tail: int | None = 200,
        refresh: bool = True,
    ) -> dict[str, Any]:
        """Read job log text (no follow).

        For remote clusters, pulls logs via transport into a local
        scratch dir first. Local clusters read paths from metadata.

        Args:
            job_id: molq UUID job id.
            stream: ``stdout``, ``stderr``, or ``both``.
            tail: Last N lines per stream; ``None`` returns full file.
                Default 200.
            refresh: Reconcile job state before resolving log paths.

        Returns:
            Dict with ``job_id``, ``state``, and ``streams`` mapping
            stream name → ``{path, text, missing}``.
        """
        if not job_id or not str(job_id).strip():
            raise ValueError("job_id is required")
        stream_name = stream.lower()
        if stream_name not in _LOG_STREAMS:
            raise ValueError("stream must be one of: stdout, stderr, both")

        wanted: tuple[str, ...] = (
            ("stdout", "stderr") if stream_name == "both" else (stream_name,)
        )

        submitor, _seed = self._open_submitor_for_job(job_id)
        try:
            if refresh:
                submitor.refresh_jobs()
            record = submitor.get_job(job_id)

            # Prefer fetch_logs (handles remote + local copy).
            local_paths: dict[str, Path] = {}
            try:
                local_paths = submitor.fetch_logs(job_id, streams=wanted)
            except Exception:
                # Fall back to reading metadata paths if they exist locally.
                for name in wanted:
                    remote = record.metadata.get(_LOG_KEYS[name])
                    if remote and Path(remote).is_file():
                        local_paths[name] = Path(remote)

            streams_out: dict[str, Any] = {}
            for name in wanted:
                meta_path = record.metadata.get(_LOG_KEYS[name])
                path = local_paths.get(name)
                if path is None or not Path(path).is_file():
                    streams_out[name] = {
                        "path": meta_path,
                        "text": "",
                        "missing": True,
                    }
                    continue
                streams_out[name] = {
                    "path": str(path),
                    "text": _read_log_text(Path(path), tail=tail),
                    "missing": False,
                }

            return {
                "job_id": record.job_id,
                "state": _serialize(record.state),
                "streams": streams_out,
            }
        finally:
            _close(submitor)

    @tool(READ_ONLY)
    def list_destinations(
        self,
        include_ssh: bool = True,
    ) -> list[dict[str, Any]]:
        """List known submission destinations (profiles + SSH hosts).

        Args:
            include_ssh: Include ``~/.ssh/config`` Host aliases.
                Defaults to True.

        Returns:
            Rows with ``name``, ``source``, ``scheduler``, ``target``.
        """
        from molq import load_config

        rows: list[dict[str, Any]] = []
        cfg = load_config()
        for profile in cfg.profiles.values():
            rows.append(
                {
                    "name": profile.cluster_name,
                    "profile": profile.name,
                    "source": f"profile:{profile.name}",
                    "scheduler": profile.scheduler,
                    "target": "(profile)",
                }
            )
        if include_ssh:
            try:
                from molq import list_ssh_hosts

                for host in list_ssh_hosts():
                    rows.append(
                        {
                            "name": host.alias,
                            "profile": None,
                            "source": "ssh_config",
                            "scheduler": "?",
                            "target": host.target,
                        }
                    )
            except Exception as exc:
                rows.append(
                    {
                        "name": "",
                        "profile": None,
                        "source": "ssh_config_error",
                        "scheduler": "?",
                        "target": str(exc),
                    }
                )
        return rows

    @tool(READ_REMOTE)
    def list_queue(
        self,
        scheduler: str = "local",
        cluster: str | None = None,
        profile: str | None = None,
        user: str | None = None,
    ) -> list[dict[str, Any]]:
        """Live scheduler queue snapshot (not the molq job store).

        Equivalent to ``squeue`` / ``qstat`` / ``bjobs``. Local
        schedulers return an empty list.

        Args:
            scheduler: ``local`` / ``slurm`` / ``pbs`` / ``lsf``.
            cluster: Cluster label / SSH alias.
            profile: Optional named profile.
            user: Optional user filter for the scheduler query.
        """
        sched = _normalize_scheduler(scheduler)
        submitor = self._open_submitor(
            scheduler=sched, cluster=cluster, profile=profile
        )
        try:
            entries = submitor.target.get_queue(user=user)
            return [_serialize(e) for e in entries]
        finally:
            _close(submitor)

    @tool(MUTATION)
    def submit_job(
        self,
        argv: list[str],
        scheduler: str = "local",
        cluster: str | None = None,
        profile: str | None = None,
        cpus: int | None = None,
        mem: str | None = None,
        time: str | None = None,
        partition: str | None = None,
        gpus: int | None = None,
        gpu_type: str | None = None,
        name: str | None = None,
        workdir: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any]:
        """Submit a single job (controlled mutation; opt-in).

        Requires ``MolqProvider(allow_submit=True)``. Does **not**
        wait —
        poll with ``get_job`` / ``list_jobs``.

        Args:
            argv: Command as a string list (never shell-interpreted).
            scheduler: ``local`` / ``slurm`` / ``pbs`` / ``lsf``.
            cluster: Cluster label; default ``cli_<scheduler>``.
            profile: Optional named profile from molq config.
            cpus: CPU cores to request.
            mem: Memory request string (e.g. ``8G``, ``512M``).
            time: Wall-time limit (e.g. ``4h``, ``2h30m``).
            partition: Partition / queue name.
            gpus: GPU count.
            gpu_type: GPU type string for the scheduler.
            name: Job name shown in the scheduler.
            workdir: Working directory for the job.
            account: Billing / accounting account.
        """
        self._require_mutate("submit_job")
        cmd = _validate_argv(argv)
        sched = _normalize_scheduler(scheduler)
        if workdir is not None and _is_unsafe_path(workdir):
            raise ValueError(f"Refusing unsafe workdir: {workdir!r}")

        from molq import (
            Duration,
            JobExecution,
            JobResources,
            JobScheduling,
            Memory,
        )

        resources = JobResources(
            cpu_count=cpus,
            memory=Memory.parse(mem) if mem else None,
            gpu_count=gpus,
            gpu_type=gpu_type,
            time_limit=Duration.parse(time) if time else None,
        )
        scheduling = JobScheduling(partition=partition, account=account)
        execution = JobExecution(cwd=workdir, job_name=name)

        submitor = self._open_submitor(
            scheduler=sched, cluster=cluster, profile=profile
        )
        try:
            handle = submitor.submit_job(
                argv=cmd,
                resources=resources,
                scheduling=scheduling,
                execution=execution,
            )
            record = submitor.get_job(handle.job_id)
            return {
                "job_id": handle.job_id,
                "cluster": submitor.cluster_name,
                "scheduler": sched,
                "command": " ".join(cmd),
                "state": _serialize(record.state),
            }
        finally:
            _close(submitor)

    @tool(MUTATION)
    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Cancel one job (controlled mutation; opt-in).

        Requires the same opt-in as ``submit_job``. Cluster/scheduler
        are taken from the job record in the store.

        Args:
            job_id: molq UUID job id.

        Returns:
            Dict with ``job_id``, ``state`` after cancel.
        """
        self._require_mutate("cancel_job")
        if not job_id or not str(job_id).strip():
            raise ValueError("job_id is required")

        submitor, _seed = self._open_submitor_for_job(job_id)
        try:
            submitor.cancel_job(job_id)
            record = submitor.get_job(job_id)
            return {
                "job_id": record.job_id,
                "cluster": record.cluster_name,
                "state": _serialize(record.state),
            }
        finally:
            _close(submitor)
