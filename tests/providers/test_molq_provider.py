"""``MolqProvider`` — the job-store plane, driven entirely through fakes.

molq's tests used to need a real ``JobStore`` and a real ``Submitor``, so
when the package left the dev environment the tests left with it. The
provider now takes both from injectable factories (the shape molvis has
with ``stage_factory``), so every tool below runs against a fake store and
a fake submitor.

**Nothing here imports ``molq``, and nothing here may start doing so.** The
two subprocess tests in :class:`TestUpstreamContract` are the guard: they
assert that importing the provider module and constructing the provider
both leave ``molq`` out of ``sys.modules``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from fastmcp import FastMCP

from molmcp.middleware import validate_plane_tool_names, validate_tool_annotations
from molmcp.providers.annotations import MUTATION, READ_ONLY, READ_REMOTE
from molmcp.providers.molq import MolqProvider
from molmcp.providers.molq.provider import (
    _is_unsafe_path,
    _normalize_scheduler,
    _resolve_db_path,
    _serialize,
    _validate_argv,
)

_REPO_SRC = Path(__file__).resolve().parents[2] / "src"

_TOOL_NAMES = frozenset(
    {
        "list_jobs",
        "get_job",
        "job_logs",
        "list_destinations",
        "list_queue",
        "submit_job",
        "cancel_job",
    }
)

#: One verbatim line per tool. The docstrings are the agent-facing contract:
#: they moved from nested functions onto methods and must not have been
#: reworded on the way.
_DOCSTRING_OPENERS = {
    "list_jobs": "List job records from the local molq DB.",
    "get_job": "Get one job by id (optionally refresh from the scheduler).",
    "job_logs": "Read job log text (no follow).",
    "list_destinations": "List known submission destinations (profiles + SSH hosts).",
    "list_queue": "Live scheduler queue snapshot (not the molq job store).",
    "submit_job": "Submit a single job (controlled mutation; opt-in).",
    "cancel_job": "Cancel one job (controlled mutation; opt-in).",
}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeRecord:
    """Stand-in for molq's frozen ``JobRecord``."""

    job_id: str = "job-1"
    cluster_name: str = "cli_local"
    scheduler: str = "local"
    state: str = "RUNNING"
    metadata: dict[str, Any] = field(default_factory=dict)


class FakeStore:
    """Stand-in for ``molq.store.JobStore`` — records how it was queried."""

    def __init__(self, records: list[FakeRecord] | None = None) -> None:
        self.records = list(records or [])
        self.list_calls: list[dict[str, Any]] = []
        self.closed = 0

    def list_records(
        self, cluster_name: str, *, include_terminal: bool = False
    ) -> list[FakeRecord]:
        self.list_calls.append(
            {"cluster_name": cluster_name, "include_terminal": include_terminal}
        )
        return [r for r in self.records if r.cluster_name == cluster_name]

    def list_all_records(
        self, *, include_terminal: bool = False, limit: int = 200
    ) -> list[FakeRecord]:
        self.list_calls.append({"include_terminal": include_terminal, "limit": limit})
        return self.records[:limit]

    def get_record(self, job_id: str) -> FakeRecord | None:
        return next((r for r in self.records if r.job_id == job_id), None)

    def close(self) -> None:
        self.closed += 1


class FakeTarget:
    """Stand-in for a molq ``Cluster`` — only the live-queue read is used."""

    def __init__(self, entries: list[Any]) -> None:
        self.entries = entries
        self.queried_users: list[str | None] = []

    def get_queue(self, user: str | None = None) -> list[Any]:
        self.queried_users.append(user)
        return list(self.entries)


