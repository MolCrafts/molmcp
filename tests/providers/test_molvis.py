"""``MolvisProvider`` — the 5 exec-primitive tools over a live viewer session.

Covers spec ``molvis-viewer-session`` AC-001 … AC-009: tool surface,
annotations, open/list/close lifecycle, the ``exec`` REPL round trip with a
persistent namespace, and cursor-based ``poll_events``.

Provider-level tests drive a **fake stage factory** (no molvis, no browser,
no network). The single in-process pin test skips unless real molvis is
installed; ``molvis`` is never imported at module level.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("molmcp", reason="molcrafts-molmcp not installed")
pytest.importorskip("fastmcp", reason="fastmcp not installed")

from fastmcp.exceptions import ToolError  # noqa: E402

from molmcp import CollectionIndex, Registry, create_server  # noqa: E402
from molmcp.providers.molvis import MolvisProvider  # noqa: E402

EventCallback = Callable[[dict[str, Any]], None]

_TOOL_NAMES = frozenset(
    {
        "molvis_open",
        "molvis_close",
        "molvis_list_sessions",
        "molvis_exec",
        "molvis_poll_events",
    }
)

_PROVIDER_PKG = (
    Path(__file__).resolve().parents[2] / "src" / "molmcp" / "providers" / "molvis"
)


# ---------------------------------------------------------------------------
# Fakes + server harness
# ---------------------------------------------------------------------------


class FakeStage:
    """Stand-in for ``molvis.Molvis`` — records subscriptions and close."""

    def __init__(self, name: str) -> None:
        self.name: str = name
        self.connected: bool = False
        self.connection_url: str = "ws://fake"
        self.subscriptions: dict[str, EventCallback] = {}
        self.closed: bool = False

    def on(self, name: str, cb: EventCallback) -> None:
        self.subscriptions[name] = cb

    def close(self) -> None:
        self.closed = True

    # -- test helper -------------------------------------------------------

    def callback_for(self, event: str) -> EventCallback:
        """Return the callback subscribed for *event* (``event.`` prefix ok)."""
        for key, cb in self.subscriptions.items():
            if key.removeprefix("event.") == event:
                return cb
        raise AssertionError(
            f"no subscription for {event!r}; got {sorted(self.subscriptions)}"
        )


class RecordingStageFactory:
    """``Callable[[str], FakeStage]`` that keeps every stage it built."""

    def __init__(self) -> None:
        self.stages: dict[str, FakeStage] = {}
        self.calls: list[str] = []

    def __call__(self, name: str) -> FakeStage:
        self.calls.append(name)
        stage = FakeStage(name)
        self.stages[name] = stage
        return stage


def _build_server(provider: MolvisProvider) -> Any:
    return create_server(
        name="molvis-test",
        collection=CollectionIndex([], Registry()),
        providers=[provider],
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
        text = result.content[0].text
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
    return sc


def _list_tools(server: Any) -> list[Any]:
    return asyncio.run(server.list_tools())


@pytest.fixture
def factory() -> RecordingStageFactory:
    return RecordingStageFactory()


@pytest.fixture
def server(factory: RecordingStageFactory) -> Any:
    return _build_server(MolvisProvider(stage_factory=factory))


@pytest.fixture
def session_id(server: Any) -> str:
    opened = _call(server, "molvis_open", {})
    return str(opened["session_id"])


# ---------------------------------------------------------------------------
# Protocol + register guard (AC-001)
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_implements_molmcp_protocol(self) -> None:
        from molmcp import Provider

        assert isinstance(MolvisProvider(), Provider)

    def test_provider_name(self) -> None:
        assert MolvisProvider().name == "molvis"

    def test_stage_factory_is_keyword_only(self) -> None:
        factory = RecordingStageFactory()
        with pytest.raises(TypeError):
            MolvisProvider(factory)  # type: ignore[misc]


class TestRegisterGuard:
    @pytest.mark.skipif(
        importlib.util.find_spec("molvis") is not None,
        reason="molvis installed — the missing-dependency guard cannot trigger",
    )
    def test_register_without_molvis_raises_runtime_error(self) -> None:
        with pytest.raises(RuntimeError, match="molvis"):
            MolvisProvider().register(MagicMock())

    def test_injected_factory_registers_without_molvis(
        self, factory: RecordingStageFactory
    ) -> None:
        """An injected stage factory replaces the molvis import entirely."""
        server = _build_server(MolvisProvider(stage_factory=factory))
        names = {t.name for t in _list_tools(server)}
        assert "molvis_open" in names


# ---------------------------------------------------------------------------
# Tool surface + annotations (AC-005)
# ---------------------------------------------------------------------------


class TestToolSurface:
    def test_exactly_five_tools(self, server: Any) -> None:
        names = {t.name for t in _list_tools(server) if t.name.startswith("molvis_")}
        assert names == set(_TOOL_NAMES)

    @pytest.mark.parametrize(
        "tool_name", ["molvis_list_sessions", "molvis_poll_events"]
    )
    def test_read_only_tools(self, server: Any, tool_name: str) -> None:
        tools = {t.name: t for t in _list_tools(server)}
        assert getattr(tools[tool_name].annotations, "readOnlyHint", False) is True

    @pytest.mark.parametrize(
        "tool_name", ["molvis_open", "molvis_close", "molvis_exec"]
    )
    def test_mutating_tools_are_not_read_only(
        self, server: Any, tool_name: str
    ) -> None:
        tools = {t.name: t for t in _list_tools(server)}
        assert getattr(tools[tool_name].annotations, "readOnlyHint", True) is False

    @pytest.mark.parametrize(
        "tool_name", ["molvis_open", "molvis_close", "molvis_exec"]
    )
    def test_mutating_tools_are_destructive(self, server: Any, tool_name: str) -> None:
        tools = {t.name: t for t in _list_tools(server)}
        assert getattr(tools[tool_name].annotations, "destructiveHint", False) is True


class TestZeroDomainKnowledge:
    """AC-005: no molpy import, no env reads inside the provider package."""

    def test_no_molpy_import(self) -> None:
        assert _PROVIDER_PKG.is_dir()
        for path in sorted(_PROVIDER_PKG.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert not any(a.name.split(".")[0] == "molpy" for a in node.names)
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert node.module.split(".")[0] != "molpy"

    def test_no_environment_reads(self) -> None:
        assert _PROVIDER_PKG.is_dir()
        for path in sorted(_PROVIDER_PKG.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            assert "os.environ" not in text, f"{path.name} reads os.environ"
            assert "getenv" not in text, f"{path.name} reads getenv"


# ---------------------------------------------------------------------------
# open / list_sessions / close (AC-002, AC-009)
# ---------------------------------------------------------------------------


class TestMolvisOpen:
    def test_open_is_ok(self, server: Any) -> None:
        assert _call(server, "molvis_open", {})["ok"] is True

    def test_open_returns_a_session_id(self, server: Any) -> None:
        opened = _call(server, "molvis_open", {})
        assert isinstance(opened["session_id"], str) and opened["session_id"]

    def test_open_returns_connection_url(self, server: Any) -> None:
        assert _call(server, "molvis_open", {})["connection_url"] == "ws://fake"

    def test_open_honours_explicit_session_id(self, server: Any) -> None:
        opened = _call(server, "molvis_open", {"session_id": "viewer-1"})
        assert opened["session_id"] == "viewer-1"

    def test_open_builds_a_stage(
        self, server: Any, factory: RecordingStageFactory
    ) -> None:
        _call(server, "molvis_open", {"session_id": "viewer-1"})
        assert factory.calls == ["viewer-1"]

    def test_duplicate_session_id_errors(self, server: Any) -> None:
        _call(server, "molvis_open", {"session_id": "viewer-1"})
        with pytest.raises((RuntimeError, ToolError)) as excinfo:
            _call(server, "molvis_open", {"session_id": "viewer-1"})
        message = str(excinfo.value).lower()
        assert "viewer-1" in message or "exist" in message


class TestMolvisListSessions:
    def test_empty_before_open(self, server: Any) -> None:
        assert _call(server, "molvis_list_sessions", {}) == []

    def test_lists_the_open_session(self, server: Any, session_id: str) -> None:
        rows = _call(server, "molvis_list_sessions", {})
        assert session_id in {row["session_id"] for row in rows}


class TestMolvisClose:
    def test_close_is_ok(self, server: Any, session_id: str) -> None:
        assert _call(server, "molvis_close", {"session_id": session_id})["ok"] is True

    def test_close_removes_from_list(self, server: Any, session_id: str) -> None:
        _call(server, "molvis_close", {"session_id": session_id})
        rows = _call(server, "molvis_list_sessions", {})
        assert session_id not in {row["session_id"] for row in rows}

    def test_close_tears_down_the_stage(
        self, server: Any, factory: RecordingStageFactory, session_id: str
    ) -> None:
        _call(server, "molvis_close", {"session_id": session_id})
        assert factory.stages[session_id].closed is True

    def test_closing_unknown_session_errors(self, server: Any) -> None:
        with pytest.raises((RuntimeError, ToolError)):
            _call(server, "molvis_close", {"session_id": "nope"})


# ---------------------------------------------------------------------------
# exec (AC-003, AC-004)
# ---------------------------------------------------------------------------


class TestMolvisExec:
    def test_stage_is_prebound(self, server: Any, session_id: str) -> None:
        result = _call(
            server,
            "molvis_exec",
            {"session_id": session_id, "code": "stage.connected"},
        )
        assert result["value_repr"] == "False"

    def test_success_is_ok(self, server: Any, session_id: str) -> None:
        result = _call(
            server,
            "molvis_exec",
            {"session_id": session_id, "code": "stage.connected"},
        )
        assert result["ok"] is True

    def test_stdout_is_captured(self, server: Any, session_id: str) -> None:
        result = _call(
            server,
            "molvis_exec",
            {"session_id": session_id, "code": 'print("hello")'},
        )
        assert result["stdout"] == "hello\n"

    def test_namespace_persists_between_calls(
        self, server: Any, session_id: str
    ) -> None:
        _call(server, "molvis_exec", {"session_id": session_id, "code": "z = 1"})
        result = _call(
            server, "molvis_exec", {"session_id": session_id, "code": "z + 1"}
        )
        assert result["value_repr"] == "2"

    def test_namespaces_are_isolated_per_session(self, server: Any) -> None:
        first = _call(server, "molvis_open", {"session_id": "a"})["session_id"]
        second = _call(server, "molvis_open", {"session_id": "b"})["session_id"]
        _call(server, "molvis_exec", {"session_id": first, "code": "z = 1"})
        result = _call(server, "molvis_exec", {"session_id": second, "code": "z"})
        assert result["ok"] is False

    def test_exception_returns_not_raises(self, server: Any, session_id: str) -> None:
        result = _call(server, "molvis_exec", {"session_id": session_id, "code": "1/0"})
        assert result["ok"] is False

    def test_exception_type_is_structured(self, server: Any, session_id: str) -> None:
        result = _call(server, "molvis_exec", {"session_id": session_id, "code": "1/0"})
        assert result["error"]["type"] == "ZeroDivisionError"

    def test_exception_carries_traceback(self, server: Any, session_id: str) -> None:
        result = _call(server, "molvis_exec", {"session_id": session_id, "code": "1/0"})
        assert "ZeroDivisionError" in result["error"]["traceback"]

    def test_server_survives_a_failing_exec(self, server: Any, session_id: str) -> None:
        _call(server, "molvis_exec", {"session_id": session_id, "code": "1/0"})
        result = _call(
            server, "molvis_exec", {"session_id": session_id, "code": "40 + 2"}
        )
        assert result["value_repr"] == "42"

    def test_unknown_session_errors(self, server: Any) -> None:
        with pytest.raises((RuntimeError, ToolError)):
            _call(server, "molvis_exec", {"session_id": "nope", "code": "1"})


# ---------------------------------------------------------------------------
# poll_events (AC-006)
# ---------------------------------------------------------------------------


class TestMolvisPollEvents:
    def test_empty_journal_returns_no_events(
        self, server: Any, session_id: str
    ) -> None:
        page = _call(
            server, "molvis_poll_events", {"session_id": session_id, "since": 0}
        )
        assert page["events"] == []

    def test_empty_journal_is_not_truncated(self, server: Any, session_id: str) -> None:
        page = _call(
            server, "molvis_poll_events", {"session_id": session_id, "since": 0}
        )
        assert page["truncated"] is False

    def test_dispatched_event_is_delivered(
        self, server: Any, factory: RecordingStageFactory, session_id: str
    ) -> None:
        factory.stages[session_id].callback_for("selection_changed")(
            {"atom_ids": [0, 2]}
        )
        page = _call(
            server, "molvis_poll_events", {"session_id": session_id, "since": 0}
        )
        assert len(page["events"]) == 1

    def test_event_type_is_preserved(
        self, server: Any, factory: RecordingStageFactory, session_id: str
    ) -> None:
        factory.stages[session_id].callback_for("selection_changed")(
            {"atom_ids": [0, 2]}
        )
        page = _call(
            server, "molvis_poll_events", {"session_id": session_id, "since": 0}
        )
        assert page["events"][0]["type"] == "selection_changed"

    def test_payload_is_verbatim(
        self, server: Any, factory: RecordingStageFactory, session_id: str
    ) -> None:
        factory.stages[session_id].callback_for("selection_changed")(
            {"atom_ids": [0, 2]}
        )
        page = _call(
            server, "molvis_poll_events", {"session_id": session_id, "since": 0}
        )
        assert page["events"][0]["payload"] == {"atom_ids": [0, 2]}

    def test_cursor_advances(
        self, server: Any, factory: RecordingStageFactory, session_id: str
    ) -> None:
        factory.stages[session_id].callback_for("selection_changed")(
            {"atom_ids": [0, 2]}
        )
        page = _call(
            server, "molvis_poll_events", {"session_id": session_id, "since": 0}
        )
        assert page["next_cursor"] == page["events"][0]["cursor"]

    def test_repolling_at_the_cursor_is_empty(
        self, server: Any, factory: RecordingStageFactory, session_id: str
    ) -> None:
        factory.stages[session_id].callback_for("selection_changed")(
            {"atom_ids": [0, 2]}
        )
        first = _call(
            server, "molvis_poll_events", {"session_id": session_id, "since": 0}
        )
        second = _call(
            server,
            "molvis_poll_events",
            {"session_id": session_id, "since": first["next_cursor"]},
        )
        assert second["events"] == []

    def test_unknown_session_errors(self, server: Any) -> None:
        with pytest.raises((RuntimeError, ToolError)):
            _call(server, "molvis_poll_events", {"session_id": "nope", "since": 0})


# ---------------------------------------------------------------------------
# In-process pin against real molvis — no browser, no network (AC-008)
# ---------------------------------------------------------------------------


class TestInProcessPin:
    def test_exec_and_events_round_trip_through_real_stage(self) -> None:
        molvis = pytest.importorskip("molvis", reason="molvis not installed")

        def _invoke(method: str, params: dict[str, Any]) -> dict[str, Any]:
            """In-process RPC stub standing in for the browser router."""
            return {}

        def _stage_factory(name: str) -> Any:
            return molvis.Molvis.from_inprocess(_invoke, name=name, gui=False)

        server = _build_server(MolvisProvider(stage_factory=_stage_factory))
        opened = _call(server, "molvis_open", {"session_id": "molmcp-inprocess-pin"})
        session_id = str(opened["session_id"])
        try:
            probe = _call(
                server,
                "molvis_exec",
                {"session_id": session_id, "code": "stage.connected"},
            )
            assert probe["ok"] is True
            assert probe["error"] is None
            assert probe["value_repr"] in {"True", "False"}

            dispatched = _call(
                server,
                "molvis_exec",
                {
                    "session_id": session_id,
                    "code": (
                        "stage.events.dispatch("
                        "'event.selection_changed', {'atom_ids': [1]})"
                    ),
                },
            )
            assert dispatched["ok"] is True

            page = _call(
                server,
                "molvis_poll_events",
                {"session_id": session_id, "since": 0},
            )
            events = [e for e in page["events"] if e["type"] == "selection_changed"]
            assert events
            assert events[-1]["payload"]["atom_ids"] == [1]
        finally:
            _call(server, "molvis_close", {"session_id": session_id})
