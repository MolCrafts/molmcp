"""Source / docstring / signature retrieval tools."""

from __future__ import annotations

import inspect
from pathlib import Path

from ._resolve import resolve_package_paths, resolve_symbol


def get_source_of(symbol: str) -> str:
    obj = resolve_symbol(symbol)
    if obj is None:
        return f"Symbol not found: {symbol}"
    try:
        return inspect.getsource(obj)
    except (TypeError, OSError):
        return f"Source not available for: {symbol}"


def get_docstring_of(symbol: str) -> str:
    obj = resolve_symbol(symbol)
    if obj is None:
        return f"Symbol not found: {symbol}"
    doc = inspect.getdoc(obj)
    return doc if doc else f"No docstring for: {symbol}"


def get_signature_of(symbol: str) -> str:
    obj = resolve_symbol(symbol)
    if obj is None:
        return f"Symbol not found: {symbol}"
    # Try with ``eval_str=True`` so PEP 563 (``from __future__ import
    # annotations``) stringified annotations resolve to real classes —
    # otherwise an agent reading ``def read_pdb(...) -> 'Frame'`` only
    # sees the string ``'Frame'`` (or worse, ``Any`` after re-export).
    # Fall back to the raw, unevaluated signature when forward refs are
    # unresolvable in the target module's namespace.
    try:
        sig = inspect.signature(obj, eval_str=True)
    except (NameError, AttributeError):
        try:
            sig = inspect.signature(obj)
        except (ValueError, TypeError):
            return f"No signature available for: {symbol}"
    except (ValueError, TypeError):
        return f"No signature available for: {symbol}"
    return f"{symbol}{sig}"


def read_package_file(
    import_roots: list[str],
    relative_path: str,
    start: int = 1,
    end: int | None = None,
) -> str:
    """Read a slice of a file inside one of ``import_roots``.

    The path is resolved against each root's package directory's parent
    (so ``relative_path="molpy/core/atomistic.py"`` works when ``molpy`` is
    one of the roots). Returns an error string on path-traversal attempts
    or files outside any root.
    """
    if ".." in Path(relative_path).parts:
        return f"Refusing path traversal: {relative_path}"

    for root in import_roots:
        for pkg_dir in resolve_package_paths(root):
            candidate = (pkg_dir.parent / relative_path).resolve()
            try:
                candidate.relative_to(pkg_dir.parent.resolve())
            except ValueError:
                continue
            if not candidate.is_file():
                continue
            try:
                lines = candidate.read_text().splitlines()
            except (OSError, UnicodeDecodeError) as e:
                return f"Cannot read {relative_path}: {e}"
            stop = end if end is not None else len(lines)
            slice_ = lines[max(start - 1, 0) : stop]
            return "\n".join(slice_)
    return f"File not found in any import root: {relative_path}"