class FakeSubmitor:
    """Stand-in for ``molq.Submitor`` — no scheduler, no transport."""

    def __init__(
        self,
        *,
        record: FakeRecord | None = None,
        logs: dict[str, Path] | None = None,
        queue: list[Any] | None = None,
        transitions: list[Any] | None = None,
    ) -> None:
        self.record = record or FakeRecord()
        self.logs = dict(logs or {})
        self.transitions = list(transitions or [{"state": "RUNNING", "at": 1.0}])
        self.target = FakeTarget(list(queue or []))
        self.cluster_name = self.record.cluster_name
        self.refreshed = 0
        self.cancelled: list[str] = []
        self.closed = 0

    def refresh_jobs(self) -> None:
        self.refreshed += 1

    def get_job(self, job_id: str) -> FakeRecord:
        return self.record

    def get_transitions(self, job_id: str) -> list[Any]:
        return list(self.transitions)

    def fetch_logs(self, job_id: str, streams: tuple[str, ...]) -> dict[str, Path]:
        return {name: self.logs[name] for name in streams if name in self.logs}

    def cancel_job(self, job_id: str) -> None:
        self.cancelled.append(job_id)

    def close(self) -> None:
        self.closed += 1


class RecordingStoreFactory:
    def __init__(self, store: FakeStore) -> None:
        self.store = store
        self.db_paths: list[Any] = []

    def __call__(self, db_path: Any) -> FakeStore:
        self.db_paths.append(db_path)
        return self.store


class RecordingSubmitorFactory:
    def __init__(self, submitor: FakeSubmitor) -> None:
        self.submitor = submitor
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> FakeSubmitor:
        self.calls.append(kwargs)
        return self.submitor


class Harness(NamedTuple):
    provider: MolqProvider
    store: FakeStore
    submitor: FakeSubmitor
    store_factory: RecordingStoreFactory
    submitor_factory: RecordingSubmitorFactory


def harness(
    *,
    records: list[FakeRecord] | None = None,
    logs: dict[str, Path] | None = None,
    queue: list[Any] | None = None,
    transitions: list[Any] | None = None,
    allow_submit: bool = False,
    db_path: str = ":memory:",
) -> Harness:
    """A provider whose store and submitor are fakes."""
    rows = list(records if records is not None else [FakeRecord()])
    store = FakeStore(rows)
    submitor = FakeSubmitor(
        record=rows[0] if rows else None,
        logs=logs,
        queue=queue,
        transitions=transitions,
    )
    store_factory = RecordingStoreFactory(store)
    submitor_factory = RecordingSubmitorFactory(submitor)
    provider = MolqProvider(
        db_path=db_path,
        allow_submit=allow_submit,
        store_factory=store_factory,
        submitor_factory=submitor_factory,
    )
    return Harness(provider, store, submitor, store_factory, submitor_factory)


class _Injected(MolqProvider):
    """A molq provider whose upstream is satisfied by injection.

    ``register()`` refuses to run without the ``molq`` distribution, which
    is exactly right in production and useless for testing the wiring. The
    tools themselves only ever touch the injected factories, so clearing
    the upstream here exercises registration without the package.
    """

    upstream = None
    import_name = None


def _registered(provider: MolqProvider) -> dict[str, Any]:
    mcp = FastMCP(provider.name)
    provider.register(mcp)
    return {t.name: t for t in asyncio.run(mcp.list_tools())}


def _subprocess_imports_molq(snippet: str) -> bool:
    """Run *snippet* in a fresh interpreter; True if it pulled in molq."""
    code = f"import sys\n{snippet}\nprint('molq' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        # Inherit the real environment and override PYTHONPATH: a stripped
        # env cannot start python.exe on Windows (no SYSTEMROOT, no DLL
        # path), and it bought no isolation anyway — whether molq is
        # importable depends on the interpreter's site-packages, not PATH.
        env={**os.environ, "PYTHONPATH": str(_REPO_SRC)},
    )
    return result.stdout.strip().endswith("True")


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------


