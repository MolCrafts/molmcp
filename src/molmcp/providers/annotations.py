"""The annotation vocabulary every plane shares.

``ToolAnnotations`` is how a client decides whether to run a tool without
asking, so the values are a contract rather than decoration. Each provider
used to hand-roll its own set inside ``register()``, and they disagreed:
molexp's read-only tools omitted ``open_world_hint`` entirely, which reads
as *unknown* rather than *local*.

Four constants cover every first-party tool. A provider that needs a fifth
should add it here, with the reason, rather than build one inline.
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

#: Changes state that the caller cannot trivially undo. A client should
#: confirm before calling one of these.
MUTATION = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=True,
)

#: Create-or-get. Writes, but calling it twice leaves the same state, so it
#: is not a destructive surface even though it is not a read.
IDEMPOTENT_WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

__all__ = ["IDEMPOTENT_WRITE", "MUTATION", "READ_ONLY", "READ_REMOTE"]
