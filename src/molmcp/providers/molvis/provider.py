"""``molvis`` MCP provider — a live viewer session driven by agent Python.

MCP is the Model Context Protocol, the contract an agent host uses to call
tools. This module registers five of them, mounted under the provider's
``molvis`` namespace (``molvis_<name>``):

Read-only
  * ``list_sessions`` — which viewer sessions are live
  * ``poll_events`` — incremental viewer events since a cursor

Session control
  * ``open`` — start a viewer + its persistent Python namespace
  * ``close`` — tear the session down
  * ``exec`` — run Python in that namespace

**This provider invents no API.** There is no ``draw`` tool, no
``show_smiles``, no command envelope: everything domain-shaped is written
by the agent as ordinary molvis / molpy Python inside ``exec``, so new
upstream capabilities need zero change here. What the provider owns is the
runtime discovery cannot see — a stage that stays alive, objects that
survive between tool calls, and an event feed to poll.

Trust model: same-process local workbench, on par with a notebook kernel.
``exec`` is unsandboxed and ungated by design; the operator started this
server themselves.

The heavy ``molvis`` import stays inside :meth:`MolvisProvider.register`
and the default stage factory, so the provider is cheap to instantiate —
and never imported at all when a stage factory is injected.

The agent-facing narrative for all of this — what the loop is and why the
surface is this small — is ``docs/guides/molvis-workbench.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .session import (
    DEFAULT_POLL_LIMIT,
    SessionStore,
    Stage,
    StageFactory,
    execute_code,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP


def _molvis_stage(name: str) -> Stage:
    """Default stage factory: one live molvis viewer per session id."""
    import molvis

    return molvis.Stage(name=name)


class MolvisProvider:
    """Provider for a live molvis viewer session and its Python namespace.

    Args:
        stage_factory: Callable building the stage for a session id.
            Defaults to a real ``molvis.Stage``. Tests (and any embedder
            with its own transport) inject one instead, which removes the
            molvis dependency from this package entirely.
    """

    name = "molvis"

    def __init__(self, *, stage_factory: StageFactory | None = None) -> None:
        self._stage_factory = stage_factory
        self._store = SessionStore(self._open_stage)

    def _open_stage(self, name: str) -> Stage:
        factory = self._stage_factory or _molvis_stage
        return factory(name)

    def register(self, mcp: FastMCP) -> None:
        """Attach the five viewer tools to *mcp*.

        Args:
            mcp: Server the tools are mounted on, under the provider's
                ``molvis`` namespace (``molvis_open``, ``molvis_exec``, …).

        Raises:
            RuntimeError: ``molvis`` is not installed. The import is probed
                eagerly so a missing dependency fails while the server is
                being built rather than on some later tool call — and is
                skipped entirely when a stage factory was injected, since
                that path never touches molvis.
        """
        if self._stage_factory is None:
            try:
                import molvis  # noqa: F401 — eager probe; surface the missing dep
            except ImportError as exc:
                raise RuntimeError(
                    "MolvisProvider requires the 'molcrafts-molvis' package. "
                    "Install with: pip install molcrafts-molvis"
                ) from exc

        from mcp.types import ToolAnnotations

        read_only = ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            openWorldHint=False,
        )
        # A viewer session is a live browser-facing object; exec runs
        # arbitrary agent code against it.
        live = ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            openWorldHint=True,
            idempotentHint=False,
        )
        store = self._store

        # ------------------------------------------------------------------
        # open
        # ------------------------------------------------------------------

        @mcp.tool(name="open", annotations=live)
        def open_session(session_id: str | None = None) -> dict[str, object]:
            """Start a viewer session and its persistent Python namespace.

            The namespace comes with ``stage`` pre-bound — the live molvis
            viewer object every later ``exec`` call operates on. Open the
            returned ``connection_url`` in a browser to see the canvas.

            Args:
                session_id: Explicit id to open. Omit to have one
                    generated. Re-using a live id is an error, never an
                    attach.

            Returns:
                Dict with ``ok``, ``session_id``, and ``connection_url``.
                That URL is an empty string when the stage has none to
                hand out — an embedder's in-process stage, say, with no
                browser to attach.
            """
            session = store.open(session_id)
            return {
                "ok": True,
                "session_id": session.session_id,
                "connection_url": str(getattr(session.stage, "connection_url", "")),
            }

        # ------------------------------------------------------------------
        # close
        # ------------------------------------------------------------------

        @mcp.tool(annotations=live)
        def close(session_id: str) -> dict[str, object]:
            """Close a viewer session and discard its namespace.

            Everything the session held — the stage, and any object the
            agent built in it — is dropped. The id becomes reusable.

            Args:
                session_id: Session to tear down.

            Returns:
                Dict with ``ok`` and the closed ``session_id``.
            """
            store.close(session_id)
            return {"ok": True, "session_id": session_id}

        # ------------------------------------------------------------------
        # list_sessions
        # ------------------------------------------------------------------

        @mcp.tool(annotations=read_only)
        def list_sessions() -> list[dict[str, object]]:
            """List the live viewer sessions in this server process.

            Returns:
                Rows with ``session_id``, ``connected`` (is a browser
                attached right now), and ``created_at`` (open time, in
                seconds since the Unix epoch). Empty list when nothing is
                open.
            """
            return store.list()

        # ------------------------------------------------------------------
        # exec
        # ------------------------------------------------------------------

        @mcp.tool(name="exec", annotations=live)
        def exec_code(session_id: str, code: str) -> dict[str, object]:
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
            look symbols up with the ``molcrafts_*`` discovery tools
            (``molcrafts_search`` → ``molcrafts_open``) before writing
            code — this provider will not validate or correct it.

            No sandbox and no timeout kill: blocking calls block this
            server's worker, exactly as they would in a notebook kernel.

            Args:
                session_id: Session whose namespace to run in.
                code: Python source. A trailing expression is echoed as
                    ``value_repr``, the way a REPL echoes a value.

            Returns:
                Dict with ``ok`` (the code ran without raising),
                ``stdout``, ``value_repr``, ``error``
                (``{type, message, traceback}`` or ``None``), and
                ``truncated`` (stdout hit the output cap). Code that
                raises returns ``ok: false`` — it is a result, not a
                tool failure. An unknown ``session_id`` *is* a failure.
            """
            session = store.get(session_id)
            result = execute_code(code, session.namespace)
            return {
                "ok": result.error is None,
                "stdout": result.stdout,
                "value_repr": result.value_repr,
                "error": result.error,
                "truncated": result.truncated,
            }

        # ------------------------------------------------------------------
        # poll_events
        # ------------------------------------------------------------------

        @mcp.tool(annotations=read_only)
        def poll_events(
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
            page = store.get(session_id).journal.poll(since=since, limit=limit)
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
