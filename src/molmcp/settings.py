"""Layered molmcp settings — what this install indexes, and where.

Three files, merged low to high, in the shape Claude Code established:

* ``~/.molmcp/settings.json`` — the user's install
* ``<project>/.molmcp/settings.json`` — checked in with a repo
* ``<project>/.molmcp/settings.local.json`` — that repo, this machine

The *user* file is the primary surface here, which is the one place this
departs from Claude Code's emphasis. A plane server is launched by an MCP
client, so its working directory is whatever the client happened to be
started in — a project-scoped default would make "what do I index" depend
on an accident. ``molmcp config`` therefore writes the user file unless
asked for ``--project``.

Keys are camelCase, and unknown ones are an error rather than a silent
no-op: a mistyped ``indexWorkspaces`` that quietly does nothing is worse
than one that says so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Directory name used for both the user home and a project checkout.
CONFIG_DIR_NAME = ".molmcp"
SETTINGS_NAME = "settings.json"
LOCAL_SETTINGS_NAME = "settings.local.json"


class SettingsError(ValueError):
    """Raised when a settings file is unreadable or names an unknown key."""


#: Every settable key, with the type its value must parse to. Anything not
#: listed is rejected — see the module docstring.
_SCHEMA: dict[str, type] = {
    "sources": dict,
    "indexWorkspace": bool,
    "knowledgeScope": list,
    "excludes": list,
    "cacheDir": str,
    "watch": bool,
    "maxCacheBytes": int,
    "maxCacheAgeDays": int,
    "pythonEnv": str,
    "discoverInclude": list,
    "discoverExclude": list,
    "molexp": dict,
    "molq": dict,
}

#: Members allowed inside each dict-valued setting whose keys are a fixed set.
#: ``sources`` is deliberately absent — its members are user-chosen names.
#: Without this, `config set molq.allowsubmit true` would be accepted, stored,
#: echoed back by `config list`, and read by nothing.
_NESTED_SCHEMA: dict[str, frozenset[str]] = {
    "molq": frozenset({"database", "allowSubmit"}),
    "molexp": frozenset({"workspace"}),
}

#: Keys whose layers combine instead of replacing one another.
_MERGED_DICTS = ("sources", "molexp", "molq")
_MERGED_LISTS = ("excludes", "knowledgeScope", "discoverInclude", "discoverExclude")


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved settings for one molmcp invocation."""

    sources: dict[str, str] = field(default_factory=dict)
    index_workspace: bool = False
    excludes: tuple[str, ...] = ()
    cache_dir: str | None = None
    watch: bool = True
    max_cache_bytes: int | None = None
    max_cache_age_days: int | None = None
    #: Narrow which configured sources the knowledge tools surface. Empty
    #: means all of them; this never widens past ``sources``.
    knowledge_scope: tuple[str, ...] = ()
    #: Locator for the Python environment auto-discovery reads.
    python_env: str | None = None
    discover_include: tuple[str, ...] = ()
    discover_exclude: tuple[str, ...] = ()
    molexp: dict[str, str] = field(default_factory=dict)
    molq: dict[str, str] = field(default_factory=dict)
    #: Files that actually contributed, lowest precedence first.
    layers: tuple[Path, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": dict(self.sources),
            "indexWorkspace": self.index_workspace,
            "excludes": list(self.excludes),
            "cacheDir": self.cache_dir,
            "watch": self.watch,
            "maxCacheBytes": self.max_cache_bytes,
            "maxCacheAgeDays": self.max_cache_age_days,
            "knowledgeScope": list(self.knowledge_scope),
            "pythonEnv": self.python_env,
            "discoverInclude": list(self.discover_include),
            "discoverExclude": list(self.discover_exclude),
            "molexp": dict(self.molexp),
            "molq": dict(self.molq),
            "layers": [str(path) for path in self.layers],
        }


def user_settings_path() -> Path:
    """The install-wide settings file."""
    return Path.home() / CONFIG_DIR_NAME / SETTINGS_NAME


def project_settings_path(root: str | Path, *, local: bool = False) -> Path:
    """Settings for one checkout; ``local`` is the untracked override."""
    name = LOCAL_SETTINGS_NAME if local else SETTINGS_NAME
    return Path(root) / CONFIG_DIR_NAME / name


def read_settings_file(path: Path) -> dict[str, Any]:
    """Parse one settings file; missing is empty, malformed is an error."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SettingsError(f"cannot read settings at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SettingsError(f"settings at {path} must be a JSON object")
    _reject_unknown(data, path)
    return data


def write_settings_file(path: Path, data: dict[str, Any]) -> None:
    """Write settings, creating the directory, with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def settings_layers(project_root: str | Path | None = None) -> list[Path]:
    """The candidate files, lowest precedence first."""
    layers = [user_settings_path()]
    if project_root is not None:
        layers.append(project_settings_path(project_root))
        layers.append(project_settings_path(project_root, local=True))
    return layers


