"""Tests for ``MolqProvider`` — one read-only ``molq_list_jobs`` tool.

Skips cleanly when molq is not installed.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("molq", reason="molcrafts-molq not installed")
pytest.importorskip("molmcp", reason="molcrafts-molmcp not installed")
pytest.importorskip("fastmcp", reason="fastmcp not installed")

from molq import Cluster  # noqa: E402
from molq.store import JobStore  # noqa: E402
from molq.submitor import Submitor  # noqa: E402

from molmcp.providers.molq import MolqProvider  # noqa: E402


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
    def _make(*, db_path=None) -> MolqProvider:
        return MolqProvider(db_path=db_path or tmp_path / "jobs.db")

    return _make


@pytest.fixture
def populated_db(tmp_path):
    """Submit one local 'true' job and return the (db_path, alias, job_id)."""
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

    def test_tool_is_read_only(self, provider_factory):
        server = _build_server(provider_factory())
        for tool in _list_tools(server):
            ann = getattr(tool, "annotations", None)
            assert ann is not None
            assert getattr(ann, "readOnlyHint", False) is True


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
