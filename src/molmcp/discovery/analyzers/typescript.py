"""Tree-sitter-backed TypeScript and JavaScript analyzer."""

from __future__ import annotations

import os
import re
from typing import Any

from ..schema import (
    EdgeKind,
    FileRecord,
    Node,
    NodeKind,
    Visibility,
    node_id,
)
from ._tree_sitter import (
    TreeSitterBuilder,
    compact,
    descendants,
    end_line,
    field,
    named_children,
    node_text,
    parse,
    start_line,
)
from .base import AnalyzerResult

_JS_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs"}


def typescript_module_qualname(path: str) -> str:
    """Derive a dotted module name from a TS/JS source path."""
    normalized = path.replace("\\", "/")
    stem = re.sub(r"\.(?:[cm]?[jt]sx?)$", "", normalized)
    parts = [part for part in stem.split("/") if part]
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "index":
        parts.pop()
    return ".".join(parts) or "(root)"


def _summary(docstring: str | None) -> str | None:
    if not docstring:
        return None
    return next((line.strip() for line in docstring.splitlines() if line.strip()), None)


def _doc_comment(node: Any, data: bytes) -> str | None:
    prefix = data[: node.start_byte].decode("utf-8", errors="replace")
    block = re.search(r"/\*\*(.*?)\*/\s*$", prefix, re.DOTALL)
    if block:
        body = re.sub(r"^\s*\* ?", "", block.group(1), flags=re.MULTILINE)
        return body.strip() or None
    lines = re.search(r"((?:^\s*///?[^\n]*\n?)+)\s*$", prefix, re.MULTILINE)
    if not lines:
        return None
    cleaned = [re.sub(r"^\s*///?\s?", "", line) for line in lines.group(1).splitlines()]
    return "\n".join(cleaned).strip() or None


def _name(node: Any, data: bytes) -> str | None:
    name_node = field(node, "name")
    if name_node is None:
        return None
    return compact(node_text(name_node, data))


def _header(node: Any, data: bytes) -> str:
    body = field(node, "body")
    if body is None:
        body = next(
            (
                child
                for child in named_children(node)
                if child.type in {"statement_block", "class_body", "object_type"}
            ),
            None,
        )
    end = body.start_byte if body is not None else node.end_byte
    return compact(
        data[node.start_byte : end].decode("utf-8", errors="replace")
    ).rstrip(";")


def _decorators(node: Any, data: bytes) -> list[str]:
    return [
        compact(node_text(child, data))
        for child in named_children(node)
        if child.type == "decorator"
    ]


def _visibility(node: Any, data: bytes) -> str:
    name = _name(node, data) or ""
    if name.startswith(("#", "_")):
        return Visibility.PRIVATE
    for child in named_children(node):
        if child.type == "accessibility_modifier":
            value = node_text(child, data).strip()
            if value in {"private", "protected"}:
                return Visibility.PRIVATE
    return Visibility.PUBLIC