def load_settings(project_root: str | Path | None = None) -> Settings:
    """Merge every layer that exists into one resolved :class:`Settings`."""
    merged: dict[str, Any] = {}
    contributing: list[Path] = []
    for path in settings_layers(project_root):
        data = read_settings_file(path)
        if not data:
            continue
        contributing.append(path)
        for key, value in data.items():
            if key in _MERGED_DICTS and isinstance(value, dict):
                merged.setdefault(key, {}).update(value)
            elif key in _MERGED_LISTS and isinstance(value, list):
                merged.setdefault(key, []).extend(value)
            else:
                merged[key] = value
    return Settings(
        sources={str(k): str(v) for k, v in (merged.get("sources") or {}).items()},
        index_workspace=bool(merged.get("indexWorkspace", False)),
        excludes=tuple(dict.fromkeys(str(x) for x in merged.get("excludes") or ())),
        cache_dir=(
            str(merged["cacheDir"]) if merged.get("cacheDir") is not None else None
        ),
        watch=bool(merged.get("watch", True)),
        max_cache_bytes=_optional_int(merged.get("maxCacheBytes")),
        max_cache_age_days=_optional_int(merged.get("maxCacheAgeDays")),
        knowledge_scope=_str_tuple(merged.get("knowledgeScope")),
        python_env=(
            str(merged["pythonEnv"]) if merged.get("pythonEnv") is not None else None
        ),
        discover_include=_str_tuple(merged.get("discoverInclude")),
        discover_exclude=_str_tuple(merged.get("discoverExclude")),
        molexp={str(k): str(v) for k, v in (merged.get("molexp") or {}).items()},
        molq={str(k): str(v) for k, v in (merged.get("molq") or {}).items()},
        layers=tuple(contributing),
    )


# -- editing (the `molmcp config` verbs) --------------------------------


def set_value(path: Path, key: str, value: str) -> dict[str, Any]:
    """Set ``key`` (dotted for nested) to a parsed ``value``."""
    root, leaf, container = _resolve(path, key, create=True)
    container[leaf] = _parse(key, value)
    write_settings_file(path, root)
    return root


def add_value(path: Path, key: str, value: str) -> dict[str, Any]:
    """Append to a list-valued ``key``, ignoring a duplicate."""
    top = key.split(".", 1)[0]
    if _SCHEMA.get(top) is not list:
        raise SettingsError(f"{key!r} is not a list-valued setting; use `config set`")
    root, leaf, container = _resolve(path, key, create=True)
    current = container.get(leaf)
    items = list(current) if isinstance(current, list) else []
    if value not in items:
        items.append(value)
    container[leaf] = items
    write_settings_file(path, root)
    return root


def remove_value(path: Path, key: str, value: str | None = None) -> dict[str, Any]:
    """Drop ``key`` outright, or one ``value`` from a list-valued key."""
    root, leaf, container = _resolve(path, key, create=False)
    if leaf not in container:
        raise SettingsError(f"{key!r} is not set in {path}")
    if value is None:
        del container[leaf]
    else:
        current = container[leaf]
        if not isinstance(current, list) or value not in current:
            raise SettingsError(f"{value!r} is not present in {key!r}")
        container[leaf] = [item for item in current if item != value]
    write_settings_file(path, root)
    return root


def get_value(data: dict[str, Any], key: str) -> Any:
    """Read a dotted ``key`` out of already-parsed settings data."""
    node: Any = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


# -- internals ----------------------------------------------------------


def _reject_unknown(data: dict[str, Any], path: Path) -> None:
    unknown = sorted(set(data) - set(_SCHEMA))
    if unknown:
        raise SettingsError(
            f"unknown setting(s) in {path}: {', '.join(unknown)}. "
            f"Known keys: {', '.join(sorted(_SCHEMA))}"
        )
    for parent, allowed in _NESTED_SCHEMA.items():
        section = data.get(parent)
        if not isinstance(section, dict):
            continue
        strays = sorted(set(section) - allowed)
        if strays:
            raise SettingsError(
                f"unknown setting(s) in {path}: "
                f"{', '.join(f'{parent}.{k}' for k in strays)}. "
                f"Known {parent} keys: {', '.join(sorted(allowed))}"
            )


def _resolve(
    path: Path, key: str, *, create: bool
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Return ``(root, leaf_name, owning_container)`` for a dotted key."""
    parts = key.split(".")
    if parts[0] not in _SCHEMA:
        raise SettingsError(
            f"unknown setting {parts[0]!r}. Known keys: {', '.join(sorted(_SCHEMA))}"
        )
    if len(parts) > 2 or (len(parts) == 2 and _SCHEMA[parts[0]] is not dict):
        raise SettingsError(f"{key!r} is not a settable path")
    allowed = _NESTED_SCHEMA.get(parts[0]) if len(parts) == 2 else None
    if allowed is not None and parts[1] not in allowed:
        raise SettingsError(
            f"unknown setting {key!r}. "
            f"Known {parts[0]} keys: {', '.join(sorted(allowed))}"
        )
    root = read_settings_file(path)
    if len(parts) == 1:
        return root, parts[0], root
    if create:
        container = root.setdefault(parts[0], {})
    else:
        container = root.get(parts[0], {})
    if not isinstance(container, dict):
        raise SettingsError(f"{parts[0]!r} is not an object in {path}")
    return root, parts[1], container


def _parse(key: str, value: str) -> Any:
    """Coerce a command-line string to the type the schema declares."""
    parts = key.split(".")
    expected = _SCHEMA[parts[0]]
    if len(parts) == 2:  # a member of a dict-valued setting is always a string
        return value
    if expected is bool:
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
        raise SettingsError(f"{key!r} expects a boolean, got {value!r}")
    if expected is int:
        try:
            return int(value)
        except ValueError as exc:
            raise SettingsError(f"{key!r} expects an integer, got {value!r}") from exc
    if expected is list:
        return [value]
    if expected is dict:
        raise SettingsError(f"set a member instead, e.g. {key}.<name> <value>")
    return value


def _str_tuple(value: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in value or ()))


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


__all__ = [
    "CONFIG_DIR_NAME",
    "LOCAL_SETTINGS_NAME",
    "SETTINGS_NAME",
    "Settings",
    "SettingsError",
    "add_value",
    "get_value",
    "load_settings",
    "project_settings_path",
    "read_settings_file",
    "remove_value",
    "set_value",
    "settings_layers",
    "user_settings_path",
    "write_settings_file",
]
