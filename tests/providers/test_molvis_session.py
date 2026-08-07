"""Pure-logic tests for the molvis viewer session layer (MCP-free).

Covers spec ``molvis-viewer-session`` AC-003 / AC-004 / AC-006 / AC-007 /
AC-009: the bounded event journal, the generic REPL ``execute_code``
machinery, and ``SessionStore`` lifecycle.

Nothing here imports ``fastmcp`` or ``molvis`` — the session module is the
MCP-free, dependency-free half of the provider, driven through a fake stage.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from molmcp.providers.molvis.session import (  # noqa: E402
    EventRecord,
    ExecResult,
    Journal,
    JournalPage,
    SessionExistsError,
    SessionNotFoundError,
    SessionStore,
    ViewerSession,
    execute_code,
)

EventCallback = Callable[[dict[str, Any]], None]


# ---------------------------------------------------------------------------
# Fakes
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


class ExplodingStageFactory:
    """Factory whose construction always fails."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, name: str) -> FakeStage:
        self.calls.append(name)
        raise RuntimeError("stage construction failed")


@pytest.fixture
def factory() -> RecordingStageFactory:
    return RecordingStageFactory()


@pytest.fixture
def store(factory: RecordingStageFactory) -> SessionStore:
    return SessionStore(factory)


# ---------------------------------------------------------------------------
# Journal — basics
# ---------------------------------------------------------------------------


class TestJournalAppend:
    def test_first_cursor_is_one(self) -> None:
        journal = Journal()
        assert journal.append("selection_changed", {"atom_ids": [1]}) == 1

    def test_cursors_are_strictly_monotonic(self) -> None:
        journal = Journal()
        cursors = [journal.append("mode_changed", {"mode": str(i)}) for i in range(5)]
        assert cursors == [1, 2, 3, 4, 5]

    def test_records_carry_type_and_cursor(self) -> None:
        journal = Journal()
        journal.append("frame_changed", {"frame_index": 3})
        (event,) = journal.poll().events
        assert (event.cursor, event.type) == (1, "frame_changed")

    def test_record_timestamp_is_a_float(self) -> None:
        journal = Journal()
        journal.append("hello_state", {})
        (event,) = journal.poll().events
        assert isinstance(event.ts, float)


class TestJournalPayloadVerbatim:
    def test_payload_round_trips_unmodified(self) -> None:
        payload: dict[str, Any] = {"atom_ids": [0, 2], "extra": {"nested": True}}
        journal = Journal()
        journal.append("selection_changed", payload)
        (event,) = journal.poll().events
        assert event.payload == {"atom_ids": [0, 2], "extra": {"nested": True}}

    def test_append_does_not_mutate_caller_payload(self) -> None:
        payload: dict[str, Any] = {"atom_ids": [0, 2]}
        journal = Journal()
        journal.append("selection_changed", payload)
        assert payload == {"atom_ids": [0, 2]}


class TestJournalPoll:
    def test_empty_journal_returns_no_events(self) -> None:
        page = Journal().poll()
        assert page.events == ()

    def test_empty_journal_echoes_since_as_next_cursor(self) -> None:
        page = Journal().poll(since=7)
        assert page.next_cursor == 7

    def test_empty_journal_is_not_truncated(self) -> None:
        assert Journal().poll().truncated is False

    def test_returns_only_events_after_since(self) -> None:
        journal = Journal()
        for i in range(4):
            journal.append("mode_changed", {"i": i})
        page = journal.poll(since=2)
        assert [e.cursor for e in page.events] == [3, 4]

    def test_next_cursor_is_last_returned_cursor(self) -> None:
        journal = Journal()
        for i in range(4):
            journal.append("mode_changed", {"i": i})
        assert journal.poll(since=2).next_cursor == 4

    def test_limit_caps_returned_events(self) -> None:
        journal = Journal()
        for i in range(10):
            journal.append("mode_changed", {"i": i})
        assert [e.cursor for e in journal.poll(since=0, limit=3).events] == [1, 2, 3]

    def test_limit_does_not_set_truncated(self) -> None:
        """``truncated`` means eviction, never ``limit`` paging."""
        journal = Journal()
        for i in range(10):
            journal.append("mode_changed", {"i": i})
        assert journal.poll(since=0, limit=3).truncated is False

    def test_polling_at_head_returns_empty_page(self) -> None:
        journal = Journal()
        journal.append("mode_changed", {"mode": "select"})
        assert journal.poll(since=1).events == ()

    def test_incremental_polls_never_repeat_events(self) -> None:
        journal = Journal()
        for i in range(6):
            journal.append("mode_changed", {"i": i})
        first = journal.poll(since=0, limit=4)
        second = journal.poll(since=first.next_cursor, limit=4)
        seen = [e.cursor for e in first.events] + [e.cursor for e in second.events]
        assert seen == [1, 2, 3, 4, 5, 6]