class TestToolSurface:
    def test_the_plane_declares_seven_job_tools(self):
        specs = MolqProvider().tool_specs()

        assert {s.name for s in specs} == _TOOL_NAMES

    @pytest.mark.parametrize("name", ["list_jobs", "list_destinations"])
    def test_a_local_read_is_read_only(self, name):
        """These two never leave the local job DB / config files."""
        specs = {s.name: s for s in MolqProvider().tool_specs()}

        assert specs[name].annotations == READ_ONLY

    @pytest.mark.parametrize("name", ["get_job", "job_logs", "list_queue"])
    def test_a_scheduler_read_is_open_world(self, name):
        """These reach a scheduler or SSH host, so the answer can move."""
        specs = {s.name: s for s in MolqProvider().tool_specs()}

        assert specs[name].annotations == READ_REMOTE

    @pytest.mark.parametrize("name", ["submit_job", "cancel_job"])
    def test_a_job_mutation_is_flagged_for_confirmation(self, name):
        specs = {s.name: s for s in MolqProvider().tool_specs()}

        assert specs[name].annotations == MUTATION

    def test_every_tool_name_is_bare(self):
        """The server is already named ``molq``; tools must not repeat it."""
        bare = re.compile(r"^[a-z][a-z0-9_]*$")

        for spec in MolqProvider().tool_specs():
            assert bare.fullmatch(spec.name)
            assert not spec.name.startswith("molq")

    def test_the_wire_name_matches_the_method_name(self):
        for spec in MolqProvider().tool_specs():
            assert spec.name == spec.attribute

    @pytest.mark.parametrize(("name", "opener"), sorted(_DOCSTRING_OPENERS.items()))
    def test_a_tool_keeps_its_docstring_summary(self, name, opener):
        doc = getattr(MolqProvider, name).__doc__ or ""

        assert doc.strip().startswith(opener)

    @pytest.mark.parametrize("name", sorted(_TOOL_NAMES))
    def test_a_tool_keeps_its_argument_documentation(self, name):
        doc = getattr(MolqProvider, name).__doc__ or ""

        assert "Args:" in doc

    def test_the_submit_argv_warning_survived_the_move(self):
        """The verbatim rule matters most where it prevents shell injection."""
        doc = MolqProvider.submit_job.__doc__ or ""

        assert "argv: Command as a string list (never shell-interpreted)." in doc


class TestRegistration:
    def test_registration_exposes_the_bare_tool_names(self):
        assert set(_registered(_Injected())) == _TOOL_NAMES

    def test_registration_satisfies_the_plane_naming_contract(self):
        provider = _Injected()
        mcp = FastMCP(provider.name)
        provider.register(mcp)

        assert validate_plane_tool_names(mcp, provider.name) == []

    def test_every_registered_tool_carries_annotations(self):
        provider = _Injected()
        mcp = FastMCP(provider.name)
        provider.register(mcp)

        assert validate_tool_annotations(mcp, strict=False) == []

    def test_self_is_not_part_of_a_tool_schema(self):
        schema = _registered(_Injected())["list_jobs"].parameters

        assert "self" not in (schema.get("properties") or {})

    def test_the_docstring_reaches_the_client(self):
        description = _registered(_Injected())["cancel_job"].description or ""

        assert "Cancel one job (controlled mutation; opt-in)." in description

    def test_a_registered_tool_runs_against_the_injected_store(self):
        kit = harness(records=[FakeRecord(job_id="job-9")])
        provider = _Injected(
            db_path=":memory:",
            store_factory=kit.store_factory,
            submitor_factory=kit.submitor_factory,
        )
        mcp = FastMCP(provider.name)
        provider.register(mcp)

        asyncio.run(mcp.call_tool("list_jobs", {}))

        assert kit.store.list_calls == [{"include_terminal": False, "limit": 200}]


class TestUpstreamContract:
    def test_the_plane_names_the_molq_distribution(self):
        assert MolqProvider.upstream == "molcrafts-molq"
        assert MolqProvider.import_name == "molq"

    @pytest.mark.skipif(
        importlib.util.find_spec("molq") is not None,
        reason="molq is installed here, so the plane is available",
    )
    def test_the_plane_is_unavailable_without_molq(self):
        assert MolqProvider().probe() is False

    @pytest.mark.skipif(
        importlib.util.find_spec("molq") is not None,
        reason="molq is installed here, so registration succeeds",
    )
    def test_registering_without_molq_says_how_to_install_it(self):
        with pytest.raises(RuntimeError) as excinfo:
            MolqProvider().register(FastMCP("molq"))

        assert "pip install molcrafts-molq" in str(excinfo.value)

    def test_importing_the_provider_module_does_not_import_molq(self):
        """``molmcp planes`` imports every provider; none may drag a stack in."""
        assert not _subprocess_imports_molq("import molmcp.providers.molq.provider")

    def test_constructing_the_provider_does_not_import_molq(self):
        snippet = (
            "from molmcp.providers.molq import MolqProvider\nMolqProvider()\n"
            "MolqProvider().probe()"
        )

        assert not _subprocess_imports_molq(snippet)


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------


