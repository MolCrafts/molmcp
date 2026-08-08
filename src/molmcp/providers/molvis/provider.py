"""``molvis`` MCP provider — a live viewer session driven by agent Python.

MCP is the Model Context Protocol, the contract an agent host uses to call
tools. This module declares seven of them, mounted under the provider's
``molvis`` namespace (``molvis_<name>``):

Read-only
  * ``list_sessions`` — which viewer sessions are live
  * ``poll_events`` — incremental viewer events since a cursor
  * ``capabilities`` — what this stage can do, and which build it is

Session control
  * ``open`` — start a viewer + its persistent Python namespace
  * ``close`` — tear the session down
  * ``exec`` — run Python in that namespace
  * ``refresh`` — re-read edited packages from disk

**This provider invents no API.** There is no ``draw`` tool, no
``show_smiles``, no command envelope: everything domain-shaped is written
by the agent as ordinary molvis / molpy Python inside ``exec``, so new
upstream capabilities need zero change here. What the provider owns is the
runtime discovery cannot see — a stage that stays alive, objects that
survive between tool calls, and an event feed to poll.

``capabilities`` and ``refresh`` are that same rule, not exceptions to it.
Neither defines a domain verb: one reflects the surface the live stage
already has, the other manipulates this process's module cache. Both exist
because an agent otherwise has to discover them by trial — probing with
``dir()`` and ``inspect``, or worse, testing a rebuilt package that the
process never actually reloaded and reporting the old behaviour as new.

Trust model: same-process local workbench, on par with a notebook kernel.
``exec`` is unsandboxed and ungated by design; the operator started this
server themselves.

The heavy ``molvis`` import stays inside the default stage factory, so the
provider is cheap to instantiate — and never imported at all when a stage
factory is injected. :meth:`MolvisProvider.probe` asks the import system
whether the package exists rather than importing it.

The agent-facing narrative for all of this — what the loop is and why the
surface is this small — is ``docs/guides/molvis-workbench.md``.
"""

from __future__ import annotations

from ..annotations import MUTATION, READ_ONLY
from ..base import ProviderBase, tool
from .capabilities import describe_stage, provenance
from .refresh import refresh_modules
from .session import (
    DEFAULT_POLL_LIMIT,
    SessionStore,
    Stage,
    StageFactory,
    execute_code,
)

#: Default packages ``refresh`` re-reads: the molecular stack an agent
#: edits between calls. Callers may name others explicitly.
DEFAULT_REFRESH_PREFIXES: tuple[str, ...] = ("molpy", "molvis")


def _molvis_stage(name: str) -> Stage:
    """Default stage factory: one live molvis viewer per session id.

    Uses a finite browser handshake (2s × 5 retries by default on
    :class:`~molvis.transport.WebSocketTransport`) so a closed tab cannot
    hang ``exec`` forever — the next RPC raises :class:`TimeoutError`
    with the page URL after a short wait.

    ``open_browser=False`` here on purpose: the ``open`` tool opens **one**
    tab with the correct ``session=<id>`` standalone URL. Letting the
    transport auto-open would race the agent and often produced a second
    tab (historically ``session=default`` then ``session=<id>``).
    """
    import molvis
    from molvis.transport.websocket import (
        DEFAULT_HANDSHAKE_RETRIES,
        DEFAULT_HANDSHAKE_TIMEOUT_S,
        WebSocketTransport,
    )

    transport = WebSocketTransport(
        open_browser=False,
        serve_page=True,
        handshake_timeout=DEFAULT_HANDSHAKE_TIMEOUT_S,
        handshake_retries=DEFAULT_HANDSHAKE_RETRIES,
        session=name,
    )
    return molvis.Stage(name=name, transport=transport)


def _stage_page_url(stage: object, session_id: str) -> str:
    """Standalone page URL for *session_id*, or empty if unavailable."""
    transport = getattr(stage, "_transport", None)
    endpoints_fn = getattr(transport, "page_endpoints", None)
    if not callable(endpoints_fn):
        return ""
    try:
        eps = endpoints_fn(session=session_id)
        return str(getattr(eps, "standalone_url", "") or "")
    except Exception:
        return ""


