"""Viewer-session primitives for the ``molvis`` provider (MCP-free).

Three collaborators, none of which knows anything about MCP — or about
molecules:

* :class:`Journal` — bounded, lock-protected ring buffer of viewer events.
  molvis dispatches from its websocket thread while agents poll from the
  MCP worker, so cursors are handed out under a lock.
* :func:`execute_code` — generic REPL (read-eval-print loop) machinery:
  stdout capture, trailing-expression ``repr``, structured traceback,
  output cap. It is the same mechanism a notebook kernel implements; it
  has no opinion about the code it runs.
* :class:`SessionStore` — registry of live :class:`ViewerSession` objects,
  each owning a persistent namespace with ``stage`` pre-bound.

Domain vocabulary lives upstream (molvis / molpy public API), reached by
the agent through :func:`execute_code`. The single exception is
:data:`SUBSCRIBED_EVENTS` — see its comment.
"""

from __future__ import annotations

import ast
import io
import threading
import time
import traceback
import uuid
from collections import deque
from collections.abc import Callable
from contextlib import redirect_stdout
from dataclasses import dataclass
from itertools import islice
from typing import Protocol

#: Default :class:`Journal` capacity, in event records: how much viewer
#: history one session retains before the oldest events are evicted.
DEFAULT_JOURNAL_MAXLEN = 512

#: Default page size for :meth:`Journal.poll` and the ``poll_events`` tool.
DEFAULT_POLL_LIMIT = 50

#: Default :func:`execute_code` cap, in characters, on each of captured
#: stdout and the trailing expression's ``repr``.
DEFAULT_OUTPUT_LIMIT = 32768

_EXEC_FILENAME = "<molvis-exec>"

#: Event names mirrored into a session journal on open.
#:
#: The ONLY upstream vocabulary in this package, and it is on loan: the
#: molvis EventBus dispatches by exact name with no wildcard subscription
#: (``events.py``), so a journal cannot say "everything" yet. When molvis
#: grows ``on("*")`` this tuple is deleted, not extended. Both the short
#: and the ``event.``-prefixed form are accepted upstream
#: (``normalize_event_name``); the short form is stored as the record type.
SUBSCRIBED_EVENTS: tuple[str, ...] = (
    "selection_changed",
    "mode_changed",
    "frame_changed",
    "hello_state",
)


class Stage(Protocol):
    """Structural contract molmcp needs from a live viewer object.

    Deliberately one method wide: ``close`` is the only member the
    provider *requires*, because tearing a stage down is the only thing it
    ever does to one. Everything else an agent wants — drawing, selection,
    camera — is reached by writing molvis Python inside ``exec``, so those
    method names never appear here.

    Three further members are read with ``getattr`` and are therefore
    optional; an object offering only ``close`` still works, it just
    degrades:

    * ``on(event, callback)`` — subscribed on open (see
      :meth:`SessionStore.open`). A stage without it gets no journal, so
      ``poll_events`` stays empty forever.
    * ``connected`` — reported by :meth:`SessionStore.list`; ``False``
      when absent.
    * ``connection_url`` — returned by the ``open`` tool; ``""`` when
      absent.
    """

    def close(self) -> None: ...


#: Builds the stage for a session id (``molvis.Stage`` in production).
StageFactory = Callable[[str], Stage]