class TestJournalTruncation:
    def test_evicted_history_flags_truncated(self) -> None:
        journal = Journal(maxlen=3)
        for i in range(5):
            journal.append("mode_changed", {"i": i})
        assert journal.poll(since=0).truncated is True

    def test_ring_buffer_keeps_only_the_newest_events(self) -> None:
        journal = Journal(maxlen=3)
        for i in range(5):
            journal.append("mode_changed", {"i": i})
        assert [e.cursor for e in journal.poll(since=0).events] == [3, 4, 5]

    def test_no_truncation_when_since_is_still_retained(self) -> None:
        journal = Journal(maxlen=3)
        for i in range(5):
            journal.append("mode_changed", {"i": i})
        assert journal.poll(since=3).truncated is False

    def test_no_truncation_below_capacity(self) -> None:
        journal = Journal(maxlen=8)
        for i in range(5):
            journal.append("mode_changed", {"i": i})
        assert journal.poll(since=0).truncated is False


class TestJournalThreadSafety:
    def test_concurrent_append_and_poll_loses_no_cursor(self) -> None:
        """AC-007: molvis dispatches from the WS thread; poll runs on main."""
        total = 500
        journal = Journal(maxlen=1024)
        failures: list[BaseException] = []

        def _producer() -> None:
            try:
                for i in range(total):
                    journal.append("selection_changed", {"i": i})
            except BaseException as exc:  # pragma: no cover - defensive
                failures.append(exc)

        worker = threading.Thread(target=_producer, name="journal-producer")
        collected: list[int] = []
        cursor = 0
        worker.start()
        try:
            deadline = time.monotonic() + 30.0
            while len(collected) < total and time.monotonic() < deadline:
                page = journal.poll(since=cursor, limit=64)
                collected.extend(event.cursor for event in page.events)
                cursor = page.next_cursor
        finally:
            worker.join(timeout=30.0)

        drain = journal.poll(since=cursor, limit=total)
        collected.extend(event.cursor for event in drain.events)

        assert not failures
        assert collected == list(range(1, total + 1))


# ---------------------------------------------------------------------------
# Immutable value objects
# ---------------------------------------------------------------------------


class TestEventRecord:
    def test_is_frozen(self) -> None:
        record = EventRecord(cursor=1, type="selection_changed", ts=0.0, payload={})
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.cursor = 2  # type: ignore[misc]

    def test_field_names(self) -> None:
        names = [f.name for f in dataclasses.fields(EventRecord)]
        assert names == ["cursor", "type", "ts", "payload"]


class TestJournalPage:
    def test_is_frozen(self) -> None:
        page = JournalPage(events=(), next_cursor=0, truncated=False)
        with pytest.raises(dataclasses.FrozenInstanceError):
            page.next_cursor = 5  # type: ignore[misc]

    def test_events_are_a_tuple(self) -> None:
        journal = Journal()
        journal.append("mode_changed", {"mode": "view"})
        assert isinstance(journal.poll().events, tuple)


class TestExecResult:
    def test_is_frozen(self) -> None:
        result = execute_code("1", {})
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.stdout = "x"  # type: ignore[misc]

    def test_field_names(self) -> None:
        names = [f.name for f in dataclasses.fields(ExecResult)]
        assert names == ["stdout", "value_repr", "error", "truncated"]


# ---------------------------------------------------------------------------
# execute_code — generic REPL machinery (AC-004)
# ---------------------------------------------------------------------------


class TestExecuteCodeStdout:
    def test_print_lands_in_stdout(self) -> None:
        assert execute_code('print("hi")', {}).stdout == "hi\n"

    def test_print_has_no_value_repr(self) -> None:
        assert execute_code('print("hi")', {}).value_repr is None

    def test_print_has_no_error(self) -> None:
        assert execute_code('print("hi")', {}).error is None