class MolvisProvider(ProviderBase):
    """Provider for a live molvis viewer session and its Python namespace.

    Args:
        stage_factory: Callable building the stage for a session id.
            Defaults to a real ``molvis.Stage``. Tests (and any embedder
            with its own transport) inject one instead, which removes the
            molvis dependency from this package entirely.
    """

    name = "molvis"
    upstream = "molcrafts-molvis"
    import_name = "molvis"

    def __init__(self, *, stage_factory: StageFactory | None = None) -> None:
        self._stage_factory = stage_factory
        self._store = SessionStore(self._open_stage)

    def probe(self) -> bool:
        """True when a stage factory is injected or ``molvis`` is importable.

        The injected factory is the whole reason this override exists: a
        stage supplied from outside is a served plane whether or not the
        upstream package — or a browser — is anywhere near this process.
        """
        if self._stage_factory is not None:
            return True
        return super().probe()

    def _open_stage(self, name: str) -> Stage:
        factory = self._stage_factory or _molvis_stage
        return factory(name)

    # -- session control -------------------------------------------------

    @tool(MUTATION, name="open")
    def open_session(self, session_id: str | None = None) -> dict[str, object]:
        """Start a viewer session and its persistent Python namespace.

        The namespace comes with ``stage`` pre-bound — the live molvis
        viewer object every later ``exec`` call operates on.

        Opens **exactly one** browser tab with ``page_url`` (standalone
        HTML + correct ``session=<id>``). Do not open ``connection_url``
        (raw WebSocket) in a second tab — that is for paste-into-settings
        only.

        Args:
            session_id: Explicit id to open. Omit to have one
                generated. Re-using a live id is an error, never an
                attach.

        Returns:
            Dict with ``ok``, ``session_id``, ``connection_url`` (ws://),
            and ``page_url`` (http:// standalone viewer). Empty strings
            when the stage has no browser endpoint.
        """
        session = self._store.open(session_id)
        stage = session.stage
        # Start transport (no auto-open — factory uses open_browser=False).
        connection_url = str(getattr(stage, "connection_url", "") or "")
        page_url = _stage_page_url(stage, session.session_id)
        if page_url:
            try:
                import webbrowser

                webbrowser.open(page_url)
            except Exception:
                pass
        return {
            "ok": True,
            "session_id": session.session_id,
            "connection_url": connection_url,
            "page_url": page_url,
        }

    @tool(MUTATION)
    def close(self, session_id: str) -> dict[str, object]:
        """Close a viewer session and discard its namespace.

        Everything the session held — the stage, and any object the
        agent built in it — is dropped. The id becomes reusable.

        Args:
            session_id: Session to tear down.

        Returns:
            Dict with ``ok`` and the closed ``session_id``.
        """
        self._store.close(session_id)
        return {"ok": True, "session_id": session_id}

    @tool(READ_ONLY)
    def list_sessions(self) -> list[dict[str, object]]:
        """List the live viewer sessions in this server process.

        Returns:
            Rows with ``session_id``, ``connected`` (is a browser
            attached right now), and ``created_at`` (open time, in
            seconds since the Unix epoch). Empty list when nothing is
            open.
        """
        return self._store.list()

    # -- the REPL --------------------------------------------------------

    @tool(MUTATION, name="exec")
    def exec_code(self, session_id: str, code: str) -> dict[str, object]:
        """Run Python in a session's namespace (read-eval-print loop).

        The namespace persists across calls, so this is a working
        session rather than a series of one-shot scripts: build an
        object once, keep using it. ``stage`` is pre-bound; import
        whatever the server environment has.

        One full turn of the loop — build and draw, let the user click
        the canvas, then read that selection back, edit, and redraw::

            # call 1 — build and draw
            import molpy as mp
            mol = mp.parser.parse_molecule("CC(=O)Oc1ccccc1C(=O)O")
            mol, _ = mp.Conformer(seed=42).generate(mol)
            stage.draw_frame(mol)

            # …the user clicks part of the structure; ``poll_events``
            # hands you a ``selection_changed`` record…

            # call 2 — `mol` is still alive, so nothing is rebuilt
            sel = stage.get_selected()
            # …edit mol with molpy…
            stage.clear()        # drawing stamps, it never wipes
            stage.draw_frame(mol)

        The API truth for every line above lives upstream, not here:
        look symbols up on the molcrafts plane (its ``search`` then
        its ``open``) before writing
        code — this provider will not validate or correct it. For the
        stage itself, ``capabilities`` reads the surface off the live
        object, which is the one source that cannot be out of date.

        Browser closed / not open: ``stage.draw`` / ``clear`` wait a
        short handshake budget (default 5×2s) then raise
        ``TimeoutError`` — they never hang indefinitely. The result
        then includes ``connection_url`` / ``page_url`` so the agent
        can ask the user to reopen the tab. The session itself stays
        live (namespace intact); closing a tab is normal, not a
        session teardown.

        Args:
            session_id: Session whose namespace to run in.
            code: Python source. A trailing expression is echoed as
                ``value_repr``, the way a REPL echoes a value.

        Returns:
            Dict with ``ok`` (the code ran without raising),
            ``stdout``, ``value_repr``, ``error``
            (``{type, message, traceback}`` or ``None``), and
            ``truncated`` (stdout hit the output cap). When the error
            is a missing browser, also ``connected: false`` and
            reconnect URLs. Code that raises returns ``ok: false`` —
            it is a result, not a tool failure. An unknown
            ``session_id`` *is* a failure.
        """
        session = self._store.get(session_id)
        result = execute_code(code, session.namespace)
        out: dict[str, object] = {
            "ok": result.error is None,
            "stdout": result.stdout,
            "value_repr": result.value_repr,
            "error": result.error,
            "truncated": result.truncated,
        }
        # Surface reconnect URLs when the browser is gone so agents do
        # not spin — closing a tab is normal; hanging is not.
        if result.error is not None:
            stage = session.stage
            connected = bool(getattr(stage, "connected", False))
            out["connected"] = connected
            if not connected or "browser" in (
                (result.error.get("message") or "").lower()
            ):
                url = str(getattr(stage, "connection_url", "") or "")
                if url:
                    out["connection_url"] = url
                endpoints_fn = getattr(
                    getattr(stage, "_transport", None),
                    "page_endpoints",
                    None,
                )
                if callable(endpoints_fn):
                    try:
                        eps = endpoints_fn(session=session.session_id)
                        out["page_url"] = str(getattr(eps, "standalone_url", "") or "")
                    except Exception:
                        pass
        return out

    # -- runtime facts ---------------------------------------------------

    @tool(READ_ONLY)
    def capabilities(
        self,
        session_id: str,
        pattern: str | None = None,
    ) -> dict[str, object]:
        """List what a session's live stage can do, and which build it is.

        Read off the stage object itself, so it is never out of date
        with the installed molvis — and it answers the two questions
        an index cannot. First, *how* to reach a name: a ``property``
        carries no signature because reading it is not a call, and
        calling one raises something as unhelpful as ``'int' object is
        not callable``. Second, whether the build being described is
        the one on disk.

        Prefer this over probing with ``dir(stage)`` inside ``exec``.

        Args:
            session_id: Session whose stage to describe.
            pattern: Case-insensitive substring filter on the name,
                e.g. ``"draw"``. Omit for the whole surface.

        Returns:
            Dict with ``ok``, ``session_id``, ``capabilities`` (rows of
            ``{name, kind, signature, summary}``, sorted by name), and
            ``provenance`` (installed versions plus mapped compiled
            extensions). ``provenance.restart_required`` means a native
            library was rebuilt after this process started: the stage
            is running the older one, and ``refresh`` cannot fix it.
        """
        session = self._store.get(session_id)
        found = describe_stage(session.stage, pattern=pattern)
        return {
            "ok": True,
            "session_id": session_id,
            "capabilities": [cap.as_dict() for cap in found],
            "provenance": provenance(),
        }

    @tool(MUTATION)
    def refresh(
        self,
        packages: list[str] | None = None,
    ) -> dict[str, object]:
        """Re-read edited packages from disk, and say what could not be.

        Drops the named packages from this process's module cache so
        the next import inside ``exec`` reads the current source. That
        is the whole mechanism, and it only covers pure Python.

        A compiled extension is mapped once per process and cannot be
        swapped, so a rebuilt ``molrs`` stays the old one until the
        server restarts. This tool never pretends otherwise: when
        ``restart_required`` comes back true, reconnect the MCP server
        before trusting any result, because the code just exercised is
        not the code on disk.

        Live objects are not migrated either. A stage, a molecule, and
        anything else an earlier ``exec`` bound keeps pointing at the
        classes it was built from — rebuild them after refreshing, or
        open a new session.

        Args:
            packages: Top-level package names to refresh. Defaults to
                ``["molpy", "molvis"]``.

        Returns:
            Dict with ``ok``, ``purged`` (modules dropped),
            ``native`` (mapped extensions, each with
            ``changed_since_start``), and ``restart_required``.
        """
        prefixes = tuple(packages) if packages else DEFAULT_REFRESH_PREFIXES
        report = refresh_modules(prefixes)
        return {"ok": True, **report.as_dict()}

    # -- the user's half of the session ----------------------------------

    @tool(READ_ONLY)
    def poll_events(
        self,
        session_id: str,
        since: int = 0,
        limit: int = DEFAULT_POLL_LIMIT,
    ) -> dict[str, object]:
        """Read the journalled viewer events newer than a cursor.

        The canvas is the user's half of the session: they click and
        switch modes while the agent works. Those notifications are
        journalled as they arrive; this tool drains them. Feed
        ``next_cursor`` back as ``since`` to page forward without
        repeats. Payloads are upstream's, verbatim.

        The journal carries a fixed set of event names —
        ``selection_changed``, ``mode_changed``, ``frame_changed``,
        ``hello_state`` — because molvis subscribes by exact name and
        has no wildcard subscription yet. Anything outside that set is
        not lost history; it was never journalled. Listen for it
        yourself with ``stage.on(...)`` inside ``exec`` if you need it.

        Args:
            session_id: Session to read from.
            since: Last cursor seen; 0 starts from the beginning.
            limit: Max events to return per call (default 50).

        Returns:
            Dict with ``ok``, ``events``, ``next_cursor``, and
            ``truncated``. Each event is ``{cursor, type, ts,
            payload}``, where ``ts`` is the arrival time in seconds
            since the Unix epoch. ``truncated`` means events were lost
            to the journal's bounded history, not merely held back by
            ``limit``.
        """
        page = self._store.get(session_id).journal.poll(since=since, limit=limit)
        return {
            "ok": True,
            "events": [
                {
                    "cursor": event.cursor,
                    "type": event.type,
                    "ts": event.ts,
                    "payload": event.payload,
                }
                for event in page.events
            ],
            "next_cursor": page.next_cursor,
            "truncated": page.truncated,
        }