class TestTheOptInIsReachableFromTheCli:
    """`molmcp serve molq` must be able to turn the mutations on.

    `discover_providers()` instantiates every provider with `cls()`, so a
    constructor keyword is unreachable from the shipped CLI. Without a config
    gate, `submit_job` and `cancel_job` are advertised on the wire and fail on
    every call with a hint naming a Python argument no MCP client can pass —
    the exact shape the bare-tool-name hint rule exists to prevent.
    """

    def _settings(self, monkeypatch, **molq_settings):
        from molmcp import settings as settings_module

        monkeypatch.setattr(
            settings_module,
            "load_settings",
            lambda _root: settings_module.Settings(molq=molq_settings),
        )

    def test_the_setting_enables_a_default_constructed_provider(self, monkeypatch):
        self._settings(monkeypatch, allowSubmit=True)
        kit = harness()  # built exactly as discover_providers() builds it

        # cancel_job runs entirely through the injected submitor, so reaching
        # the fake proves the gate opened rather than that molq is installed.
        kit.provider.cancel_job(job_id="job-1")

        assert kit.submitor_factory.calls

    def test_a_string_setting_also_counts(self, monkeypatch):
        # `molmcp config set` takes text, so "true" must work like True.
        self._settings(monkeypatch, allowSubmit="true")
        kit = harness()

        kit.provider.cancel_job(job_id="job-1")

        assert kit.submitor_factory.calls

    def test_absent_setting_still_refuses(self, monkeypatch):
        self._settings(monkeypatch)

        with pytest.raises(RuntimeError):
            harness().provider.submit_job(argv=["echo", "hi"])

    def test_an_explicit_false_still_refuses(self, monkeypatch):
        self._settings(monkeypatch, allowSubmit=False)

        with pytest.raises(RuntimeError):
            harness().provider.cancel_job(job_id="job-1")

    def test_an_unrecognised_value_does_not_enable_a_mutation(self, monkeypatch):
        self._settings(monkeypatch, allowSubmit="yes-please")

        with pytest.raises(RuntimeError):
            harness().provider.cancel_job(job_id="job-1")

    def test_the_constructor_still_wins_for_embedders(self, monkeypatch):
        self._settings(monkeypatch, allowSubmit=False)
        kit = harness(allow_submit=True)

        kit.provider.cancel_job(job_id="job-1")

        assert kit.submitor_factory.calls

    def test_the_refusal_names_something_a_client_can_actually_set(self, monkeypatch):
        self._settings(monkeypatch)

        with pytest.raises(RuntimeError) as excinfo:
            harness().provider.submit_job(argv=["echo"])

        message = str(excinfo.value)
        assert "molq.allowSubmit" in message
        assert "allow_submit=True" not in message, (
            "a Python constructor keyword is not an action an MCP client can take"
        )


class TestMutationGate:
    def test_submit_job_is_refused_without_the_opt_in(self):
        with pytest.raises(RuntimeError):
            harness().provider.submit_job(argv=["echo", "hi"])

    def test_cancel_job_is_refused_without_the_opt_in(self):
        with pytest.raises(RuntimeError):
            harness().provider.cancel_job(job_id="job-1")

    def test_the_refusal_names_the_opt_in(self):
        with pytest.raises(RuntimeError) as excinfo:
            harness().provider.submit_job(argv=["echo"])

        assert "molq.allowSubmit" in str(excinfo.value)

    def test_a_refused_submit_never_reaches_the_submitor(self):
        kit = harness()

        with pytest.raises(RuntimeError):
            kit.provider.submit_job(argv=["echo"])

        assert kit.submitor_factory.calls == []

    def test_submit_job_rejects_a_shell_string(self):
        kit = harness(allow_submit=True)

        with pytest.raises(ValueError, match="non-empty list"):
            kit.provider.submit_job(argv="echo hi")  # type: ignore[arg-type]

    def test_submit_job_rejects_an_unknown_scheduler(self):
        kit = harness(allow_submit=True)

        with pytest.raises(ValueError, match="scheduler must be one of"):
            kit.provider.submit_job(argv=["echo"], scheduler="condor")

    def test_submit_job_refuses_an_unsafe_workdir(self):
        kit = harness(allow_submit=True)

        with pytest.raises(ValueError, match="unsafe workdir"):
            kit.provider.submit_job(argv=["echo"], workdir="../../etc")

    def test_cancel_job_runs_once_opted_in(self):
        kit = harness(allow_submit=True)

        result = kit.provider.cancel_job(job_id="job-1")

        assert kit.submitor.cancelled == ["job-1"]
        assert result["job_id"] == "job-1"

    def test_cancel_job_requires_a_job_id(self):
        kit = harness(allow_submit=True)

        with pytest.raises(ValueError, match="job_id is required"):
            kit.provider.cancel_job(job_id="  ")