class TestExecuteCodeValueRepr:
    def test_trailing_expression_returns_repr(self) -> None:
        assert execute_code("x = 2\nx + 40", {}).value_repr == "42"

    def test_statement_only_code_has_no_value_repr(self) -> None:
        assert execute_code("x = 5", {}).value_repr is None

    def test_repr_uses_repr_not_str(self) -> None:
        assert execute_code('"abc"', {}).value_repr == "'abc'"


class TestExecuteCodeNamespace:
    def test_namespace_persists_across_calls(self) -> None:
        namespace: dict[str, Any] = {}
        execute_code("y = 7", namespace)
        assert execute_code("y * 2", namespace).value_repr == "14"

    def test_definitions_land_in_the_caller_namespace(self) -> None:
        namespace: dict[str, Any] = {}
        execute_code("y = 7", namespace)
        assert namespace["y"] == 7

    def test_prebound_objects_are_visible(self) -> None:
        stage = FakeStage("s1")
        namespace: dict[str, Any] = {"stage": stage}
        assert execute_code("stage.name", namespace).value_repr == "'s1'"


class TestExecuteCodeErrors:
    def test_runtime_error_is_returned_not_raised(self) -> None:
        result = execute_code("1/0", {})
        assert result.error is not None

    def test_runtime_error_type(self) -> None:
        result = execute_code("1/0", {})
        assert result.error is not None
        assert result.error["type"] == "ZeroDivisionError"

    def test_runtime_error_carries_message(self) -> None:
        result = execute_code("1/0", {})
        assert result.error is not None
        assert isinstance(result.error["message"], str)
        assert result.error["message"]

    def test_runtime_error_carries_traceback(self) -> None:
        result = execute_code("1/0", {})
        assert result.error is not None
        assert "ZeroDivisionError" in result.error["traceback"]

    def test_syntax_error_is_structured(self) -> None:
        result = execute_code("def (:", {})
        assert result.error is not None
        assert result.error["type"] == "SyntaxError"

    def test_name_error_is_structured(self) -> None:
        result = execute_code("undefined_name", {})
        assert result.error is not None
        assert result.error["type"] == "NameError"

    def test_failed_run_has_no_value_repr(self) -> None:
        assert execute_code("1/0", {}).value_repr is None


class TestExecuteCodeOutputCap:
    def test_oversized_output_sets_truncated(self) -> None:
        result = execute_code('print("x" * 5000)', {}, output_limit=1024)
        assert result.truncated is True

    def test_oversized_output_respects_limit(self) -> None:
        result = execute_code('print("x" * 5000)', {}, output_limit=1024)
        assert len(result.stdout) <= 1024

    def test_small_output_is_not_truncated(self) -> None:
        assert execute_code('print("x" * 10)', {}, output_limit=1024).truncated is False

    def test_default_output_limit_is_32768(self) -> None:
        result = execute_code('print("x" * 40000)', {})
        assert result.truncated is True
        assert len(result.stdout) <= 32768

    def test_oversized_value_repr_is_capped(self) -> None:
        result = execute_code("'x' * 100_000", {}, output_limit=1024)
        assert result.value_repr is not None
        assert len(result.value_repr) <= 1024
        assert result.truncated is True
        assert result.error is None

    def test_small_value_repr_is_not_truncated(self) -> None:
        result = execute_code("'x' * 10", {}, output_limit=1024)
        assert result.value_repr == repr("x" * 10)
        assert result.truncated is False


# ---------------------------------------------------------------------------
# ViewerSession / errors
# ---------------------------------------------------------------------------


class TestViewerSession:
    def test_field_names(self) -> None:
        names = [f.name for f in dataclasses.fields(ViewerSession)]
        assert names == ["session_id", "stage", "namespace", "journal", "created_at"]

    def test_holds_its_collaborators(self) -> None:
        stage = FakeStage("s1")
        journal = Journal()
        session = ViewerSession(
            session_id="s1",
            stage=stage,
            namespace={"stage": stage},
            journal=journal,
            created_at=0.0,
        )
        assert (session.session_id, session.stage, session.journal) == (
            "s1",
            stage,
            journal,
        )


class TestSessionErrors:
    def test_exists_error_is_runtime_error(self) -> None:
        assert issubclass(SessionExistsError, RuntimeError)

    def test_not_found_error_is_key_error(self) -> None:
        assert issubclass(SessionNotFoundError, KeyError)


# ---------------------------------------------------------------------------
# SessionStore — open (AC-002, AC-003)
# ---------------------------------------------------------------------------


