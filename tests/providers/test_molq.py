"""Tests for ``MolqProvider`` — one read-only ``molq_list_jobs`` tool.

Helper-level tests (``_serialize``, ``_resolve_db_path``, register-guard)
run without ``molq`` installed; integration tests skip cleanly.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("molmcp", reason="molcrafts-molmcp not installed")
pytest.importorskip("fastmcp", reason="fastmcp not installed")

from molmcp.providers.molq import MolqProvider  # noqa: E402
from molmcp.providers.molq.provider import (  # noqa: E402
    _resolve_db_path,
    _serialize,
)


def _build_server(provider: MolqProvider) -> Any:
    from molmcp import create_server

    return create_server(
        name="molq-test",
        providers=[provider],
        discover_entry_points=False,
        import_roots=None,
    )


def _tool(server: Any, name: str) -> Any:
    import asyncio

    tool = asyncio.run(server.get_tool(name))
    if tool is None:
        raise KeyError(f"Tool '{name}' not registered")
    return tool.fn


def _list_tools(server: Any) -> list[Any]:
    import asyncio

    return asyncio.run(server.list_tools())


@pytest.fixture
def provider_factory(tmp_path):
    pytest.importorskip("molq", reason="molcrafts-molq not installed")

    def _make(*, db_path=None) -> MolqProvider:
        return MolqProvider(db_path=db_path or tmp_path / "jobs.db")

    return _make


@pytest.fixture
def populated_db(tmp_path):
    """Submit one local 'true' job and return the (db_path, alias, job_id)."""
    pytest.importorskip("molq", reason="molcrafts-molq not installed")

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
        # str(Path) is platform-dependent (/ on POSIX, \ on Windows); compute
        # the expected value from str() rather than hardcoding a POSIX form.
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


class TestResolveDbPath:
    def test_memory_passes_through(self):
        assert _resolve_db_path(":memory:") == ":memory:"

    def test_arg_wins_over_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MOLQ_DB_PATH", str(tmp_path / "env.db"))
        out = _resolve_db_path(tmp_path / "arg.db")
        assert out == tmp_path / "arg.db"

    def test_env_used_when_arg_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MOLQ_DB_PATH", str(tmp_path / "env.db"))
        out = _resolve_db_path(None)
        assert out == tmp_path / "env.db"

    def test_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("MOLQ_DB_PATH", raising=False)
        assert _resolve_db_path(None) is None

    def test_expands_user_home(self, monkeypatch, tmp_path):
        # Path.expanduser() reads $HOME on POSIX, $USERPROFILE on Windows —
        # set both so the test runs uniformly on either platform.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        out = _resolve_db_path("~/jobs.db")
        assert out == tmp_path / "jobs.db"


# ---------------------------------------------------------------------------
# Register-time guard — no molq install needed
# ---------------------------------------------------------------------------


class TestRegisterGuard:
    def test_register_without_molq_raises_runtime_error(self, monkeypatch):
        # Force `import molq` inside register() to fail.
        monkeypatch.setitem(sys.modules, "molq", None)
        with pytest.raises(RuntimeError, match="molcrafts-molq"):
            MolqProvider().register(MagicMock())


# ---------------------------------------------------------------------------
# Protocol conformance — molq must be installed
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_implements_molmcp_protocol(self):
        from molmcp import Provider

        p = MolqProvider()
        assert isinstance(p, Provider)
        assert p.name == "molq"

    def test_tool_set(self, provider_factory):
        """One read-only tool — molq_list_jobs."""
        server = _build_server(provider_factory())
        names = {t.name for t in _list_tools(server)}
        assert names == {"molq_list_jobs"}

    def test_tool_is_read_only_closed_world(self, provider_factory):
        server = _build_server(provider_factory())
        for tool in _list_tools(server):
            ann = getattr(tool, "annotations", None)
            assert ann is not None
            assert getattr(ann, "readOnlyHint", False) is True
            assert getattr(ann, "openWorldHint", True) is False


# ---------------------------------------------------------------------------
# Tool semantics — molq must be installed
# ---------------------------------------------------------------------------


class TestMolqListJobs:
    def test_returns_submitted_job(self, populated_db, provider_factory):
        db, alias, job_id = populated_db
        server = _build_server(provider_factory(db_path=db))
        records = _tool(server, "molq_list_jobs")(
            cluster_name=alias, include_terminal=True
        )
        assert any(r["job_id"] == job_id for r in records)

    def test_empty_db_returns_empty_list(self, provider_factory):
        server = _build_server(provider_factory())
        records = _tool(server, "molq_list_jobs")()
        assert records == []

    def test_excludes_terminal_by_default(self, populated_db, provider_factory):
        db, alias, _ = populated_db
        server = _build_server(provider_factory(db_path=db))
        records = _tool(server, "molq_list_jobs")(cluster_name=alias)
        # ``true`` finishes immediately, so the record is terminal and
        # filtered out by default.
        assert records == []

    def test_all_clusters_when_omitted(self, populated_db, provider_factory):
        db, _, job_id = populated_db
        server = _build_server(provider_factory(db_path=db))
        records = _tool(server, "molq_list_jobs")(include_terminal=True)
        assert any(r["job_id"] == job_id for r in records)


# ---------------------------------------------------------------------------
# Tool dispatches with the right kwargs — no molq install needed (we stub
# the store) so we can verify that ``limit`` flows to list_all_records and
# not to list_records (per-cluster).
# ---------------------------------------------------------------------------


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

        # Bypass the eager `import molq` in register() with a sentinel module.
        monkeypatch.setitem(sys.modules, "molq", SimpleNamespace())

        provider = MolqProvider()
        monkeypatch.setattr(provider, "_open_store", lambda: _StubStore())

        from molmcp import create_server

        server = create_server(
            name="molq-stubbed",
            providers=[provider],
            discover_entry_points=False,
            import_roots=None,
        )
        fn = _tool(server, "molq_list_jobs")

        captured.clear()
        fn(cluster_name="alpha", limit=5)
        assert captured["scope"] == "per_cluster"
        assert captured["cluster"] == "alpha"
        assert "limit" not in captured  # limit not forwarded per-cluster
        assert captured["closed"] is True

        captured.clear()
        fn(limit=7)
        assert captured["scope"] == "all"
        assert captured["limit"] == 7
