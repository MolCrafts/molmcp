"""Python analyzer — the deep, stdlib-``ast``-based v1 analyzer.

Extracts modules/packages, classes (and nested classes), functions,
methods, properties, fields, module constants, decorators, base-class
names, imports, ``__all__`` exports, docstrings, signatures, and line
spans. Cross-file references (calls, imports, base classes) are emitted
as :class:`UnresolvedRef` for the Resolver to link in phase 2.
"""

from __future__ import annotations

import ast
import copy

from ..schema import (
    Edge,
    EdgeKind,
    FileRecord,
    Node,
    NodeKind,
    UnresolvedRef,
    Visibility,
    node_id,
)
from .base import AnalyzerResult


def module_qualname(rel_path: str) -> str:
    """Derive a dotted module name from a repo-relative file path."""
    p = rel_path.replace("\\", "/")
    for suffix in (".pyi", ".py"):
        if p.endswith(suffix):
            p = p[: -len(suffix)]
            break
    parts = [seg for seg in p.split("/") if seg]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


def _docstring(node: ast.AST) -> str | None:
    try:
        return ast.get_docstring(node, clean=True)  # type: ignore[arg-type]
    except TypeError:
        return None


def _summary(docstring: str | None) -> str | None:
    if not docstring:
        return None
    for line in docstring.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _decorator_names(decorator_list: list[ast.expr]) -> list[str]:
    names: list[str] = []
    for dec in decorator_list:
        try:
            names.append(ast.unparse(dec))
        except Exception:  # noqa: BLE001 - never let rendering break analysis
            pass
    return names


def _base_name(expr: ast.expr) -> str:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return f"{_base_name(expr.value)}.{expr.attr}".lstrip(".")
    if isinstance(expr, ast.Subscript):
        return _base_name(expr.value)
    try:
        return ast.unparse(expr)
    except Exception:  # noqa: BLE001
        return ""


def _signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    clone = copy.copy(fn)
    clone.body = [ast.Pass()]
    clone.decorator_list = []
    try:
        text = ast.unparse(clone)
    except Exception:  # noqa: BLE001
        return None
    head = text.split("\n", 1)[0].rstrip().rstrip(":")
    paren = head.find("(")
    if paren == -1:
        return None
    return f"{fn.name}{head[paren:]}"


def _call_target(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = _call_target(func.value)
        return f"{base}.{func.attr}" if base else func.attr
    return None


def _visibility(name: str) -> str:
    return Visibility.PRIVATE if name.startswith("_") else Visibility.PUBLIC


class _Builder:
    """Accumulates one file's nodes/edges/unresolved refs."""

    def __init__(self, file: str, language: str):
        self.file = file
        self.language = language
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self.unresolved: list[UnresolvedRef] = []
        self._seen_calls: set[tuple[str, str]] = set()

    def add_node(self, node: Node) -> None:
        self.nodes.append(node)

    def add_contains(self, parent_id: str, child_id: str) -> None:
        self.edges.append(
            Edge(source=parent_id, target=child_id, kind=EdgeKind.CONTAINS,
                 file=self.file)
        )

    def add_ref(self, from_id: str, name: str, kind: str, line: int | None) -> None:
        if kind == EdgeKind.CALLS:
            key = (from_id, name)
            if key in self._seen_calls:
                return
            self._seen_calls.add(key)
        self.unresolved.append(
            UnresolvedRef(from_node=from_id, name=name, kind=kind,
                          file=self.file, line=line)
        )

    def collect_calls(self, from_id: str, fn: ast.AST) -> None:
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Call):
                target = _call_target(sub.func)
                if target:
                    self.add_ref(from_id, target, EdgeKind.CALLS,
                                 getattr(sub, "lineno", None))


