"""The annotation vocabulary every plane shares.

``ToolAnnotations`` is how a client decides whether to run a tool without
asking, so the values are a contract rather than decoration. Each provider
used to hand-roll its own set inside ``register()``, and they disagreed:
molexp's read-only tools omitted ``open_world_hint`` entirely, which reads
as *unknown* rather than *local*.

Six constants cover every first-party tool. A provider that needs a seventh
should add it here, with the reason, rather than build one inline — the
whole point is that a named vocabulary cannot drift the way inline literals
did.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

#: Reads local state and nothing else. Safe to call, safe to repeat.
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

#: Reads, but reaches a scheduler, a browser, or the network to do it. Still
#: safe to call; the answer can change underneath you.
READ_REMOTE = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)

#: Changes state beyond this machine and cannot be trivially undone —
#: submitting to a cluster, cancelling a remote job, driving a browser. A
#: client should confirm before calling one of these.
MUTATION = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=True,
)

#: Rewrites or removes local state, and resumes rather than duplicating when
#: called again.
#:
#: Destructiveness and reach are independent axes, and the first cut of this
#: vocabulary fused them: every destructive tool had to claim it touched an
#: open world. molexp's ``run_adoption`` is the case that exposed it — move
#: mode unlinks source files, it resumes from a ledger, and it never leaves
#: the filesystem. Forcing it onto MUTATION would have made it lie twice.
LOCAL_MUTATION = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)

#: Adds to a local record; calling it twice adds twice.
#:
#: Additive, so *not* destructive — the spec defines the two as opposites.
#: What a caller needs to know is that a retry is not free, which is what
#: ``idempotent_hint=False`` says. Flagging it destructive instead would make
#: a client confirm every append, which is noise.
APPEND_WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)

#: Create-or-get. Writes, but calling it twice leaves the same state, so it
#: is not a destructive surface even though it is not a read.
IDEMPOTENT_WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

__all__ = [
    "APPEND_WRITE",
    "IDEMPOTENT_WRITE",
    "LOCAL_MUTATION",
    "MUTATION",
    "READ_ONLY",
    "READ_REMOTE",
]
