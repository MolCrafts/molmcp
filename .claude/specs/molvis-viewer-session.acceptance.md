---
spec: molvis-viewer-session
created: 2026-08-02
criteria:
  - id: ac-001
    summary: "MolvisProvider registers under molmcp.providers with name molvis"
    type: code
    pass_when: "entry point molvis loads MolvisProvider and instance.name == 'molvis'"
    status: verified
    last_checked: 2026-08-02
  - id: ac-002
    summary: "Open creates a listable session; duplicate session_id errors"
    type: runtime
    pass_when: "after open, list_sessions includes the session_id and open returns connection_url; open with the same session_id returns a structured error (no silent attach)"
    status: verified
    last_checked: 2026-08-02
  - id: ac-003
    summary: "exec runs in a persistent per-session namespace with stage prebound"
    type: runtime
    pass_when: "a variable defined in one exec call is usable in the next; `stage` resolves to the session's Stage without any import"
    status: verified
    last_checked: 2026-08-02
  - id: ac-004
    summary: "exec has REPL return contract: stdout, last-expression repr, structured errors, output cap"
    type: runtime
    pass_when: "print output lands in stdout; a trailing expression returns its repr; an exception returns {type, message, traceback} without crashing the server; oversized output is truncated with a flag"
    status: verified
    last_checked: 2026-08-02
  - id: ac-005
    summary: "Provider carries zero domain knowledge, zero gating, zero env vars"
    type: code
    pass_when: "provider.py and session.py contain no molvis method-name branching, no molpy import, no os.environ reads, and no permission/opt-in branches; the only tools are open/close/list_sessions/exec/poll_events"
    status: verified
    last_checked: 2026-08-02
  - id: ac-006
    summary: "poll_events returns monotonic cursor deltas with truncation flag and verbatim payloads"
    type: runtime
    pass_when: "journal events poll incrementally by cursor; evicted history yields truncated: true; payloads are stored and returned unmodified"
    status: verified
    last_checked: 2026-08-02
  - id: ac-007
    summary: "Journal is thread-safe under WS-thread dispatch"
    type: test
    pass_when: "concurrent append (worker thread) + poll_events (main thread) test passes without lost or duplicated cursors"
    status: pending
  - id: ac-008
    summary: "Workbench pinned against real molvis via in-process transport"
    type: test
    pass_when: "a test using Molvis.from_inprocess (no browser) drives stage APIs through exec and receives an injected event.* notification through poll_events"
    status: pending
  - id: ac-009
    summary: "close removes session, tears down stage, drops namespace"
    type: runtime
    pass_when: "after close(session_id), list_sessions no longer contains it; stage.close asserted (mock ok); namespace objects are released"
    status: verified
    last_checked: 2026-08-02
  - id: ac-010
    summary: "Agent learning path: molvis indexed by discovery + loop guide page"
    type: docs
    pass_when: "molvis is in the discovery source inventory and molcrafts_open can inject drawing/selection mixin docstring pages; a guide page teaches the exec loop (build → draw → poll → get_selected → edit → clear → redraw) and contains no API reference (points to discovery instead)"
    status: pending
  - id: ac-011
    summary: "provider-design documents the workbench, zero-vocabulary rule, same-process trust model"
    type: docs
    pass_when: "docs/concepts/provider-design.md lists the 5 molvis tools, the no-invented-API principle, and a one-line local-workbench trust statement (no gating machinery described)"
    status: pending
  - id: ac-012
    summary: "In-tree tests cover session + provider without product e2e tree"
    type: test
    pass_when: "uv run pytest tests/providers/test_molvis*.py -q passes; no new e2e playbook under molmcp/examples or molvis/"
    status: pending
out_of_scope:
  - "Out-of-tree aspirin dialogue e2e harness (sibling repo/folder)"
  - "Named wrapper tools (composite or 1:1) and any agent-facing send_cmd/JSON-RPC surface"
  - "Env-var switches, permission gating, sandboxing/isolation"
  - "Attach to externally started WebSocket viewers"
---

# Acceptance — molvis-viewer-session

Done means: an agent connected to molmcp can open a MolVis session, drive it by writing molpy/molvis Python code through the `exec` primitive (persistent namespace, `stage` prebound), read uplink events through `poll_events`, and close — with in-tree unit tests (including an in-process-transport pin against real molvis) and docs. molmcp invents zero vocabulary, reads zero env vars, and ships zero permission machinery. The human aspirin playbook is **not** required inside this repo.

## AC-001 — entry point

`pyproject.toml` registers `molvis = "molmcp.providers.molvis:MolvisProvider"`. Discover/load yields `name == "molvis"`.

## AC-002 — open + list + collision

Happy path creates a session visible to `list_sessions` and returns `connection_url`. Re-opening an existing session_id is a structured error, not an attach.

## AC-003 — persistent namespace

The namespace is the agent's working memory: objects like `mol` survive across exec calls until `close`. `stage` is prebound at `open`.

## AC-004 — REPL contract

`exec` is generic REPL machinery: captured stdout, last-expression repr, structured `{type, message, traceback}` on exception, size-capped output with a truncation flag. No code validation, no import restrictions.

## AC-005 — zero domain knowledge, zero gating

No molvis method names in control flow (docstring examples excepted), no molpy import in provider code, no `os.environ`, no opt-in branches. Exactly 5 tools.

## AC-006 — event poll

Cursor-based, monotonic, `truncated` on eviction, payloads verbatim.

## AC-007 — journal thread safety

molvis EventBus dispatches from the WS thread; the journal must tolerate concurrent append/poll under its lock.

## AC-008 — in-process pin

The workbench (not molvis semantics) is verified against real molvis through `Molvis.from_inprocess`: exec-driven stage calls round-trip and events arrive via poll_events, no browser.

## AC-009 — close

Session removed; stage closed; namespace dropped so held objects are released.

## AC-010 — learning path

Discovery over molvis (and molpy) is the semantic source; the guide page teaches only the loop and defers every API to discovery.

## AC-011 — provider-design docs

Workbench entry documents the 5 tools, the zero-invented-API rule, and the local same-process trust model in one line — no gating machinery.

## AC-012 — tests placement

Provider tests live under `tests/providers/`. Spec forbids landing the aspirin e2e playbook inside molmcp/molvis product trees.

## Non-criteria

- Real browser screenshot CI.
- Multi-agent concurrent sessions stress.
- Sandboxing or resource isolation for exec.
- molvis-side companion gaps (selection↔row contract pin, NotConnectedError, serve-env construction regression) — they gate the edit-selected e2e leg, not this repo's done.
