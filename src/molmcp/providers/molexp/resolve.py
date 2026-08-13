"""Open a molexp Workspace from a local path or host-qualified serve label.

Local agents call MCP tools with either:

* an absolute local path (``/Users/me/ws``), or
* a serve-style remote label (``Arrhenius:/home/…``, ``user@host:/data``)

Both resolve through molexp's single target stack so navigation / scaffold
share the same SSH filesystem as ``molexp validate -ws Host:/path``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from molexp.workspace import Workspace

#: SCP / serve form: optional ``user@``, host, absolute remote path after ``:``.
_HOST_QUALIFIED_RE = re.compile(r"^(?:[a-zA-Z0-9_.-]+@)?[a-zA-Z0-9_.-]+:(/|~).+$")


def is_host_qualified(spec: str) -> bool:
    """True when *spec* is ``Host:/abs`` / ``user@host:/abs`` (not a URL)."""
    s = (spec or "").strip()
    if not s or "://" in s:
        return False
    return bool(_HOST_QUALIFIED_RE.match(s))


def open_workspace(spec: str | Path) -> Workspace:
    """Open a :class:`~molexp.workspace.Workspace` for *spec* (local or remote).

    Host-qualified labels use molexp's ``resolve_target`` + remote
    ``FileSystem`` so all Folder I/O goes over SSH. Local paths use the
    default local filesystem.
    """
    from molexp.workspace import Workspace
    from molexp.workspace.target import resolve_target, target_to_filesystem

    raw = str(spec).strip()
    if not raw:
        raise ValueError("workspace spec is empty")

    if is_host_qualified(raw):
        target, _transport = resolve_target(raw)
        fs = target_to_filesystem(target)
        root = str(target.path)
        return Workspace(root, fs=fs)

    root = Path(raw).expanduser().resolve()
    return Workspace(root)


def workspace_spec_string(workspace: str | Path | Workspace) -> str:
    """Canonical string form of a workspace argument for re-open / display."""
    if isinstance(workspace, (str, Path)):
        return str(workspace).strip()
    resolve = getattr(workspace, "resolve", None)
    if callable(resolve):
        return str(resolve())
    return str(workspace)


def as_workspace(workspace: str | Path | Workspace) -> Workspace:
    """Coerce a path/spec or live Workspace into a Workspace."""
    from molexp.workspace import Workspace as Ws

    if isinstance(workspace, Ws):
        return workspace
    return open_workspace(workspace)


def validate_workspace_report(spec: str | Path) -> dict[str, Any]:
    """Lint *spec* (local path or host-qualified) via molexp validate.

    Returns the agent-facing report dict (same shape as
    ``molexp validate --json`` / MCP ``validate_workspace``).
    """
    from molexp.workspace import validate_workspace as _validate

    raw = str(spec).strip()
    if is_host_qualified(raw):
        ws = open_workspace(raw)
        root = str(ws.resolve())
        report = _validate(root, fs=ws._fs)
        payload = report.to_dict()
        payload["path"] = raw
        payload["root"] = root
        payload["remote"] = True
        # Marker check through the remote fs (not local Path).
        has_json = ws._fs.exists(ws._fs.join(root, "workspace.json"))
        has_yaml = ws._fs.exists(ws._fs.join(root, "meta.yaml"))
        payload["is_workspace"] = has_json or has_yaml
        return payload

    root = Path(raw).expanduser().resolve()
    report = _validate(root)
    payload = report.to_dict()
    payload["path"] = payload.get("root", str(root))
    payload["is_workspace"] = (root / "workspace.json").is_file() or (
        root / "meta.yaml"
    ).is_file()
    payload["remote"] = False
    return payload