class TestListJobs:
    def test_every_record_comes_back_serialized(self):
        kit = harness(records=[FakeRecord(job_id="a"), FakeRecord(job_id="b")])

        rows = kit.provider.list_jobs()

        assert [r["job_id"] for r in rows] == ["a", "b"]

    def test_the_log_paths_are_lifted_out_of_metadata(self):
        record = FakeRecord(
            metadata={
                "molq.stdout_path": "/logs/out.txt",
                "molq.stderr_path": "/logs/err.txt",
                "molq.job_dir": "/logs",
            }
        )
        kit = harness(records=[record])

        row = kit.provider.list_jobs()[0]

        assert row["stdout_path"] == "/logs/out.txt"
        assert row["stderr_path"] == "/logs/err.txt"
        assert row["job_dir"] == "/logs"

    def test_the_store_is_closed_afterwards(self):
        kit = harness()

        kit.provider.list_jobs()

        assert kit.store.closed == 1

    def test_one_cluster_uses_the_scoped_query(self):
        kit = harness(records=[FakeRecord(cluster_name="hpc")])

        kit.provider.list_jobs(cluster_name="hpc", include_terminal=True)

        assert kit.store.list_calls == [
            {"cluster_name": "hpc", "include_terminal": True}
        ]

    def test_the_store_is_opened_at_the_resolved_db_path(self):
        kit = harness()

        kit.provider.list_jobs()

        assert kit.store_factory.db_paths == [":memory:"]


class TestGetJob:
    def test_a_plain_read_never_opens_a_submitor(self):
        kit = harness()

        kit.provider.get_job(job_id="job-1", refresh=False, include_transitions=False)

        assert kit.submitor_factory.calls == []

    def test_a_refresh_reconciles_before_reading(self):
        kit = harness()

        kit.provider.get_job(job_id="job-1")

        assert kit.submitor.refreshed == 1

    def test_the_transition_timeline_is_included_on_request(self):
        kit = harness(transitions=[{"state": "PENDING", "at": 1.0}])

        payload = kit.provider.get_job(job_id="job-1", include_transitions=True)

        assert payload["transitions"] == [{"state": "PENDING", "at": 1.0}]

    def test_transitions_are_omitted_when_not_asked_for(self):
        kit = harness()

        payload = kit.provider.get_job(job_id="job-1", include_transitions=False)

        assert "transitions" not in payload

    def test_a_blank_job_id_is_refused(self):
        with pytest.raises(ValueError, match="job_id is required"):
            harness().provider.get_job(job_id="")

    def test_an_unknown_job_is_a_lookup_error(self):
        kit = harness(records=[FakeRecord(job_id="job-1")])

        with pytest.raises(LookupError, match="job not found"):
            kit.provider.get_job(job_id="nope")

    def test_the_submitor_follows_the_record(self):
        """Scheduler and cluster come from the stored job, not the caller."""
        kit = harness(records=[FakeRecord(scheduler="slurm", cluster_name="hpc")])

        kit.provider.get_job(job_id="job-1")

        call = kit.submitor_factory.calls[0]
        assert call["scheduler"] == "slurm"
        assert call["cluster"] == "hpc"

    def test_the_submitor_is_closed_afterwards(self):
        kit = harness()

        kit.provider.get_job(job_id="job-1")

        assert kit.submitor.closed == 1