class TestSessionStoreOpen:
    def test_returns_a_viewer_session(self, store: SessionStore) -> None:
        assert isinstance(store.open("s1"), ViewerSession)

    def test_explicit_session_id_is_kept(self, store: SessionStore) -> None:
        assert store.open("s1").session_id == "s1"

    def test_stage_factory_receives_the_session_id(
        self, store: SessionStore, factory: RecordingStageFactory
    ) -> None:
        store.open("s1")
        assert factory.calls == ["s1"]

    def test_session_holds_the_factory_stage(
        self, store: SessionStore, factory: RecordingStageFactory
    ) -> None:
        session = store.open("s1")
        assert session.stage is factory.stages["s1"]

    def test_generated_id_is_a_non_empty_string(self, store: SessionStore) -> None:
        session_id = store.open().session_id
        assert isinstance(session_id, str) and session_id

    def test_generated_ids_are_unique(self, store: SessionStore) -> None:
        assert store.open().session_id != store.open().session_id

    def test_generated_id_is_passed_to_the_factory(
        self, store: SessionStore, factory: RecordingStageFactory
    ) -> None:
        session = store.open()
        assert factory.calls == [session.session_id]

    def test_namespace_prebinds_stage(self, store: SessionStore) -> None:
        session = store.open("s1")
        assert session.namespace["stage"] is session.stage

    def test_each_session_gets_its_own_namespace(self, store: SessionStore) -> None:
        first = store.open("s1")
        second = store.open("s2")
        assert first.namespace is not second.namespace

    def test_each_session_gets_its_own_journal(self, store: SessionStore) -> None:
        first = store.open("s1")
        second = store.open("s2")
        assert first.journal is not second.journal

    def test_duplicate_session_id_raises(self, store: SessionStore) -> None:
        store.open("s1")
        with pytest.raises(SessionExistsError):
            store.open("s1")

    def test_duplicate_open_does_not_rebuild_the_stage(
        self, store: SessionStore, factory: RecordingStageFactory
    ) -> None:
        store.open("s1")
        with pytest.raises(SessionExistsError):
            store.open("s1")
        assert factory.calls == ["s1"]


class TestSessionStoreOpenFailure:
    def test_factory_error_propagates(self) -> None:
        store = SessionStore(ExplodingStageFactory())
        with pytest.raises(RuntimeError, match="stage construction failed"):
            store.open("s1")

    def test_failed_open_registers_nothing(self) -> None:
        store = SessionStore(ExplodingStageFactory())
        with pytest.raises(RuntimeError):
            store.open("s1")
        assert store.list() == []

    def test_failed_open_leaves_no_gettable_session(self) -> None:
        store = SessionStore(ExplodingStageFactory())
        with pytest.raises(RuntimeError):
            store.open("s1")
        with pytest.raises(SessionNotFoundError):
            store.get("s1")


# ---------------------------------------------------------------------------
# SessionStore — event subscription (AC-006)
# ---------------------------------------------------------------------------


class TestSessionStoreEventSubscription:
    def test_open_subscribes_to_selection_changed(
        self, store: SessionStore, factory: RecordingStageFactory
    ) -> None:
        store.open("s1")
        assert factory.stages["s1"].callback_for("selection_changed") is not None

    def test_dispatched_event_lands_in_the_journal(
        self, store: SessionStore, factory: RecordingStageFactory
    ) -> None:
        session = store.open("s1")
        factory.stages["s1"].callback_for("selection_changed")({"atom_ids": [0, 2]})
        assert len(session.journal.poll(since=0).events) == 1

    def test_dispatched_event_keeps_its_type(
        self, store: SessionStore, factory: RecordingStageFactory
    ) -> None:
        session = store.open("s1")
        factory.stages["s1"].callback_for("selection_changed")({"atom_ids": [0, 2]})
        (event,) = session.journal.poll(since=0).events
        assert event.type == "selection_changed"

    def test_dispatched_payload_is_verbatim(
        self, store: SessionStore, factory: RecordingStageFactory
    ) -> None:
        session = store.open("s1")
        factory.stages["s1"].callback_for("selection_changed")({"atom_ids": [0, 2]})
        (event,) = session.journal.poll(since=0).events
        assert event.payload == {"atom_ids": [0, 2]}

    def test_events_are_isolated_per_session(
        self, store: SessionStore, factory: RecordingStageFactory
    ) -> None:
        first = store.open("s1")
        second = store.open("s2")
        factory.stages["s1"].callback_for("selection_changed")({"atom_ids": [1]})
        assert len(first.journal.poll().events) == 1
        assert second.journal.poll().events == ()

    def test_stage_without_on_still_opens(self) -> None:
        """Subscription is best-effort; a stage lacking ``on`` must not break."""

        class _BareStage:
            def __init__(self, name: str) -> None:
                self.name = name

            def close(self) -> None:
                return None

        store = SessionStore(_BareStage)
        assert store.open("s1").session_id == "s1"


