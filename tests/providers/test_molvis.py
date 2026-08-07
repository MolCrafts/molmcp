"""``MolvisProvider`` — the exec-primitive tools over a live viewer session.

Covers spec ``molvis-viewer-session`` AC-001 … AC-009: tool surface,
annotations, open/list/close lifecycle, the ``exec`` REPL round trip with a
persistent namespace, and cursor-based ``poll_events``. Plus the two
runtime-fact tools the spec did not anticipate — ``capabilities`` (what
the live stage can do) and ``refresh`` (re-read edited packages, and admit
what could not be re-read).

Provider-level tests drive a **fake stage factory** (no real browser, no
network). ``webbrowser.open`` is mocked so ``molvis_open`` never spawns tabs.
"""

from __future__ import annotations

import ast
import asyncio
import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastmcp.exceptions import ToolError  # noqa: E402

from molmcp import create_plane  # noqa: E402
from molmcp.providers.molvis import MolvisProvider  # noqa: E402

# CollectionIndex/Registry no longer wrap provider planes.

EventCallback = Callable[[dict[str, Any]], None]


@pytest.fixture(autouse=True)
def _no_browser_tabs(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """``molvis_open`` calls ``webbrowser.open`` — never open real tabs in CI/tests."""
    mock_open = MagicMock(return_value=True)
    monkeypatch.setattr("webbrowser.open", mock_open)
    yield mock_open


_TOOL_NAMES = frozenset(
    {
        "open",
        "close",
        "list_sessions",
        "exec",
        "poll_events",
        "capabilities",
        "refresh",
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
        # Minimal transport face for exec reconnect-URL enrichment.
        self._transport = type(
            "T",
            (),
            {
                "page_endpoints": staticmethod(
                    lambda session: type(
                        "E",
                        (),
                        {"standalone_url": f"http://fake/?session={session}"},
                    )()
                )
            },
        )()

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
    opened = _call(server, "open", {})
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
    def test_injected_factory_registers_without_touching_default_stage(
        self, factory: RecordingStageFactory
    ) -> None:
        """An injected stage factory replaces the molvis import entirely."""
        server = _build_server(MolvisProvider(stage_factory=factory))
        names = {t.name for t in _list_tools(server)}
        assert "open" in names


# ---------------------------------------------------------------------------
# Tool surface + annotations (AC-005)
# ---------------------------------------------------------------------------


class TestToolSurface:
    def test_exactly_the_declared_tools(self, server: Any) -> None:
        names = {t.name for t in _list_tools(server)}
        assert names == set(_TOOL_NAMES)

    @pytest.mark.parametrize(
        "tool_name",
        ["list_sessions", "poll_events", "capabilities"],
    )
    def test_read_only_tools(self, server: Any, tool_name: str) -> None:
        tools = {t.name: t for t in _list_tools(server)}
        assert getattr(tools[tool_name].annotations, "read_only_hint", False) is True

    @pytest.mark.parametrize(
        "tool_name",
        ["open", "close", "exec", "refresh"],
    )
    def test_mutating_tools_are_not_read_only(
        self, server: Any, tool_name: str
    ) -> None:
        tools = {t.name: t for t in _list_tools(server)}
        assert getattr(tools[tool_name].annotations, "read_only_hint", True) is False

    @pytest.mark.parametrize(
        "tool_name",
        ["open", "close", "exec", "refresh"],
    )
    def test_mutating_tools_are_destructive(self, server: Any, tool_name: str) -> None:
        tools = {t.name: t for t in _list_tools(server)}
        assert getattr(tools[tool_name].annotations, "destructive_hint", False) is True


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
        assert _call(server, "open", {})["ok"] is True

    def test_open_returns_a_session_id(self, server: Any) -> None:
        opened = _call(server, "open", {})
        assert isinstance(opened["session_id"], str) and opened["session_id"]

    def test_open_returns_connection_url(
        self, server: Any, _no_browser_tabs: MagicMock
    ) -> None:
        opened = _call(server, "open", {})
        assert opened["connection_url"] == "ws://fake"
        assert opened.get("page_url", "").startswith("http://fake/")
        # Exactly one open attempt with the standalone page URL (not ws://).
        _no_browser_tabs.assert_called_once()
        opened_url = _no_browser_tabs.call_args[0][0]
        assert opened_url.startswith("http://fake/")
        assert "session=" in opened_url

    def test_open_honours_explicit_session_id(self, server: Any) -> None:
        opened = _call(server, "open", {"session_id": "viewer-1"})
        assert opened["session_id"] == "viewer-1"

    def test_open_builds_a_stage(
        self, server: Any, factory: RecordingStageFactory
    ) -> None:
        _call(server, "open", {"session_id": "viewer-1"})
        assert factory.calls == ["viewer-1"]

    def test_duplicate_session_id_errors(self, server: Any) -> None:
        _call(server, "open", {"session_id": "viewer-1"})
        with pytest.raises((RuntimeError, ToolError)) as excinfo:
            _call(server, "open", {"session_id": "viewer-1"})
        message = str(excinfo.value).lower()
        assert "viewer-1" in message or "exist" in message


class TestMolvisListSessions:
    def test_empty_before_open(self, server: Any) -> None:
        assert _call(server, "list_sessions", {}) == []

    def test_lists_the_open_session(self, server: Any, session_id: str) -> None:
        rows = _call(server, "list_sessions", {})
        assert session_id in {row["session_id"] for row in rows}


class TestMolvisClose:
    def test_close_is_ok(self, server: Any, session_id: str) -> None:
        assert _call(server, "close", {"session_id": session_id})["ok"] is True

    def test_close_removes_from_list(self, server: Any, session_id: str) -> None:
        _call(server, "close", {"session_id": session_id})
        rows = _call(server, "list_sessions", {})
        assert session_id not in {row["session_id"] for row in rows}

    def test_close_tears_down_the_stage(
        self, server: Any, factory: RecordingStageFactory, session_id: str
    ) -> None:
        _call(server, "close", {"session_id": session_id})
        assert factory.stages[session_id].closed is True

    def test_closing_unknown_session_errors(self, server: Any) -> None:
        with pytest.raises((RuntimeError, ToolError)):
            _call(server, "close", {"session_id": "nope"})


# ---------------------------------------------------------------------------
# exec (AC-003, AC-004)
# ---------------------------------------------------------------------------


class TestMolvisExec:
    def test_stage_is_prebound(self, server: Any, session_id: str) -> None:
        result = _call(
            server,
            "exec",
            {"session_id": session_id, "code": "stage.connected"},
        )
        assert result["value_repr"] == "False"

    def test_success_is_ok(self, server: Any, session_id: str) -> None:
        result = _call(
            server,
            "exec",
            {"session_id": session_id, "code": "stage.connected"},
        )
        assert result["ok"] is True

    def test_stdout_is_captured(self, server: Any, session_id: str) -> None:
        result = _call(
            server,
            "exec",
            {"session_id": session_id, "code": 'print("hello")'},
        )
        assert result["stdout"] == "hello\n"

    def test_namespace_persists_between_calls(
        self, server: Any, session_id: str
    ) -> None:
        _call(server, "exec", {"session_id": session_id, "code": "z = 1"})
        result = _call(server, "exec", {"session_id": session_id, "code": "z + 1"})
        assert result["value_repr"] == "2"

    def test_namespaces_are_isolated_per_session(self, server: Any) -> None:
        first = _call(server, "open", {"session_id": "a"})["session_id"]
        second = _call(server, "open", {"session_id": "b"})["session_id"]
        _call(server, "exec", {"session_id": first, "code": "z = 1"})
        result = _call(server, "exec", {"session_id": second, "code": "z"})
        assert result["ok"] is False

    def test_exception_returns_not_raises(self, server: Any, session_id: str) -> None:
        result = _call(server, "exec", {"session_id": session_id, "code": "1/0"})
        assert result["ok"] is False

    def test_exception_type_is_structured(self, server: Any, session_id: str) -> None:
        result = _call(server, "exec", {"session_id": session_id, "code": "1/0"})
        assert result["error"]["type"] == "ZeroDivisionError"

    def test_browser_timeout_includes_reconnect_urls(
        self, server: Any, session_id: str
    ) -> None:
        """Closed tab / no browser → TimeoutError must carry page URLs."""
        code = (
            "raise TimeoutError("
            '"No browser connected after 5 attempt(s). '
            'Viewer tab is not connected")'
        )
        result = _call(
            server,
            "exec",
            {"session_id": session_id, "code": code},
        )
        assert result["ok"] is False
        assert result["error"]["type"] == "TimeoutError"
        assert result.get("connected") is False
        assert result.get("connection_url") == "ws://fake"
        assert "session=" in str(result.get("page_url") or "")

    def test_exception_carries_traceback(self, server: Any, session_id: str) -> None:
        result = _call(server, "exec", {"session_id": session_id, "code": "1/0"})
        assert "ZeroDivisionError" in result["error"]["traceback"]

    def test_server_survives_a_failing_exec(self, server: Any, session_id: str) -> None:
        _call(server, "exec", {"session_id": session_id, "code": "1/0"})
        result = _call(server, "exec", {"session_id": session_id, "code": "40 + 2"})
        assert result["value_repr"] == "42"

    def test_unknown_session_errors(self, server: Any) -> None:
        with pytest.raises((RuntimeError, ToolError)):
            _call(server, "exec", {"session_id": "nope", "code": "1"})


# ---------------------------------------------------------------------------
# poll_events (AC-006)
# ---------------------------------------------------------------------------


class TestMolvisPollEvents:
    def test_empty_journal_returns_no_events(
        self, server: Any, session_id: str
    ) -> None:
        page = _call(server, "poll_events", {"session_id": session_id, "since": 0})
        assert page["events"] == []

    def test_empty_journal_is_not_truncated(self, server: Any, session_id: str) -> None:
        page = _call(server, "poll_events", {"session_id": session_id, "since": 0})
        assert page["truncated"] is False

    def test_dispatched_event_is_delivered(
        self, server: Any, factory: RecordingStageFactory, session_id: str
    ) -> None:
        factory.stages[session_id].callback_for("selection_changed")(
            {"atom_ids": [0, 2]}
        )
        page = _call(server, "poll_events", {"session_id": session_id, "since": 0})
        assert len(page["events"]) == 1

    def test_event_type_is_preserved(
        self, server: Any, factory: RecordingStageFactory, session_id: str
    ) -> None:
        factory.stages[session_id].callback_for("selection_changed")(
            {"atom_ids": [0, 2]}
        )
        page = _call(server, "poll_events", {"session_id": session_id, "since": 0})
        assert page["events"][0]["type"] == "selection_changed"

    def test_payload_is_verbatim(
        self, server: Any, factory: RecordingStageFactory, session_id: str
    ) -> None:
        factory.stages[session_id].callback_for("selection_changed")(
            {"atom_ids": [0, 2]}
        )
        page = _call(server, "poll_events", {"session_id": session_id, "since": 0})
        assert page["events"][0]["payload"] == {"atom_ids": [0, 2]}

    def test_cursor_advances(
        self, server: Any, factory: RecordingStageFactory, session_id: str
    ) -> None:
        factory.stages[session_id].callback_for("selection_changed")(
            {"atom_ids": [0, 2]}
        )
        page = _call(server, "poll_events", {"session_id": session_id, "since": 0})
        assert page["next_cursor"] == page["events"][0]["cursor"]

    def test_repolling_at_the_cursor_is_empty(
        self, server: Any, factory: RecordingStageFactory, session_id: str
    ) -> None:
        factory.stages[session_id].callback_for("selection_changed")(
            {"atom_ids": [0, 2]}
        )
        first = _call(server, "poll_events", {"session_id": session_id, "since": 0})
        second = _call(
            server,
            "poll_events",
            {"session_id": session_id, "since": first["next_cursor"]},
        )
        assert second["events"] == []

    def test_unknown_session_errors(self, server: Any) -> None:
        with pytest.raises((RuntimeError, ToolError)):
            _call(server, "poll_events", {"session_id": "nope", "since": 0})


# ---------------------------------------------------------------------------
# capabilities / refresh
# ---------------------------------------------------------------------------


class TestMolvisCapabilities:
    def test_lists_the_live_stage_surface(self, server: Any, session_id: str) -> None:
        found = _call(server, "capabilities", {"session_id": session_id})
        names = {row["name"] for row in found["capabilities"]}
        # FakeStage's own surface, read off the instance — nothing declared
        # in the provider.
        assert {"on", "close", "connected", "connection_url"} <= names

    def test_method_and_attribute_are_distinguished(
        self, server: Any, session_id: str
    ) -> None:
        rows = {
            row["name"]: row
            for row in _call(server, "capabilities", {"session_id": session_id})[
                "capabilities"
            ]
        }
        assert rows["close"]["kind"] == "method"
        assert rows["connected"]["kind"] == "attribute"

    def test_pattern_narrows_the_listing(self, server: Any, session_id: str) -> None:
        found = _call(
            server,
            "capabilities",
            {"session_id": session_id, "pattern": "connect"},
        )
        assert {row["name"] for row in found["capabilities"]} == {
            "connected",
            "connection_url",
        }

    def test_carries_a_restart_verdict(self, server: Any, session_id: str) -> None:
        found = _call(server, "capabilities", {"session_id": session_id})
        assert isinstance(found["provenance"]["restart_required"], bool)

    def test_unknown_session_is_an_error(self, server: Any) -> None:
        with pytest.raises((ToolError, RuntimeError)):
            _call(server, "capabilities", {"session_id": "nope"})


@pytest.fixture
def throwaway_package(tmp_path: Path) -> str:
    """An importable package this test may safely drop from sys.modules."""
    name = "molmcp_refresh_probe"
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("VALUE = 1\n")
    sys.path.insert(0, str(tmp_path))
    __import__(name)
    try:
        yield name
    finally:
        sys.path.remove(str(tmp_path))
        for mod in [m for m in list(sys.modules) if m.startswith(name)]:
            del sys.modules[mod]


class TestMolvisRefresh:
    def test_refreshing_an_unloaded_package_is_a_no_op(self, server: Any) -> None:
        report = _call(server, "refresh", {"packages": ["molmcp_absent_fixture"]})
        assert report["ok"] is True
        assert report["purged"] == []

    def test_reports_a_restart_verdict(self, server: Any) -> None:
        report = _call(server, "refresh", {"packages": ["molmcp_absent_fixture"]})
        assert report["restart_required"] is False

    def test_purges_a_loaded_pure_python_package(
        self, server: Any, throwaway_package: str
    ) -> None:
        report = _call(server, "refresh", {"packages": [throwaway_package]})
        assert throwaway_package in report["purged"]

    def test_refuses_to_purge_the_standard_library(self, server: Any) -> None:
        """This used to reach for `json` as a convenient stand-in.

        Dropping a stdlib module does not reload it for anyone: modules that
        already imported it keep the old object while a re-import installs a
        new one, so their exception classes stop matching. It broke
        `except json.JSONDecodeError` across the rest of this suite.
        """
        import json

        before = sys.modules["json"]

        report = _call(server, "refresh", {"packages": ["json"]})

        assert sys.modules["json"] is before
        assert report["purged"] == []
        assert report["refused"] == ["json"]
        assert json.loads("{}") == {}

    def test_defaults_to_the_molecular_stack(self, server: Any) -> None:
        report = _call(server, "refresh", {})
        assert report["ok"] is True
        assert isinstance(report["purged"], list)