class TestJobLogs:
    def test_the_stream_is_tailed(self, tmp_path):
        log = tmp_path / "out.txt"
        log.write_text("l1\nl2\nl3\nl4\n", encoding="utf-8")
        kit = harness(logs={"stdout": log})

        payload = kit.provider.job_logs(job_id="job-1", tail=2)

        assert payload["streams"]["stdout"]["text"] == "l3\nl4\n"

    def test_the_whole_file_comes_back_without_a_tail(self, tmp_path):
        log = tmp_path / "out.txt"
        log.write_text("l1\nl2\n", encoding="utf-8")
        kit = harness(logs={"stdout": log})

        payload = kit.provider.job_logs(job_id="job-1", tail=None)

        assert payload["streams"]["stdout"]["text"] == "l1\nl2\n"

    def test_a_stream_with_no_file_is_reported_missing(self):
        kit = harness(
            records=[FakeRecord(metadata={"molq.stderr_path": "/gone/err.txt"})]
        )

        payload = kit.provider.job_logs(job_id="job-1", stream="stderr")

        assert payload["streams"]["stderr"] == {
            "path": "/gone/err.txt",
            "text": "",
            "missing": True,
        }

    def test_both_streams_can_be_read_at_once(self, tmp_path):
        out = tmp_path / "out.txt"
        err = tmp_path / "err.txt"
        out.write_text("o\n", encoding="utf-8")
        err.write_text("e\n", encoding="utf-8")
        kit = harness(logs={"stdout": out, "stderr": err})

        payload = kit.provider.job_logs(job_id="job-1", stream="both")

        assert set(payload["streams"]) == {"stdout", "stderr"}

    def test_an_unknown_stream_is_refused(self):
        with pytest.raises(ValueError, match="stream must be one of"):
            harness().provider.job_logs(job_id="job-1", stream="trace")  # type: ignore[arg-type]

    def test_a_blank_job_id_is_refused(self):
        with pytest.raises(ValueError, match="job_id is required"):
            harness().provider.job_logs(job_id="")

    def test_the_state_travels_with_the_logs(self, tmp_path):
        log = tmp_path / "out.txt"
        log.write_text("x\n", encoding="utf-8")
        kit = harness(records=[FakeRecord(state="COMPLETED")], logs={"stdout": log})

        payload = kit.provider.job_logs(job_id="job-1")

        assert payload["state"] == "COMPLETED"


class TestListQueue:
    def test_the_live_queue_is_snapshotted(self):
        kit = harness(queue=[{"id": "1", "state": "R"}])

        assert kit.provider.list_queue() == [{"id": "1", "state": "R"}]

    def test_the_scheduler_name_is_normalized(self):
        kit = harness()

        kit.provider.list_queue(scheduler="  SLURM ")

        assert kit.submitor_factory.calls[0]["scheduler"] == "slurm"

    def test_an_unknown_scheduler_is_refused(self):
        with pytest.raises(ValueError, match="scheduler must be one of"):
            harness().provider.list_queue(scheduler="condor")

    def test_the_user_filter_reaches_the_target(self):
        kit = harness()

        kit.provider.list_queue(user="rk")

        assert kit.submitor.target.queried_users == ["rk"]

    def test_the_submitor_is_closed_afterwards(self):
        kit = harness()

        kit.provider.list_queue()

        assert kit.submitor.closed == 1


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestSerialize:
    def test_a_dataclass_becomes_a_dict(self):
        assert _serialize(FakeRecord(job_id="a"))["job_id"] == "a"

    def test_a_path_becomes_a_string(self):
        # str(Path(...)) is what goes on the wire, so the expectation has
        # to be the platform's own rendering — "/tmp/x" is "\\tmp\\x" on Windows.
        path = Path("/tmp/x")
        assert _serialize(path) == str(path)

    def test_an_enum_like_object_becomes_its_value(self):
        class State:
            value = "RUNNING"

        assert _serialize(State()) == "RUNNING"

    def test_a_tuple_becomes_a_list(self):
        assert _serialize((1, "a")) == [1, "a"]

    def test_nested_containers_are_walked(self):
        assert _serialize({"a": [Path("/x")]}) == {"a": ["/x"]}

    def test_primitives_pass_through(self):
        assert _serialize(None) is None
        assert _serialize(3) == 3

    def test_anything_else_falls_back_to_its_repr_text(self):
        class Opaque:
            def __str__(self) -> str:
                return "opaque"

        assert _serialize(Opaque()) == "opaque"