@dataclass(frozen=True, slots=True)
class EventRecord:
    """One journalled viewer event.

    Attributes:
        cursor: Strictly monotonic position, starting at 1.
        type: Short event name, e.g. ``selection_changed``.
        ts: Wall-clock time of the append (``time.time()``).
        payload: Upstream params, verbatim — never mapped or summarized.
    """

    cursor: int
    type: str
    ts: float
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class JournalPage:
    """One incremental read of a :class:`Journal`.

    Attributes:
        events: Records with ``cursor > since``, oldest first.
        next_cursor: Cursor to pass as ``since`` next time.
        truncated: Whether wanted events were lost to ring eviction.
            Paging via ``limit`` never sets this.
    """

    events: tuple[EventRecord, ...]
    next_cursor: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class ExecResult:
    """Outcome of one :func:`execute_code` run.

    Attributes:
        stdout: Captured standard output, capped at ``output_limit``.
        value_repr: ``repr`` of the trailing expression, capped at
            ``output_limit`` just like ``stdout``. ``None`` for
            statement-only code, for a trailing ``None``, and whenever
            ``error`` is set.
        error: ``{"type", "message", "traceback"}`` when the run raised,
            else ``None``.
        truncated: Whether either ``stdout`` or ``value_repr`` was cut at
            the cap.
    """

    stdout: str
    value_repr: str | None
    error: dict[str, str] | None
    truncated: bool


@dataclass(frozen=True, slots=True)
class ViewerSession:
    """A live viewer plus the Python session that drives it.

    Attributes:
        session_id: Registry key; also the stage name.
        stage: The live viewer object built by the stage factory.
        namespace: ``exec`` globals, persistent across calls, with
            ``stage`` pre-bound. Cleared on close.
        journal: Event ring buffer fed by the stage's notifications.
        created_at: Wall-clock open time.
    """

    session_id: str
    stage: Stage
    namespace: dict[str, object]
    journal: Journal
    created_at: float


class SessionExistsError(RuntimeError):
    """Raised when opening a session id that is already live."""


class SessionNotFoundError(KeyError):
    """Raised when a session id is not (or no longer) live."""


class Journal:
    """Bounded event ring buffer with monotonic cursors, safe across threads.

    Appends arrive on the molvis websocket thread; polls arrive on the MCP
    worker. One lock covers both the cursor counter and the buffer, so a
    cursor can never be reused, skipped, or observed out of order.

    Args:
        maxlen: Ring capacity, defaulting to
            :data:`DEFAULT_JOURNAL_MAXLEN`. Older events are evicted once
            it is exceeded, which is what ``truncated`` reports on poll.

    Raises:
        ValueError: *maxlen* is below 1.
    """

    def __init__(self, maxlen: int = DEFAULT_JOURNAL_MAXLEN) -> None:
        if maxlen < 1:
            raise ValueError(f"maxlen must be >= 1, got {maxlen}")
        self._lock = threading.Lock()
        self._events: deque[EventRecord] = deque(maxlen=maxlen)
        self._next_cursor = 1

    @property
    def maxlen(self) -> int:
        """Ring capacity in records."""
        return self._events.maxlen or 0

    def append(self, type_: str, payload: dict[str, object]) -> int:
        """Record one event and return its cursor.

        Args:
            type_: Short event name, stored as the record type.
            payload: Upstream params, stored verbatim (not copied, not
                mapped); callers must not mutate them afterwards.

        Returns:
            The cursor assigned to the new record (first is 1).
        """
        with self._lock:
            cursor = self._next_cursor
            self._next_cursor += 1
            self._events.append(
                EventRecord(
                    cursor=cursor,
                    type=type_,
                    ts=time.time(),
                    payload=payload,
                )
            )
        return cursor

    def poll(self, since: int = 0, limit: int = DEFAULT_POLL_LIMIT) -> JournalPage:
        """Read events newer than *since*.

        Args:
            since: Last cursor the caller has seen; 0 reads from the start.
            limit: Max records to return, defaulting to
                :data:`DEFAULT_POLL_LIMIT`. Paging is not truncation.

        Returns:
            A :class:`JournalPage`. ``next_cursor`` is the last returned
            cursor, or *since* when the page is empty, so a caller can
            always feed it straight back in.

        Raises:
            ValueError: *limit* is negative.
        """
        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        with self._lock:
            oldest = self._events[0].cursor if self._events else self._next_cursor
            # Anything in (since, oldest) fell out of the ring unread.
            truncated = since < oldest - 1
            events = tuple(islice((e for e in self._events if e.cursor > since), limit))
        next_cursor = events[-1].cursor if events else since
        return JournalPage(events=events, next_cursor=next_cursor, truncated=truncated)