# ---------------------------------------------------------------------------
# SessionStore — get / list / close (AC-009)
# ---------------------------------------------------------------------------


class TestSessionStoreGet:
    def test_returns_the_open_session(self, store: SessionStore) -> None:
        session = store.open("s1")
        assert store.get("s1") is session

    def test_unknown_session_raises(self, store: SessionStore) -> None:
        with pytest.raises(SessionNotFoundError):
            store.get("nope")


class TestSessionStoreList:
    def test_empty_store_lists_nothing(self, store: SessionStore) -> None:
        assert store.list() == []

    def test_rows_carry_session_id(self, store: SessionStore) -> None:
        store.open("s1")
        assert [row["session_id"] for row in store.list()] == ["s1"]

    def test_lists_every_open_session(self, store: SessionStore) -> None:
        store.open("s1")
        store.open("s2")
        assert {row["session_id"] for row in store.list()} == {"s1", "s2"}


class TestSessionStoreClose:
    def test_closes_the_stage(
        self, store: SessionStore, factory: RecordingStageFactory
    ) -> None:
        store.open("s1")
        store.close("s1")
        assert factory.stages["s1"].closed is True

    def test_session_is_no_longer_gettable(self, store: SessionStore) -> None:
        store.open("s1")
        store.close("s1")
        with pytest.raises(SessionNotFoundError):
            store.get("s1")

    def test_session_drops_out_of_list(self, store: SessionStore) -> None:
        store.open("s1")
        store.open("s2")
        store.close("s1")
        assert {row["session_id"] for row in store.list()} == {"s2"}

    def test_namespace_is_cleared(self, store: SessionStore) -> None:
        session = store.open("s1")
        session.namespace["mol"] = object()
        store.close("s1")
        assert len(session.namespace) == 0

    def test_closing_unknown_session_raises(self, store: SessionStore) -> None:
        with pytest.raises(SessionNotFoundError):
            store.close("nope")

    def test_id_can_be_reused_after_close(self, store: SessionStore) -> None:
        store.open("s1")
        store.close("s1")
        assert store.open("s1").session_id == "s1"


class TestOpenDoesNotBlockTheStore:
    """Building a stage is slow; holding the registry lock across it is not
    necessary. The production factory performs a browser handshake with a
    5x2s budget, and for that whole window every other session's list, get
    and close waited on a lock they had no reason to want."""

    def test_another_session_is_usable_while_one_is_opening(self):
        import threading

        released = threading.Event()
        building = threading.Event()

        def slow_factory(name: str):
            if name == "slow":
                building.set()
                released.wait(timeout=5)
            return FakeStage(name)

        store = SessionStore(slow_factory)
        store.open("ready")

        opener = threading.Thread(target=store.open, args=("slow",))
        opener.start()
        try:
            assert building.wait(timeout=5)
            # The store must answer for the session that is already live.
            assert [row["session_id"] for row in store.list()] == ["ready"]
            assert store.get("ready").session_id == "ready"
        finally:
            released.set()
            opener.join(timeout=5)

        assert {row["session_id"] for row in store.list()} == {"ready", "slow"}

    def test_a_duplicate_id_is_still_refused_before_any_stage_is_built(self):
        built: list[str] = []

        def counting_factory(name: str):
            built.append(name)
            return FakeStage(name)

        store = SessionStore(counting_factory)
        store.open("dup")

        with pytest.raises(SessionExistsError):
            store.open("dup")

        assert built == ["dup"]

    def test_a_failed_build_frees_the_id_for_a_retry(self):
        attempts: list[str] = []

        def flaky_factory(name: str):
            attempts.append(name)
            if len(attempts) == 1:
                raise RuntimeError("no browser")
            return FakeStage(name)

        store = SessionStore(flaky_factory)
        with pytest.raises(RuntimeError):
            store.open("retry")

        session = store.open("retry")

        assert session.session_id == "retry"
        assert attempts == ["retry", "retry"]