class TestValidateArgv:
    def test_an_empty_list_is_refused(self):
        with pytest.raises(ValueError, match="non-empty list"):
            _validate_argv([])

    def test_a_shell_string_is_refused(self):
        with pytest.raises(ValueError, match="non-empty list"):
            _validate_argv("echo hi")  # type: ignore[arg-type]

    def test_a_non_string_item_is_refused(self):
        with pytest.raises(ValueError, match="non-empty strings"):
            _validate_argv(["echo", 3])  # type: ignore[list-item]

    def test_an_empty_item_is_refused(self):
        with pytest.raises(ValueError, match="non-empty strings"):
            _validate_argv(["echo", ""])

    def test_a_valid_argv_is_copied_not_aliased(self):
        argv = ["echo", "hi"]

        assert _validate_argv(argv) == argv
        assert _validate_argv(argv) is not argv


class TestNormalizeScheduler:
    @pytest.mark.parametrize("raw", ["slurm", " SLURM ", "Slurm"])
    def test_the_name_is_trimmed_and_lowercased(self, raw):
        assert _normalize_scheduler(raw) == "slurm"

    def test_an_unknown_scheduler_lists_the_allowed_ones(self):
        with pytest.raises(ValueError) as excinfo:
            _normalize_scheduler("condor")

        assert "'local'" in str(excinfo.value)


class TestUnsafePath:
    @pytest.mark.parametrize("value", ["../etc", "a/../../b", r"a\..\b"])
    def test_a_parent_traversal_is_unsafe(self, value):
        assert _is_unsafe_path(value) is True

    def test_a_nul_byte_is_unsafe(self):
        assert _is_unsafe_path("runs\x00/x") is True

    @pytest.mark.parametrize("value", ["runs/job-1", "/abs/runs", "plain"])
    def test_an_ordinary_path_is_safe(self, value):
        assert _is_unsafe_path(value) is False


class TestResolveDbPath:
    def test_memory_passes_through_untouched(self):
        assert _resolve_db_path(":memory:") == ":memory:"

    def test_an_explicit_path_wins(self, tmp_path):
        assert _resolve_db_path(tmp_path / "jobs.db") == tmp_path / "jobs.db"

    def test_a_user_relative_path_is_expanded(self):
        resolved = _resolve_db_path("~/jobs.db")

        assert resolved == Path.home() / "jobs.db"

    def test_the_molq_database_setting_is_used_when_no_argument(self, monkeypatch):
        """`molq.database` in settings still resolves after the migration."""
        from molmcp import settings as settings_module

        monkeypatch.setattr(
            settings_module,
            "load_settings",
            lambda _root: settings_module.Settings(molq={"database": "~/from.db"}),
        )

        assert _resolve_db_path(None) == Path.home() / "from.db"

    @pytest.mark.skipif(
        importlib.util.find_spec("molq") is not None,
        reason="molq is installed here, so the fallback resolves to a real path",
    )
    def test_a_blank_setting_does_not_count_as_configured(self, monkeypatch):
        """Falling through to molq's default must not be short-circuited."""
        from molmcp import settings as settings_module

        monkeypatch.setattr(
            settings_module,
            "load_settings",
            lambda _root: settings_module.Settings(molq={"database": "   "}),
        )

        # No molq installed in test envs: the fallback import is the failure.
        with pytest.raises((ImportError, ModuleNotFoundError)):
            _resolve_db_path(None)