class _EventWriter:
    """Callback that files one event kind into a journal, payload verbatim."""

    def __init__(self, journal: Journal, event_type: str) -> None:
        self._journal = journal
        self._event_type = event_type

    def __call__(self, payload: dict[str, object]) -> None:
        self._journal.append(self._event_type, payload)


def _error_dict(exc: BaseException) -> dict[str, str]:
    """Structure an exception for transport (never re-raises)."""
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": "".join(traceback.format_exception(exc)),
    }


def _clip(text: str, limit: int) -> tuple[str, bool]:
    """Cut *text* to *limit* characters, reporting whether it was cut."""
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def execute_code(
    code: str,
    namespace: dict[str, object],
    *,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
) -> ExecResult:
    """Run *code* in *namespace* with read-eval-print loop (REPL) semantics.

    Generic kernel machinery: the code is parsed, everything but a
    trailing expression is executed as statements, and that trailing
    expression is evaluated so its ``repr`` can be reported the way a REPL
    echoes a value. Definitions land in *namespace*, which is why an
    object built by one call is still there for the next.

    Failures are values, not exceptions: syntax errors and runtime errors
    alike come back in ``error``. (``BaseException`` — ``SystemExit``,
    ``KeyboardInterrupt`` — is deliberately left to propagate; those are
    process-level signals, not results.)

    Args:
        code: Python source. No sandbox, no import restrictions — this is
            a local workbench, on par with a notebook kernel.
        namespace: Persistent ``exec`` globals for the session.
        output_limit: Max characters to keep of each reported text, so a
            large object cannot flood an agent's context. It applies to
            captured ``stdout`` and to the trailing expression's
            ``value_repr`` alike — printing a huge object and echoing one
            are the same hazard — and either cut sets ``truncated``.

    Returns:
        An :class:`ExecResult`; ``error is None`` means the run succeeded.
    """
    try:
        module = ast.parse(code, filename=_EXEC_FILENAME)
    except SyntaxError as exc:
        return ExecResult(
            stdout="",
            value_repr=None,
            error=_error_dict(exc),
            truncated=False,
        )

    statements = module.body
    trailing: ast.Expr | None = None
    if statements and isinstance(statements[-1], ast.Expr):
        trailing = statements[-1]
        statements = statements[:-1]

    buffer = io.StringIO()
    value_repr: str | None = None
    error: dict[str, str] | None = None
    try:
        with redirect_stdout(buffer):
            if statements:
                block = ast.Module(body=statements, type_ignores=module.type_ignores)
                exec(compile(block, _EXEC_FILENAME, "exec"), namespace)
            if trailing is not None:
                expression = ast.Expression(body=trailing.value)
                value = eval(compile(expression, _EXEC_FILENAME, "eval"), namespace)
                if value is not None:
                    value_repr = repr(value)
    except Exception as exc:
        value_repr = None
        error = _error_dict(exc)

    stdout, stdout_cut = _clip(buffer.getvalue(), output_limit)
    repr_cut = False
    if value_repr is not None:
        value_repr, repr_cut = _clip(value_repr, output_limit)
    return ExecResult(
        stdout=stdout,
        value_repr=value_repr,
        error=error,
        truncated=stdout_cut or repr_cut,
    )