class TypeScriptAnalyzer:
    """Extract TypeScript/JavaScript definitions and unresolved references."""

    language = "typescript"
    extensions = frozenset(
        {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}
    )

    def analyze(self, file: FileRecord, source: str) -> AnalyzerResult:
        extension = os.path.splitext(file.path)[1].lower()
        grammar = (
            "javascript"
            if extension in _JS_EXTENSIONS
            else "tsx"
            if extension == ".tsx"
            else "typescript"
        )
        language = "javascript" if extension in _JS_EXTENSIONS else "typescript"
        root, data = parse(grammar, source)
        builder = TreeSitterBuilder(file.path)
        module_qn = typescript_module_qualname(file.path)
        module_name = module_qn.rsplit(".", 1)[-1]
        module_id = node_id(file.path, module_qn, NodeKind.MODULE)
        builder.nodes.append(
            Node(
                id=module_id,
                kind=NodeKind.MODULE,
                name=module_name,
                qualname=module_qn,
                language=language,
                file=file.path,
                start_line=1,
                end_line=source.count("\n") + 1,
                is_exported=True,
            )
        )
        self._visit_statements(
            named_children(root),
            builder,
            data,
            language,
            parent_id=module_id,
            parent_qn=module_qn,
            exported=False,
        )
        errors = (
            [f"Tree-sitter parsed {language} source with syntax errors"]
            if root.has_error
            else []
        )
        return AnalyzerResult(
            nodes=builder.nodes,
            edges=builder.edges,
            unresolved=builder.unresolved,
            errors=errors,
        )

    def _visit_statements(
        self,
        statements: list[Any],
        builder: TreeSitterBuilder,
        data: bytes,
        language: str,
        *,
        parent_id: str,
        parent_qn: str,
        exported: bool,
    ) -> None:
        for statement in statements:
            node_type = statement.type
            if node_type in {"export_statement", "export_clause"}:
                source_node = field(statement, "source")
                if source_node is not None:
                    builder.ref(
                        parent_id,
                        node_text(source_node, data).strip("'\""),
                        EdgeKind.IMPORTS,
                        start_line(statement),
                    )
                declarations = [
                    child
                    for child in named_children(statement)
                    if child.type not in {"string", "export_clause", "namespace_export"}
                ]
                if declarations:
                    self._visit_statements(
                        declarations,
                        builder,
                        data,
                        language,
                        parent_id=parent_id,
                        parent_qn=parent_qn,
                        exported=True,
                    )
                continue
            if node_type == "import_statement":
                source_node = field(statement, "source")
                if source_node is None:
                    source_node = next(
                        (
                            child
                            for child in named_children(statement)
                            if child.type == "string"
                        ),
                        None,
                    )
                if source_node is not None:
                    builder.ref(
                        parent_id,
                        node_text(source_node, data).strip("'\""),
                        EdgeKind.IMPORTS,
                        start_line(statement),
                    )
                continue
            if node_type in {"class_declaration", "abstract_class_declaration"}:
                self._container(
                    statement,
                    NodeKind.CLASS,
                    builder,
                    data,
                    language,
                    parent_id,
                    parent_qn,
                    exported,
                )
                continue
            if node_type == "interface_declaration":
                self._container(
                    statement,
                    NodeKind.INTERFACE,
                    builder,
                    data,
                    language,
                    parent_id,
                    parent_qn,
                    exported,
                )
                continue
            if node_type == "enum_declaration":
                self._container(
                    statement,
                    NodeKind.ENUM,
                    builder,
                    data,
                    language,
                    parent_id,
                    parent_qn,
                    exported,
                )
                continue
            if node_type in {"module_declaration", "internal_module"}:
                self._container(
                    statement,
                    NodeKind.NAMESPACE,
                    builder,
                    data,
                    language,
                    parent_id,
                    parent_qn,
                    exported,
                )
                continue
            if node_type in {
                "function_declaration",
                "generator_function_declaration",
            }:
                self._function(
                    statement,
                    builder,
                    data,
                    language,
                    parent_id,
                    parent_qn,
                    exported=exported,
                    is_method=False,
                )
                continue
            if node_type == "type_alias_declaration":
                self._simple_definition(
                    statement,
                    NodeKind.TYPE_ALIAS,
                    builder,
                    data,
                    language,
                    parent_id,
                    parent_qn,
                    exported,
                )
                continue
            if node_type in {"lexical_declaration", "variable_declaration"}:
                self._variables(
                    statement,
                    builder,
                    data,
                    language,
                    parent_id,
                    parent_qn,
                    exported,
                )

    def _container(
        self,
        item: Any,
        kind: str,
        builder: TreeSitterBuilder,
        data: bytes,
        language: str,
        parent_id: str,
        parent_qn: str,
        exported: bool,
    ) -> None:
        name = _name(item, data)
        if not name:
            return
        qn = f"{parent_qn}.{name}" if parent_qn != "(root)" else name
        item_id = node_id(builder.file, qn, kind)
        header = _header(item, data)
        doc = _doc_comment(item, data)
        bases, implements = self._heritage(item, data)
        builder.nodes.append(
            Node(
                id=item_id,
                kind=kind,
                name=name,
                qualname=qn,
                language=language,
                file=builder.file,
                start_line=start_line(item),
                end_line=end_line(item),
                signature=header,
                docstring=doc,
                summary=_summary(doc),
                decorators=_decorators(item, data),
                bases=bases,
                visibility=Visibility.PUBLIC,
                is_exported=exported,
                is_abstract=item.type.startswith("abstract_")
                or " abstract " in f" {header} ",
            )
        )
        builder.contains(parent_id, item_id, start_line(item))
        for base in bases:
            builder.ref(item_id, base, EdgeKind.EXTENDS, start_line(item))
        for interface in implements:
            builder.ref(item_id, interface, EdgeKind.IMPLEMENTS, start_line(item))

        body = field(item, "body")
        if body is None:
            body = next(
                (
                    child
                    for child in named_children(item)
                    if child.type
                    in {"class_body", "object_type", "enum_body", "statement_block"}
                ),
                None,
            )
        if body is None:
            return
        if kind == NodeKind.NAMESPACE:
            self._visit_statements(
                named_children(body),
                builder,
                data,
                language,
                parent_id=item_id,
                parent_qn=qn,
                exported=exported,
            )
        else:
            self._members(
                named_children(body), builder, data, language, item_id, qn, kind
            )

    @staticmethod
    def _heritage(item: Any, data: bytes) -> tuple[list[str], list[str]]:
        header = _header(item, data)
        extends: list[str] = []
        implements: list[str] = []
        extends_match = re.search(
            r"\bextends\s+(.+?)(?=\s+implements\b|\s*\{|$)", header
        )
        if extends_match:
            extends = [
                value.strip()
                for value in extends_match.group(1).split(",")
                if value.strip()
            ]
        implements_match = re.search(r"\bimplements\s+(.+?)(?=\s*\{|$)", header)
        if implements_match:
            implements = [
                value.strip()
                for value in implements_match.group(1).split(",")
                if value.strip()
            ]
        return extends, implements

    def _members(
        self,
        members: list[Any],
        builder: TreeSitterBuilder,
        data: bytes,
        language: str,
        parent_id: str,
        parent_qn: str,
        parent_kind: str,
    ) -> None:
        for member in members:
            if member.type in {
                "method_definition",
                "method_signature",
                "abstract_method_signature",
            }:
                self._function(
                    member,
                    builder,
                    data,
                    language,
                    parent_id,
                    parent_qn,
                    exported=False,
                    is_method=True,
                )
            elif member.type in {
                "public_field_definition",
                "field_definition",
                "property_signature",
                "required_parameter",
                "optional_parameter",
            }:
                self._simple_definition(
                    member,
                    NodeKind.FIELD,
                    builder,
                    data,
                    language,
                    parent_id,
                    parent_qn,
                    exported=False,
                )
            elif (
                member.type in {"enum_assignment", "property_identifier"}
                and parent_kind == NodeKind.ENUM
            ):
                self._simple_definition(
                    member,
                    NodeKind.CONSTANT,
                    builder,
                    data,
                    language,
                    parent_id,
                    parent_qn,
                    exported=False,
                )

    def _function(
        self,
        item: Any,
        builder: TreeSitterBuilder,
        data: bytes,
        language: str,
        parent_id: str,
        parent_qn: str,
        *,
        exported: bool,
        is_method: bool,
    ) -> None:
        name = _name(item, data)
        if not name:
            return
        kind = NodeKind.METHOD if is_method else NodeKind.FUNCTION
        qn = f"{parent_qn}.{name}" if parent_qn != "(root)" else name
        item_id = node_id(builder.file, qn, kind)
        header = _header(item, data)
        doc = _doc_comment(item, data)
        visibility = _visibility(item, data)
        builder.nodes.append(
            Node(
                id=item_id,
                kind=kind,
                name=name,
                qualname=qn,
                language=language,
                file=builder.file,
                start_line=start_line(item),
                end_line=end_line(item),
                signature=header,
                docstring=doc,
                summary=_summary(doc),
                decorators=_decorators(item, data),
                visibility=visibility,
                is_exported=exported and visibility == Visibility.PUBLIC,
                is_async=bool(re.search(r"\basync\b", header)),
                is_abstract="abstract" in header.split(),
            )
        )
        builder.contains(parent_id, item_id, start_line(item))
        body = field(item, "body")
        if body is not None:
            self._calls(body, item_id, builder, data)

    def _variables(
        self,
        declaration: Any,
        builder: TreeSitterBuilder,
        data: bytes,
        language: str,
        parent_id: str,
        parent_qn: str,
        exported: bool,
    ) -> None:
        for item in named_children(declaration):
            if item.type != "variable_declarator":
                continue
            value = field(item, "value")
            is_function = value is not None and value.type in {
                "arrow_function",
                "function_expression",
                "generator_function",
            }
            kind = NodeKind.FUNCTION if is_function else NodeKind.CONSTANT
            name = _name(item, data)
            if not name:
                continue
            qn = f"{parent_qn}.{name}" if parent_qn != "(root)" else name
            item_id = node_id(builder.file, qn, kind)
            doc = _doc_comment(declaration, data)
            signature = compact(node_text(declaration, data))
            if value is not None and is_function:
                body = field(value, "body")
                if body is not None:
                    prefix = data[declaration.start_byte : body.start_byte].decode(
                        "utf-8", errors="replace"
                    )
                    signature = compact(prefix)
            builder.nodes.append(
                Node(
                    id=item_id,
                    kind=kind,
                    name=name,
                    qualname=qn,
                    language=language,
                    file=builder.file,
                    start_line=start_line(item),
                    end_line=end_line(item),
                    signature=signature.rstrip(";"),
                    docstring=doc,
                    summary=_summary(doc),
                    visibility=Visibility.PRIVATE
                    if name.startswith("_")
                    else Visibility.PUBLIC,
                    is_exported=exported and not name.startswith("_"),
                    is_async=is_function
                    and value is not None
                    and "async" in _header(value, data).split(),
                )
            )
            builder.contains(parent_id, item_id, start_line(item))
            if is_function and value is not None:
                self._calls(value, item_id, builder, data)

    def _simple_definition(
        self,
        item: Any,
        kind: str,
        builder: TreeSitterBuilder,
        data: bytes,
        language: str,
        parent_id: str,
        parent_qn: str,
        exported: bool,
    ) -> None:
        name = _name(item, data)
        if not name and item.type == "property_identifier":
            name = compact(node_text(item, data))
        if not name:
            return
        qn = f"{parent_qn}.{name}" if parent_qn != "(root)" else name
        item_id = node_id(builder.file, qn, kind)
        doc = _doc_comment(item, data)
        visibility = _visibility(item, data)
        builder.nodes.append(
            Node(
                id=item_id,
                kind=kind,
                name=name,
                qualname=qn,
                language=language,
                file=builder.file,
                start_line=start_line(item),
                end_line=end_line(item),
                signature=_header(item, data),
                docstring=doc,
                summary=_summary(doc),
                visibility=visibility,
                is_exported=exported and visibility == Visibility.PUBLIC,
            )
        )
        builder.contains(parent_id, item_id, start_line(item))

    @staticmethod
    def _calls(
        body: Any, function_id: str, builder: TreeSitterBuilder, data: bytes
    ) -> None:
        for node in descendants(body):
            if node.type == "call_expression":
                target = field(node, "function")
                if target is None and named_children(node):
                    target = named_children(node)[0]
                if target is not None:
                    builder.ref(
                        function_id,
                        node_text(target, data),
                        EdgeKind.CALLS,
                        start_line(node),
                    )
            elif node.type == "new_expression":
                target = field(node, "constructor")
                if target is None and named_children(node):
                    target = named_children(node)[0]
                if target is not None:
                    builder.ref(
                        function_id,
                        node_text(target, data),
                        EdgeKind.INSTANTIATES,
                        start_line(node),
                    )