class TestInjectionMakesThePlaneServable:
    """An injected backend is the plane, upstream or no upstream.

    molvis already works this way: a supplied stage factory means the plane
    is servable whether or not molcrafts-molvis is anywhere near the
    process. molq gained the same seams but kept the base's "is molq
    importable" answer, so a fully-injected provider built its own backend
    and then had register() refuse it.
    """

    def _fully_injected(self) -> MolqProvider:
        from molmcp.providers.molq.provider import Destinations

        return MolqProvider(
            store_factory=lambda db_path: FakeStore(),
            submitor_factory=lambda **kwargs: FakeSubmitor(),
            destinations_factory=lambda: Destinations(profiles=[], ssh_hosts=list),
        )

    def test_a_fully_injected_provider_is_available(self):
        assert self._fully_injected().probe() is True

    def test_a_fully_injected_provider_registers(self):
        from fastmcp import FastMCP

        self._fully_injected().register(FastMCP("molq"))  # must not raise

    def test_a_partly_injected_provider_still_needs_the_package(self):
        """Two seams of three is not a backend: list_destinations would
        still import molq on first use, failing later and less clearly."""
        provider = MolqProvider(
            store_factory=lambda db_path: FakeStore(),
            submitor_factory=lambda **kwargs: FakeSubmitor(),
        )

        assert provider.probe() is MolqProvider().probe()


class FakeProfile:
    def __init__(self, name: str, cluster: str, scheduler: str) -> None:
        self.name = name
        self.cluster_name = cluster
        self.scheduler = scheduler


class FakeHost:
    def __init__(self, alias: str, target: str) -> None:
        self.alias = alias
        self.target = target


def _destinations(profiles=(), hosts=(), raises: Exception | None = None):
    """Build the one seam `list_destinations` reaches molq through."""
    from molmcp.providers.molq.provider import Destinations

    def ssh_hosts():
        if raises is not None:
            raise raises
        return list(hosts)

    return lambda: Destinations(profiles=list(profiles), ssh_hosts=ssh_hosts)


def _provider_with(destinations) -> MolqProvider:
    return MolqProvider(
        store_factory=lambda db_path: FakeStore(),
        submitor_factory=lambda **kwargs: FakeSubmitor(),
        destinations_factory=destinations,
    )


class TestListDestinations:
    """The last tool with no fake coverage.

    Its two molq touchpoints — load_config and list_ssh_hosts — sit behind
    one seam, so the row shaping and the ssh-failure fallback, which are
    molmcp's own, are reachable without the package.
    """

    def test_a_profile_becomes_a_row(self):
        provider = _provider_with(
            _destinations(profiles=[FakeProfile("prod", "devbox", "slurm")])
        )

        rows = provider.list_destinations(include_ssh=False)

        assert rows == [
            {
                "name": "devbox",
                "profile": "prod",
                "source": "profile:prod",
                "scheduler": "slurm",
                "target": "(profile)",
            }
        ]

    def test_ssh_hosts_are_appended_after_profiles(self):
        provider = _provider_with(
            _destinations(
                profiles=[FakeProfile("prod", "devbox", "slurm")],
                hosts=[FakeHost("gpu01", "user@gpu01")],
            )
        )

        rows = provider.list_destinations()

        assert [r["source"] for r in rows] == ["profile:prod", "ssh_config"]
        assert rows[1]["name"] == "gpu01"
        assert rows[1]["target"] == "user@gpu01"
        assert rows[1]["scheduler"] == "?"

    def test_excluding_ssh_never_reads_the_ssh_config(self):
        called = {"n": 0}

        def counting_hosts():
            called["n"] += 1
            return []

        from molmcp.providers.molq.provider import Destinations

        provider = _provider_with(
            lambda: Destinations(profiles=[], ssh_hosts=counting_hosts)
        )

        provider.list_destinations(include_ssh=False)

        assert called["n"] == 0

    def test_an_unreadable_ssh_config_becomes_a_row_not_an_exception(self):
        """A broken ~/.ssh/config must not take the whole listing down."""
        provider = _provider_with(_destinations(raises=OSError("permission denied")))

        rows = provider.list_destinations()

        assert len(rows) == 1
        assert rows[0]["source"] == "ssh_config_error"
        assert "permission denied" in rows[0]["target"]

    def test_no_profiles_and_no_hosts_is_an_empty_listing(self):
        assert _provider_with(_destinations()).list_destinations() == []
