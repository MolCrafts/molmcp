"""Generate host MCP client configs — default all planes, --enable/--disable."""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .planes import list_plane_infos

Host = Literal["grok", "claude", "cursor"]


@dataclass(frozen=True, slots=True)
class PlaneToggle:
    """Which planes are enabled for a client config."""

    enabled: tuple[str, ...]
    disabled: tuple[str, ...]
    all_planes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": list(self.enabled),
            "disabled": list(self.disabled),
            "all_planes": list(self.all_planes),
        }


def default_plane_ids() -> tuple[str, ...]:
    """Planes with installed deps (catalog, molcrafts, then α).

    Optional science packages that are not installed are omitted silently —
    no pytest-style skip; they simply never appear in client configs.
    """
    infos = list_plane_infos(include_unavailable_providers=False)
    ids = [p.id for p in infos]
    # Prefer catalog → molcrafts first, then the rest sorted.
    head = [x for x in ("catalog", "molcrafts") if x in ids]
    tail = sorted(x for x in ids if x not in head)
    return tuple(head + tail)


def resolve_plane_toggles(
    *,
    enable: list[str] | tuple[str, ...] = (),
    disable: list[str] | tuple[str, ...] = (),
    available: tuple[str, ...] | None = None,
) -> PlaneToggle:
    """Default: all planes on. Apply ``--disable`` then ``--enable``.

    Raises:
        ValueError: unknown plane id in enable/disable.
    """
    all_planes = available if available is not None else default_plane_ids()
    known = set(all_planes)
    enabled = set(all_planes)

    def _norm(name: str) -> str:
        return name.strip().lower()

    for raw in disable:
        plane = _norm(raw)
        if plane not in known:
            raise ValueError(f"unknown plane {plane!r}; known: {', '.join(all_planes)}")
        enabled.discard(plane)

    for raw in enable:
        plane = _norm(raw)
        if plane not in known:
            raise ValueError(f"unknown plane {plane!r}; known: {', '.join(all_planes)}")
        enabled.add(plane)

    if not enabled:
        raise ValueError("at least one plane must remain enabled")

    ordered = tuple(p for p in all_planes if p in enabled)
    disabled = tuple(p for p in all_planes if p not in enabled)
    return PlaneToggle(enabled=ordered, disabled=disabled, all_planes=all_planes)


def _molmcp_command() -> list[str]:
    """The command a *client* can launch, as an absolute path.

    Emitting the bare name assumed the client would resolve it on PATH.
    Desktop MCP hosts are started by the desktop session, whose PATH is the
    system default, so a virtualenv's bin directory is not on it — the
    config worked in the terminal that generated it and nowhere else.

    The fallback runs this very interpreter rather than ``python``, which on
    macOS frequently does not exist at all.

    Symlinks are deliberately left alone: ``molmcp`` is often a shim, and
    resolving through it would pin a path the installer may replace.
    """
    resolved = shutil.which("molmcp")
    if resolved:
        return [os.path.abspath(resolved)]
    return [sys.executable, "-m", "molmcp"]


def serve_argv(plane: str) -> list[str]:
    return [*_molmcp_command(), "serve", plane]


def render_mcp_json(toggle: PlaneToggle) -> dict[str, Any]:
    """The standard ``mcpServers`` map, listing only the enabled planes.

    Every host molmcp targets reads this shape: Claude Code and Cursor
    natively, and Grok alongside its own ``config.toml`` (from
    ``~/.claude.json``, ``.cursor/mcp.json`` and project ``.mcp.json``).

    A disabled plane is simply absent. The TOML renderer this replaces
    emitted every plane with ``enabled = false``, which only that one
    format understood.
    """
    cmd = _molmcp_command()
    return {
        "mcpServers": {
            plane: {"command": cmd[0], "args": cmd[1:] + ["serve", plane]}
            for plane in toggle.enabled
        }
    }


def render_client(
    host: Host | None = None,
    *,
    enable: list[str] | tuple[str, ...] = (),
    disable: list[str] | tuple[str, ...] = (),
    available: tuple[str, ...] | None = None,
) -> tuple[PlaneToggle, str]:
    """Return ``(toggle, config text)``.

    ``host`` selects only where the result is meant to go; the body is the
    same JSON for all of them.
    """
    if host is not None and host not in _HOST_PATHS:
        raise ValueError(
            f"unknown host {host!r}; known: {', '.join(sorted(_HOST_PATHS))}"
        )
    toggle = resolve_plane_toggles(enable=enable, disable=disable, available=available)
    return toggle, json.dumps(render_mcp_json(toggle), indent=2) + "\n"


#: Where each host expects to find the JSON, relative to home unless noted.
_HOST_PATHS: dict[str, tuple[str, ...]] = {
    # Claude Code merges the user file; Cursor and Grok read project files.
    "claude": (".claude.json",),
    "cursor": (".cursor", "mcp.json"),
    # Grok reads project .mcp.json below its own config.toml in priority.
    "grok": (".mcp.json",),
}


def default_write_path(host: Host) -> Path:
    """Conventional destination for *host*'s MCP config."""
    if host not in _HOST_PATHS:
        raise ValueError(
            f"unknown host {host!r}; known: {', '.join(sorted(_HOST_PATHS))}"
        )
    return Path.home().joinpath(*_HOST_PATHS[host])


__all__ = [
    "Host",
    "PlaneToggle",
    "default_plane_ids",
    "default_write_path",
    "render_client",
    "render_mcp_json",
    "resolve_plane_toggles",
    "serve_argv",
]
