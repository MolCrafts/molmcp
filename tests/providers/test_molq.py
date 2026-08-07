"""Tests for ``MolqProvider`` lifecycle tools.

Requires ``molcrafts-molq`` (dev extra). Do not skip.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from molmcp import create_plane
from molmcp.providers.molq import MolqProvider
from molmcp.providers.molq.provider import (
    _resolve_db_path,
    _serialize,
    _validate_argv,
)


def _build_server(provider: MolqProvider) -> Any:
    return create_plane(
        provider.name,
        provider=provider,
        discover_entry_points=False,
    )


def _call(server: Any, name: str, args: dict[str, Any] | None = None) -> Any:
    """Invoke a tool and unwrap the FastMCP structured result."""
    result = asyncio.run(server.call_tool(name, args or {}))
    if getattr(result, "is_error", False):
        text = ""
        if result.content:
            text = getattr(result.content[0], "text", str(result.content[0]))
        raise RuntimeError(text or "tool error")
    sc = getattr(result, "structured_content", None)
    if isinstance(sc, dict) and "result" in sc:
        return sc["result"]
    if result.content:
        import json

        text = result.content[0].text
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
    return sc


def _list_tools(server: Any) -> list[Any]:
    return asyncio.run(server.list_tools())


@pytest.fixture
def provider_factory(tmp_path: Path):

    def _make(*, db_path=None, allow_submit: bool = False) -> MolqProvider:
        return MolqProvider(
            db_path=db_path or tmp_path / "jobs.db",
            allow_submit=allow_submit,
            jobs_dir=tmp_path / "jobs",
        )

    return _make


@pytest.fixture
def populated_db(tmp_path: Path):
    """Submit one local ``true`` job and return (db_path, cluster, job_id)."""

    from molq import Cluster
    from molq.store import JobStore
    from molq.submitor import Submitor

    db = tmp_path / "jobs.db"
    cluster = Cluster("devbox", "local")
    store = JobStore(db_path=db)
    submitor = Submitor(target=cluster, store=store, jobs_dir=tmp_path / "jobs")
    try:
        handle = submitor.submit_job(argv=["true"])
        handle.wait(timeout=30)
    finally:
        submitor.close()
    return db, cluster.name, handle.job_id


# ---------------------------------------------------------------------------
# Helpers — pure functions, no molq dependency
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Record:
    job_id: str
    nested: Path
    score: float


class _Status(Enum):
    RUNNING = "running"
    DONE = 2


class TestSerializeHelper:
    def test_passes_through_primitives(self):
        assert _serialize(None) is None
        assert _serialize("hello") == "hello"
        assert _serialize(42) == 42
        assert _serialize(3.14) == 3.14
        assert _serialize(True) is True

    def test_converts_path_to_string(self):
        p = Path("/tmp/x")
        assert _serialize(p) == str(p)

    def test_unwraps_dataclass_recursively(self):
        p = Path("/a")
        rec = _Record(job_id="j1", nested=p, score=1.5)
        out = _serialize(rec)
        assert out == {"job_id": "j1", "nested": str(p), "score": 1.5}

    def test_walks_dict_values(self):
        px, py = Path("/x"), Path("/y")
        out = _serialize({"a": px, "b": [1, py]})
        assert out == {"a": str(px), "b": [1, str(py)]}

    def test_walks_list_and_tuple(self):
        pa, pb = Path("/a"), Path("/b")
        assert _serialize([pa, pb]) == [str(pa), str(pb)]
        assert _serialize((pa, 1)) == [str(pa), 1]

    def test_extracts_enum_value(self):
        assert _serialize(_Status.RUNNING) == "running"
        assert _serialize(_Status.DONE) == 2

    def test_falls_back_to_str_for_unknown_objects(self):
        class _Opaque:
            def __str__(self) -> str:
                return "opaque-repr"

        assert _serialize(_Opaque()) == "opaque-repr"


def _set_molq_db(monkeypatch, home: Path, db: Path) -> None:
    """Point the molq.database setting at *db* via a scratch home."""
    from molmcp import settings as st

    monkeypatch.setattr(st.Path, "home", staticmethod(lambda: home))
    st.write_settings_file(st.user_settings_path(), {"molq": {"database": str(db)}})


class TestResolveDbPath:
    def test_memory_passes_through(self):
        assert _resolve_db_path(":memory:") == ":memory:"

    def test_arg_wins_over_the_setting(self, monkeypatch, tmp_path: Path):
        _set_molq_db(monkeypatch, tmp_path, tmp_path / "env.db")
        out = _resolve_db_path(tmp_path / "arg.db")
        assert out == tmp_path / "arg.db"

    def test_setting_used_when_arg_missing(self, monkeypatch, tmp_path: Path):
        _set_molq_db(monkeypatch, tmp_path, tmp_path / "env.db")
        out = _resolve_db_path(None)
        assert out == tmp_path / "env.db"

    def test_falls_back_to_molq_default(self, monkeypatch, tmp_path: Path):
        from molmcp import settings as st

        monkeypatch.setattr(st.Path, "home", staticmethod(lambda: tmp_path))
        from molq.store import default_jobs_db_path

        assert _resolve_db_path(None) == default_jobs_db_path()

    def test_expands_user_home(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        out = _resolve_db_path("~/jobs.db")
        assert out == tmp_path / "jobs.db"


class TestValidateArgv:
    def test_accepts_non_empty_list(self):
        assert _validate_argv(["echo", "hi"]) == ["echo", "hi"]

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="non-empty"):
            _validate_argv([])

    def test_rejects_non_strings(self):
        with pytest.raises(ValueError, match="non-empty strings"):
            _validate_argv(["ok", 1])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# Register-time guard — no molq install needed
# ---------------------------------------------------------------------------


class TestRegisterGuard:
    def test_register_without_molq_raises_runtime_error(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "molq", None)
        with pytest.raises(RuntimeError, match="molcrafts-molq"):
            MolqProvider().register(MagicMock())


# ---------------------------------------------------------------------------
# Protocol / tool surface
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_implements_molmcp_protocol(self):
        from molmcp import Provider

        p = MolqProvider()
        assert isinstance(p, Provider)
        assert p.name == "molq"

    def test_tool_set(self, provider_factory):
        server = _build_server(provider_factory())
        names = {t.name for t in _list_tools(server)}
        # Bare tool names on molq plane
        assert names >= {
            "list_jobs",
            "get_job",
            "job_logs",
            "list_destinations",
            "list_queue",
            "submit_job",
            "cancel_job",
        }

    def test_list_jobs_is_read_only(self, provider_factory):
        server = _build_server(provider_factory())
        tools = {t.name: t for t in _list_tools(server)}
        ann = tools["list_jobs"].annotations
        assert getattr(ann, "read_only_hint", False) is True

    def test_submit_and_cancel_are_destructive(self, provider_factory):
        server = _build_server(provider_factory())
        tools = {t.name: t for t in _list_tools(server)}
        for name in ("submit_job", "cancel_job"):
            ann = tools[name].annotations
            assert getattr(ann, "destructive_hint", False) is True
            assert getattr(ann, "read_only_hint", True) is False


# ---------------------------------------------------------------------------
# list_jobs semantics
# ---------------------------------------------------------------------------


class TestMolqListJobs:
    def test_returns_submitted_job(self, populated_db, provider_factory):
        db, alias, job_id = populated_db
        server = _build_server(provider_factory(db_path=db))
        records = _call(
            server,
            "list_jobs",
            {"cluster_name": alias, "include_terminal": True},
        )
        assert any(r["job_id"] == job_id for r in records)

    def test_empty_db_returns_empty_list(self, provider_factory):
        server = _build_server(provider_factory())
        records = _call(server, "list_jobs")
        assert records == []

    def test_excludes_terminal_by_default(self, populated_db, provider_factory):
        db, alias, _ = populated_db
        server = _build_server(provider_factory(db_path=db))
        records = _call(server, "list_jobs", {"cluster_name": alias})
        # ``true`` finishes immediately → terminal → filtered out.
        assert records == []

    def test_all_clusters_when_omitted(self, populated_db, provider_factory):
        db, _, job_id = populated_db
        server = _build_server(provider_factory(db_path=db))
        records = _call(server, "list_jobs", {"include_terminal": True})
        assert any(r["job_id"] == job_id for r in records)


class TestStoreDispatch:
    def test_limit_only_applies_to_all_clusters_listing(self, monkeypatch):
        captured: dict[str, Any] = {}

        class _StubStore:
            def list_records(self, cluster_name, *, include_terminal):
                captured["scope"] = "per_cluster"
                captured["cluster"] = cluster_name
                captured["include_terminal"] = include_terminal
                return []

            def list_all_records(self, *, include_terminal, limit):
                captured["scope"] = "all"
                captured["include_terminal"] = include_terminal
                captured["limit"] = limit
                return []

            def close(self):
                captured["closed"] = True

        monkeypatch.setitem(sys.modules, "molq", SimpleNamespace())
        provider = MolqProvider()
        monkeypatch.setattr(provider, "_open_store", lambda: _StubStore())

        server = _build_server(provider)

        captured.clear()
        _call(
            server,
            "list_jobs",
            {"cluster_name": "alpha", "limit": 5},
        )
        assert captured["scope"] == "per_cluster"
        assert captured["cluster"] == "alpha"
        assert "limit" not in captured
        assert captured["closed"] is True

        captured.clear()
        _call(server, "list_jobs", {"limit": 7})
        assert captured["scope"] == "all"
        assert captured["limit"] == 7


# ---------------------------------------------------------------------------
# submit_job — opt-in gate + happy path
# ---------------------------------------------------------------------------


class TestMolqSubmitJob:
    def test_disabled_by_default(self, provider_factory):
        from fastmcp.exceptions import ToolError

        server = _build_server(provider_factory(allow_submit=False))
        with pytest.raises(ToolError, match="disabled"):
            _call(server, "submit_job", {"argv": ["true"]})

    def test_explicit_opt_in(self, provider_factory):
        server = _build_server(provider_factory(allow_submit=True))
        result = _call(
            server,
            "submit_job",
            {"argv": ["true"], "scheduler": "local", "cluster": "mcp-test"},
        )
        assert "job_id" in result
        assert result["scheduler"] == "local"
        assert result["cluster"] == "mcp-test"
        assert result["command"] == "true"

    def test_constructor_opt_in(self, provider_factory):
        server = _build_server(provider_factory(allow_submit=True))
        result = _call(
            server,
            "submit_job",
            {
                "argv": ["echo", "hello"],
                "scheduler": "local",
                "cluster": "mcp-test",
            },
        )
        assert result["job_id"]
        assert result["command"] == "echo hello"

        # Visible via list_jobs once we include terminal (echo exits fast).
        records = _call(
            server,
            "list_jobs",
            {"cluster_name": "mcp-test", "include_terminal": True},
        )
        assert any(r["job_id"] == result["job_id"] for r in records)

    def test_rejects_empty_argv(self, provider_factory):
        from fastmcp.exceptions import ToolError

        server = _build_server(provider_factory(allow_submit=True))
        with pytest.raises(ToolError, match="non-empty"):
            _call(server, "submit_job", {"argv": []})

    def test_rejects_unknown_scheduler(self, provider_factory):
        from fastmcp.exceptions import ToolError

        server = _build_server(provider_factory(allow_submit=True))
        with pytest.raises(ToolError, match="scheduler"):
            _call(
                server,
                "submit_job",
                {"argv": ["true"], "scheduler": "htcondor"},
            )

    def test_rejects_unsafe_workdir(self, provider_factory):
        from fastmcp.exceptions import ToolError

        server = _build_server(provider_factory(allow_submit=True))
        with pytest.raises(ToolError, match="unsafe workdir"):
            _call(
                server,
                "submit_job",
                {"argv": ["true"], "workdir": "../escape"},
            )


# ---------------------------------------------------------------------------
# get_job / job_logs / cancel / destinations / queue
# ---------------------------------------------------------------------------


class TestMolqGetJob:
    def test_returns_job_with_transitions(self, populated_db, provider_factory):
        db, _alias, job_id = populated_db
        server = _build_server(provider_factory(db_path=db))
        row = _call(
            server,
            "get_job",
            {"job_id": job_id, "refresh": True, "include_transitions": True},
        )
        assert row["job_id"] == job_id
        assert row["state"] in {
            "succeeded",
            "failed",
            "cancelled",
            "timed_out",
            "lost",
            "running",
            "queued",
            "submitted",
            "created",
        }
        assert "transitions" in row
        assert isinstance(row["transitions"], list)
        assert "stdout_path" in row

    def test_missing_job_errors(self, provider_factory):
        from fastmcp.exceptions import ToolError

        server = _build_server(provider_factory())
        with pytest.raises(ToolError, match="not found"):
            _call(server, "get_job", {"job_id": "does-not-exist"})


class TestMolqJobLogs:
    def test_reads_stdout(self, populated_db, provider_factory):
        db, _alias, job_id = populated_db
        server = _build_server(provider_factory(db_path=db))
        out = _call(
            server,
            "job_logs",
            {"job_id": job_id, "stream": "stdout", "tail": 50},
        )
        assert out["job_id"] == job_id
        assert "streams" in out
        assert "stdout" in out["streams"]
        # true produces empty stdout — still a valid non-error response
        assert (
            out["streams"]["stdout"]["missing"] is False
            or out["streams"]["stdout"]["text"] == ""
        )

    def test_echo_content_visible(self, provider_factory, tmp_path: Path):
        server = _build_server(provider_factory(allow_submit=True))
        submitted = _call(
            server,
            "submit_job",
            {
                "argv": ["echo", "molq-mcp-log-marker"],
                "scheduler": "local",
                "cluster": "logbox",
            },
        )
        # Local jobs finish quickly; refresh + read.
        import time

        time.sleep(0.3)
        out = _call(
            server,
            "job_logs",
            {
                "job_id": submitted["job_id"],
                "stream": "stdout",
                "tail": 20,
                "refresh": True,
            },
        )
        text = out["streams"]["stdout"]["text"]
        if not out["streams"]["stdout"]["missing"]:
            assert "molq-mcp-log-marker" in text


class TestMolqCancelJob:
    def test_disabled_by_default(self, populated_db, provider_factory):
        from fastmcp.exceptions import ToolError

        db, _alias, job_id = populated_db
        server = _build_server(provider_factory(db_path=db, allow_submit=False))
        with pytest.raises(ToolError, match="disabled"):
            _call(server, "cancel_job", {"job_id": job_id})

    def test_cancel_running_or_done_job(self, provider_factory):
        server = _build_server(provider_factory(allow_submit=True))
        # Long-ish sleep so we can cancel while active; if already terminal,
        # cancel still returns a cancelled (or terminal) state from store.
        submitted = _call(
            server,
            "submit_job",
            {
                "argv": ["sleep", "30"],
                "scheduler": "local",
                "cluster": "cancelbox",
            },
        )
        result = _call(
            server,
            "cancel_job",
            {"job_id": submitted["job_id"]},
        )
        assert result["job_id"] == submitted["job_id"]
        assert result["state"] == "cancelled"


class TestMolqListDestinations:
    def test_returns_list(self, provider_factory):
        server = _build_server(provider_factory())
        rows = _call(server, "list_destinations", {"include_ssh": False})
        assert isinstance(rows, list)


class TestMolqListQueue:
    def test_local_returns_empty(self, provider_factory):
        server = _build_server(provider_factory())
        rows = _call(
            server,
            "list_queue",
            {"scheduler": "local", "cluster": "qbox"},
        )
        assert rows == []
