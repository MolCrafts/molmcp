"""Hints must name tools that exist.

Every ``hint`` and error string here is read by an agent that will act on
it. Pointing at ``molcrafts_packages`` when the tool registered is
``packages`` sends it to a name no client resolves — the one failure mode
where the error message itself causes the next error.

Tool names are written bare, matching registration. How a client composes
them with the server name (``molcrafts__packages``, ``mcp__molcrafts__…``)
is the client's business, and hard-coding one client's spelling into a
payload is how the wrong ones got there.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from molmcp.collection.browse import open_ref, outline_source, search_scoped
from molmcp.guide import build_routing_guide

SRC = Path(__file__).resolve().parents[1] / "src" / "molmcp"

#: A plane id glued to a tool name by a single underscore — the mount-era
#: spelling the naming middleware rejects at registration time.
_MOUNT_ERA = re.compile(
    r"\b(molcrafts|molvis|molq|molexp)_"
    r"(packages|outline|open|compose|search|suggest|exec|close|refresh|"
    r"capabilities|poll_events|list_sessions|list_jobs|get_job|job_logs|"
    r"list_destinations|list_queue|submit_job|cancel_job|list_projects|"
    r"list_experiments|list_runs|workspace_layout|check_layout|"
    r"materialize_workspace|add_project|add_experiment|create_run|"
    r"validate_workflow)\b"
)

#: Tools that no longer exist at all.
_DELETED = ("molmcp_describe_symbol", "molmcp_outline", "molmcp_search_symbols")


def _hint_strings(payload: object) -> list[str]:
    """Every string an agent might read out of a tool payload."""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"hint", "error", "markdown"} and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_hint_strings(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_hint_strings(item))
    return found


class _EmptyCollection:
    sources: tuple = ()

    def info(self):
        return {"sources": {}}

    def search(self, *a, **k):
        return []

    def describe(self, *a, **k):
        return None


class TestRuntimeHints:
    @pytest.mark.parametrize(
        "payload",
        [
            outline_source(_EmptyCollection(), ""),
            outline_source(_EmptyCollection(), "nope"),
            open_ref(_EmptyCollection(), "nope"),
            search_scoped(_EmptyCollection(), "q", mode="executable"),
            build_routing_guide("draw a molecule", sources={}),
        ],
    )
    def test_no_payload_names_a_mount_era_tool(self, payload):
        offenders = [s for s in _hint_strings(payload) if _MOUNT_ERA.search(s)]

        assert offenders == []


class TestSourceIsClean:
    """A grep-level guard: the payloads above cannot cover every branch."""

    @pytest.mark.parametrize(
        "path", sorted(SRC.rglob("*.py")), ids=lambda p: str(p.name)
    )
    def test_no_module_emits_a_mount_era_tool_name(self, path: Path):
        # Two modules state the contract by quoting the spelling it bans;
        # for them the mount-era form appearing is the point.
        if path.name in {"naming.py", "provider.py"} and path.parent.name in {
            "middleware",
            "molmcp",
        }:
            pytest.skip("states the rejected spelling by definition")
        text = path.read_text(encoding="utf-8")
        offenders = sorted(set(_MOUNT_ERA.findall(text)))

        assert offenders == []

    @pytest.mark.parametrize(
        "path", sorted(SRC.rglob("*.py")), ids=lambda p: str(p.name)
    )
    def test_no_module_references_a_deleted_tool(self, path: Path):
        text = path.read_text(encoding="utf-8")

        assert [name for name in _DELETED if name in text] == []
