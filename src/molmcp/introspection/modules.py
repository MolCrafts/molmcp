"""Module/symbol enumeration tools."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

from ._resolve import resolve_symbol


def list_modules_under(import_roots: list[str], prefix: str | None = None) -> list[str]:
    """List importable module names under any of ``import_roots``.

    Args:
        import_roots: Top-level packages to walk.
        prefix: Optional substring filter — module name must start with this.

    Returns:
        Sorted unique list of fully-qualified module names.
    """
    collected: set[str] = set()
    for root in import_roots:
        try:
            mod = importlib.import_module(root)
        except ImportError:
            continue
        collected.add(root)
        if not hasattr(mod, "__path__"):
            continue
        for info in pkgutil.walk_packages(mod.__path__, prefix=f"{root}."):
            collected.add(info.name)
    if prefix:
        return sorted(m for m in collected if m.startswith(prefix))
    return sorted(collected)


def list_symbols_in(symbol: str) -> dict[str, str]:
    """Return ``{name: summary}`` for a module's public API or a class's members.

    For modules, values are one-line docstring summaries (or the type
    name when there's no docstring) — same behavior as before.

    For classes, values are tagged ``"<kind> — <summary>"`` where ``kind``
    is one of ``method``, ``classmethod``, ``staticmethod``, ``property``,
    ``attribute``, or ``nested_class``.  This lets agents discover
    instance methods and properties without pulling the whole class
    source.

    Args:
        symbol: Fully-qualified dotted name of a module or a class.
    """
    obj = resolve_symbol(symbol)
    if obj is None:
        return {"error": f"Symbol not found: {symbol}"}
    if inspect.ismodule(obj):
        return _list_module_symbols(obj)
    if inspect.isclass(obj):
        return _list_class_members(obj)
    return {"error": f"Not a module or class: {symbol}"}


def _list_module_symbols(mod: Any) -> dict[str, str]:
    names = getattr(mod, "__all__", None)
    if names is None:
        names = [n for n in dir(mod) if not n.startswith("_")]

    result: dict[str, str] = {}
    for name in sorted(names):
        member = getattr(mod, name, None)
        if member is None:
            continue
        doc = inspect.getdoc(member)
        result[name] = doc.split("\n", 1)[0] if doc else type(member).__name__
    return result


def _list_class_members(cls: type) -> dict[str, str]:
    """List public members of *cls* with kind tags.

    Walks ``cls.__mro__`` only as far as needed to find each member's
    declaring class, so we can classify descriptors (classmethod,
    staticmethod, property) before they're unwrapped by attribute access.
    Members inherited from :class:`object` are skipped.
    """
    result: dict[str, str] = {}
    for name in sorted(dir(cls)):
        if name.startswith("_"):
            continue
        kind = _classify_member(cls, name)
        if kind is None:
            continue
        # Use getattr to fetch the unwrapped object for docstring lookup.
        member = getattr(cls, name, None)
        doc = inspect.getdoc(member) if member is not None else None
        summary = doc.split("\n", 1)[0] if doc else ""
        result[name] = f"{kind} — {summary}" if summary else kind
    return result


def _classify_member(cls: type, name: str) -> str | None:
    """Classify ``cls.<name>`` by inspecting the raw descriptor.

    ``inspect.getmembers`` and ``getattr`` both unwrap descriptors, so
    the only reliable way to tell a classmethod from a staticmethod from
    a regular function is to peek at the declaring class's ``__dict__``.
    """
    for base in cls.__mro__:
        if base is object:
            return None
        if name in base.__dict__:
            raw = base.__dict__[name]
            if isinstance(raw, classmethod):
                return "classmethod"
            if isinstance(raw, staticmethod):
                return "staticmethod"
            if isinstance(raw, property):
                return "property"
            if inspect.isfunction(raw):
                return "method"
            if inspect.isclass(raw):
                return "nested_class"
            return "attribute"
    return None