class PythonAnalyzer:
    """Stdlib-``ast`` analyzer for ``.py`` / ``.pyi`` files."""

    language = "python"
    extensions = frozenset({".py", ".pyi"})

    def analyze(self, file: FileRecord, source: str) -> AnalyzerResult:
        try:
            tree = ast.parse(source, filename=file.path)
        except SyntaxError as exc:
            return AnalyzerResult(errors=[f"SyntaxError: {exc}"])

        b = _Builder(file.path, self.language)
        is_package = file.path.replace("\\", "/").endswith("__init__.py")
        mod_qn = module_qualname(file.path) or "(root)"
        mod_name = mod_qn.rsplit(".", 1)[-1]
        mod_kind = NodeKind.PACKAGE if is_package else NodeKind.MODULE
        mod_id = node_id(file.path, mod_qn, mod_kind)
        mod_doc = _docstring(tree)
        line_count = source.count("\n") + 1

        b.add_node(
            Node(
                id=mod_id, kind=mod_kind, name=mod_name, qualname=mod_qn,
                language=self.language, file=file.path, start_line=1,
                end_line=line_count, docstring=mod_doc,
                summary=_summary(mod_doc), is_exported=True,
            )
        )

        exported = _extract_all(tree)
        self._visit_body(tree.body, b, mod_id, mod_qn, in_class=False,
                         exported=exported)
        return AnalyzerResult(nodes=b.nodes, edges=b.edges,
                              unresolved=b.unresolved)

    def _visit_body(
        self,
        body: list[ast.stmt],
        b: _Builder,
        parent_id: str,
        parent_qn: str,
        *,
        in_class: bool,
        exported: set[str] | None,
    ) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                if not in_class:
                    self._handle_import(stmt, b, parent_id)
            elif isinstance(stmt, ast.ClassDef):
                self._handle_class(stmt, b, parent_id, parent_qn,
                                   in_class=in_class, exported=exported)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._handle_function(stmt, b, parent_id, parent_qn,
                                      in_class=in_class, exported=exported)
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                self._handle_assign(stmt, b, parent_id, parent_qn,
                                    in_class=in_class, exported=exported)

    def _handle_import(
        self, stmt: ast.Import | ast.ImportFrom, b: _Builder, mod_id: str
    ) -> None:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                b.add_ref(mod_id, alias.name, EdgeKind.IMPORTS, stmt.lineno)
        else:
            prefix = "." * stmt.level + (stmt.module or "")
            for alias in stmt.names:
                name = f"{prefix}.{alias.name}" if prefix else alias.name
                b.add_ref(mod_id, name, EdgeKind.IMPORTS, stmt.lineno)

    def _handle_class(
        self,
        stmt: ast.ClassDef,
        b: _Builder,
        parent_id: str,
        parent_qn: str,
        *,
        in_class: bool,
        exported: set[str] | None,
    ) -> None:
        qn = f"{parent_qn}.{stmt.name}" if parent_qn != "(root)" else stmt.name
        cid = node_id(b.file, qn, NodeKind.CLASS)
        bases = [_base_name(base) for base in stmt.bases]
        bases = [x for x in bases if x]
        decorators = _decorator_names(stmt.decorator_list)
        doc = _docstring(stmt)
        is_abstract = any(
            x in {"ABC", "abc.ABC"} for x in bases
        ) or "abstractmethod" in " ".join(decorators)
        b.add_node(
            Node(
                id=cid, kind=NodeKind.CLASS, name=stmt.name, qualname=qn,
                language=self.language, file=b.file, start_line=stmt.lineno,
                end_line=stmt.end_lineno or stmt.lineno, docstring=doc,
                summary=_summary(doc), decorators=decorators, bases=bases,
                visibility=_visibility(stmt.name),
                is_exported=_is_exported(stmt.name, in_class, exported),
                is_abstract=is_abstract,
            )
        )
        b.add_contains(parent_id, cid)
        for base in bases:
            b.add_ref(cid, base, EdgeKind.EXTENDS, stmt.lineno)
        self._visit_body(stmt.body, b, cid, qn, in_class=True,
                         exported=exported)

    def _handle_function(
        self,
        stmt: ast.FunctionDef | ast.AsyncFunctionDef,
        b: _Builder,
        parent_id: str,
        parent_qn: str,
        *,
        in_class: bool,
        exported: set[str] | None,
    ) -> None:
        qn = f"{parent_qn}.{stmt.name}" if parent_qn != "(root)" else stmt.name
        decorators = _decorator_names(stmt.decorator_list)
        dec_blob = " ".join(decorators)
        is_property = any(
            d.split(".")[-1] in {"property", "cached_property"}
            for d in decorators
        )
        if in_class:
            kind = NodeKind.PROPERTY if is_property else NodeKind.METHOD
        else:
            kind = NodeKind.FUNCTION
        fid = node_id(b.file, qn, kind)
        doc = _docstring(stmt)
        metadata: dict = {}
        if in_class:
            if "classmethod" in dec_blob:
                metadata["method_type"] = "classmethod"
            elif "staticmethod" in dec_blob:
                metadata["method_type"] = "staticmethod"
        b.add_node(
            Node(
                id=fid, kind=kind, name=stmt.name, qualname=qn,
                language=self.language, file=b.file, start_line=stmt.lineno,
                end_line=stmt.end_lineno or stmt.lineno,
                signature=_signature(stmt), docstring=doc,
                summary=_summary(doc), decorators=decorators,
                visibility=_visibility(stmt.name),
                is_exported=_is_exported(stmt.name, in_class, exported),
                is_async=isinstance(stmt, ast.AsyncFunctionDef),
                is_abstract="abstractmethod" in dec_blob,
                metadata=metadata,
            )
        )
        b.add_contains(parent_id, fid)
        b.collect_calls(fid, stmt)

    def _handle_assign(
        self,
        stmt: ast.Assign | ast.AnnAssign,
        b: _Builder,
        parent_id: str,
        parent_qn: str,
        *,
        in_class: bool,
        exported: set[str] | None,
    ) -> None:
        if isinstance(stmt, ast.AnnAssign):
            targets: list[ast.expr] = [stmt.target]
        else:
            targets = list(stmt.targets)
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            name = target.id
            if name == "__all__":
                continue
            kind = NodeKind.FIELD if in_class else NodeKind.CONSTANT
            qn = f"{parent_qn}.{name}" if parent_qn != "(root)" else name
            nid = node_id(b.file, qn, kind)
            b.add_node(
                Node(
                    id=nid, kind=kind, name=name, qualname=qn,
                    language=self.language, file=b.file,
                    start_line=stmt.lineno,
                    end_line=stmt.end_lineno or stmt.lineno,
                    visibility=_visibility(name),
                    is_exported=_is_exported(name, in_class, exported),
                )
            )
            b.add_contains(parent_id, nid)


def _extract_all(tree: ast.Module) -> set[str] | None:
    """Return the names in a module-level ``__all__``, or None if absent."""
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in stmt.targets
        ):
            continue
        value = stmt.value
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            names = {
                el.value
                for el in value.elts
                if isinstance(el, ast.Constant) and isinstance(el.value, str)
            }
            return names
    return None


def _is_exported(name: str, in_class: bool, exported: set[str] | None) -> bool:
    if in_class:
        return False
    if exported is not None:
        return name in exported
    return not name.startswith("_")