class SessionStore:
    """Process-local registry of live viewer sessions.

    One store per provider instance. The stage factory is injected, so the
    store never imports molvis and tests never open a browser.

    Args:
        stage_factory: Builds the stage for a session id.
        journal_maxlen: Ring capacity for each session's journal,
            defaulting to :data:`DEFAULT_JOURNAL_MAXLEN`.
    """

    def __init__(
        self,
        stage_factory: StageFactory,
        *,
        journal_maxlen: int = DEFAULT_JOURNAL_MAXLEN,
    ) -> None:
        self._stage_factory = stage_factory
        self._journal_maxlen = journal_maxlen
        self._lock = threading.Lock()
        self._sessions: dict[str, ViewerSession] = {}
        #: Ids claimed but not yet registered, so a concurrent open of the
        #: same id is refused rather than building a second stage for it.
        self._opening: set[str] = set()

    def open(self, session_id: str | None = None) -> ViewerSession:
        """Build a stage and register a session around it.

        Args:
            session_id: Explicit id; ``None`` generates a fresh one.

        Returns:
            The registered :class:`ViewerSession`, its namespace holding
            the stage under ``stage``.

        Raises:
            SessionExistsError: *session_id* is already live, or another
                caller is opening it right now. The existing session is left
                untouched and no stage is built.
            Exception: Whatever the stage factory raises propagates
                unchanged. The stage is built before anything is
                registered, so a failed open leaves the store untouched
                and the id free to retry.
        """
        # Claim the id under the lock, then build outside it. The production
        # factory performs a browser handshake with a multi-second budget,
        # and holding the registry lock across that made every other
        # session's list/get/close wait on it for no reason.
        with self._lock:
            resolved = self._generate_id() if session_id is None else session_id
            if resolved in self._sessions or resolved in self._opening:
                raise SessionExistsError(f"viewer session already open: {resolved}")
            self._opening.add(resolved)

        try:
            stage = self._stage_factory(resolved)
            journal = Journal(maxlen=self._journal_maxlen)
            self._subscribe(stage, journal)
            session = ViewerSession(
                session_id=resolved,
                stage=stage,
                namespace={"stage": stage},
                journal=journal,
                created_at=time.time(),
            )
            with self._lock:
                self._sessions[resolved] = session
        finally:
            # A failed build registers nothing and frees the id to retry.
            with self._lock:
                self._opening.discard(resolved)
        return session

    def get(self, session_id: str) -> ViewerSession:
        """Return the live session for *session_id*.

        Raises:
            SessionNotFoundError: No such session (never opened, or closed).
        """
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(f"no such viewer session: {session_id}")
        return session

    def list(self) -> list[dict[str, object]]:
        """Summarize every live session.

        Returns:
            One row per live session, in the order the sessions were
            opened, each carrying ``session_id``, ``connected`` (whether a
            browser is currently attached — ``False`` for a stage that
            does not expose the attribute at all), and ``created_at``
            (wall-clock open time).
        """
        with self._lock:
            sessions = list(self._sessions.values())
        return [
            {
                "session_id": session.session_id,
                "connected": bool(getattr(session.stage, "connected", False)),
                "created_at": session.created_at,
            }
            for session in sessions
        ]

    def close(self, session_id: str) -> None:
        """Tear down a session: close the stage, drop its namespace, unregister.

        The id becomes reusable. Deregistration happens even if the stage
        raises on close, so a broken viewer cannot wedge its id forever;
        the error still surfaces to the caller.

        Raises:
            SessionNotFoundError: No such session.
        """
        session = self.get(session_id)
        try:
            session.stage.close()
        finally:
            session.namespace.clear()
            with self._lock:
                self._sessions.pop(session_id, None)

    def _generate_id(self) -> str:
        """Mint an unused session id (caller holds the lock)."""
        while True:
            candidate = f"molvis-{uuid.uuid4().hex[:12]}"
            if candidate not in self._sessions and candidate not in self._opening:
                return candidate

    def _subscribe(self, stage: Stage, journal: Journal) -> None:
        """Mirror the stage's event notifications into *journal*.

        Best effort: a stage without ``on`` (a bare test double, a future
        transport) simply opens without a feed rather than failing.
        """
        subscribe = getattr(stage, "on", None)
        if not callable(subscribe):
            return
        for event_type in SUBSCRIBED_EVENTS:
            subscribe(event_type, _EventWriter(journal, event_type))
