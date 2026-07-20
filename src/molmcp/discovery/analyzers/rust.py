"""Tree-sitter-backed Rust analyzer.

Extraction is deliberately language-local. Imports, calls, inheritance, and
trait implementations are emitted as unresolved references for the resolver;
only containment is materialized immediately.
"""

from __future__ import annotations

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


def rust_module_qualname(path: str) -> str:
    """Derive a useful ``::`` module name from a Rust source path."""
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    if parts and parts[-1].endswith(".rs"):
        parts[-1] = parts[-1][:-3]
    if "src" in parts:
        at = len(parts) - 1 - parts[::-1].index("src")
        prefix = parts[:at]
        tail = parts[at + 1 :]
        parts = ([prefix[-1]] if prefix else []) + tail
    if parts and parts[-1] in {"lib", "main", "mod"}:
        parts.pop()
    return "::".join(parts) or "(crate)"


def _summary(docstring: str | None) -> str | None:
    if not docstring:
        return None
    return next((line.strip() for line in docstring.splitlines() if line.strip()), None)


def _doc_comment(node: Any, source: str) -> str | None:
    """Collect an immediately preceding Rust doc-comment block."""
    lines = source.splitlines()
    index = start_line(node) - 2
    while index >= 0 and lines[index].lstrip().startswith("#["):
        index -= 1
    collected: list[str] = []
    while index >= 0:
        stripped = lines[index].strip()
        if stripped.startswith(("///", "//!")):
            collected.append(stripped[3:].lstrip())
            index -= 1
            continue
        break
    if collected:
        return "\n".join(reversed(collected)).strip() or None

    # The common single/multi-line /** ... */ form.
    prefix = "\n".join(lines[: index + 1])
    match = re.search(r"/\*\*(!?)(.*?)\*/\s*$", prefix, re.DOTALL)
    if not match:
        return None
    body = re.sub(r"^\s*\* ?", "", match.group(2), flags=re.MULTILINE)
    return body.strip() or None


def _name(node: Any, data: bytes) -> str | None:
    name_node = field(node, "name")
    return compact(node_text(name_node, data)) if name_node is not None else None


def _header(node: Any, data: bytes) -> str:
    body = field(node, "body")
    end = body.start_byte if body is not None else node.end_byte
    return compact(
        data[node.start_byte : end].decode("utf-8", errors="replace")
    ).rstrip(";")


def _is_public(node: Any, data: bytes, *, inherited: bool = False) -> bool:
    if inherited:
        return True
    visibility = field(node, "visibility")
    if visibility is not None:
        return node_text(visibility, data).strip().startswith("pub")
    return bool(re.match(r"\s*pub(?:\([^)]*\))?\s", node_text(node, data)))


def _type_name(text: str) -> str:
    """Strip references/generics enough to make an implementation qualifier."""
    value = compact(text)
    value = re.sub(r"^(?:&\s*(?:'\w+\s*)?(?:mut\s+)?|mut\s+)", "", value)
    return re.sub(r"<.*>", "", value).strip() or value


class RustAnalyzer:
    """Extract Rust definitions and references using Tree-sitter."""

    language = "rust"
    extensions = frozenset({".rs"})

    def analyze(self, file: FileRecord, source: str) -> AnalyzerResult:
        root, data = parse("rust", source)
        builder = TreeSitterBuilder(file.path)
        module_qn = rust_module_qualname(file.path)
        module_name = module_qn.rsplit("::", 1)[-1]
        module_id = node_id(file.path, module_qn, NodeKind.MODULE)
        builder.nodes.append(
            Node(
                id=module_id,
                kind=NodeKind.MODULE,
                name=module_name,
                qualname=module_qn,
                language=self.language,
                file=file.path,
                start_line=1,
                end_line=source.count("\n") + 1,
                is_exported=True,
            )
        )
        self._visit_items(
            named_children(root),
            builder,
            data,
            source,
            parent_id=module_id,
            parent_qn=module_qn,
            parent_kind=NodeKind.MODULE,
            inherited_exported=True,
        )
        errors = (
            ["Tree-sitter parsed Rust source with syntax errors"]
            if root.has_error
            else []
        )
        return AnalyzerResult(
            nodes=builder.nodes,
            edges=builder.edges,
            unresolved=builder.unresolved,
            errors=errors,
        )

    def _visit_items(
        self,
        items: list[Any],
        builder: TreeSitterBuilder,
        data: bytes,
        source: str,
        *,
        parent_id: str,
        parent_qn: str,
        parent_kind: str,
        inherited_exported: bool,
    ) -> None:
        for item in items:
            node_type = item.type
            if node_type in {"use_declaration", "extern_crate_declaration"}:
                target = self._import_target(item, data)
                if target:
                    builder.ref(parent_id, target, EdgeKind.IMPORTS, start_line(item))
                continue
            if node_type == "mod_item":
                self._module(item, builder, data, source, parent_id, parent_qn)
                continue
            if node_type == "impl_item":
                self._implementation(item, builder, data, source, parent_id, parent_qn)
                continue
            if node_type in {
                "struct_item",
                "enum_item",
                "trait_item",
                "union_item",
            }:
                self._container(item, builder, data, source, parent_id, parent_qn)
                continue
            if node_type in {"function_item", "function_signature_item"}:
                self._function(
                    item,
                    builder,
                    data,
                    source,
                    parent_id,
                    parent_qn,
                    is_method=parent_kind in {NodeKind.TRAIT, NodeKind.NAMESPACE},
                    inherited_exported=(
                        inherited_exported and parent_kind == NodeKind.TRAIT
                    ),
                )
                continue
            if node_type in {"type_item", "associated_type"}:
                self._simple_definition(
                    item,
                    NodeKind.TYPE_ALIAS,
                    builder,
                    data,
                    source,
                    parent_id,
                    parent_qn,
                    inherited_exported,
                )
                continue
            if node_type in {"const_item", "static_item", "enum_variant"}:
                self._simple_definition(
                    item,
                    NodeKind.CONSTANT,
                    builder,
                    data,
                    source,
                    parent_id,
                    parent_qn,
                    inherited_exported,
                )
                continue
            if node_type == "field_declaration":
                self._simple_definition(
                    item,
                    NodeKind.FIELD,
                    builder,
                    data,
                    source,
                    parent_id,
                    parent_qn,
                    inherited_exported=False,
                )

    @staticmethod
    def _import_target(item: Any, data: bytes) -> str:
        argument = field(item, "argument") or field(item, "path")
        if argument is not None:
            return node_text(argument, data).strip()
        text = node_text(item, data).strip().rstrip(";")
        return re.sub(r"^(?:pub\s+)?(?:use|extern\s+crate)\s+", "", text).strip()

    def _module(
        self,
        item: Any,
        builder: TreeSitterBuilder,
        data: bytes,
        source: str,
        parent_id: str,
        parent_qn: str,
    ) -> None:
        name = _name(item, data)
        if not name:
            return
        qn = f"{parent_qn}::{name}"
        item_id = node_id(builder.file, qn, NodeKind.MODULE)
        public = _is_public(item, data)
        doc = _doc_comment(item, source)
        builder.nodes.append(
            Node(
                id=item_id,
                kind=NodeKind.MODULE,
                name=name,
                qualname=qn,
                language=self.language,
                file=builder.file,
                start_line=start_line(item),
                end_line=end_line(item),
                signature=_header(item, data),
                docstring=doc,
                summary=_summary(doc),
                visibility=Visibility.PUBLIC if public else Visibility.PRIVATE,
                is_exported=public,
            )
        )
        builder.contains(parent_id, item_id, start_line(item))
        body = field(item, "body")
        if body is None:
            builder.ref(item_id, name, EdgeKind.IMPORTS, start_line(item))
            return
        self._visit_items(
            named_children(body),
            builder,
            data,
            source,
            parent_id=item_id,
            parent_qn=qn,
            parent_kind=NodeKind.MODULE,
            inherited_exported=public,
        )

    def _container(
        self,
        item: Any,
        builder: TreeSitterBuilder,
        data: bytes,
        source: str,
        parent_id: str,
        parent_qn: str,
    ) -> None:
        kind_by_type = {
            "struct_item": NodeKind.STRUCT,
            "enum_item": NodeKind.ENUM,
            "trait_item": NodeKind.TRAIT,
            "union_item": NodeKind.STRUCT,
        }
        kind = kind_by_type[item.type]
        name = _name(item, data)
        if not name:
            return
        qn = f"{parent_qn}::{name}"
        item_id = node_id(builder.file, qn, kind)
        public = _is_public(item, data)
        doc = _doc_comment(item, source)
        header = _header(item, data)
        bases: list[str] = []
        if kind == NodeKind.TRAIT:
            match = re.search(
                rf"\btrait\s+{re.escape(name)}(?:\s*<[^{{>]*>)?\s*:\s*(.*?)(?:\s+where\b|$)",
                header,
            )
            if match:
                bases = [
                    part.strip() for part in match.group(1).split("+") if part.strip()
                ]
        builder.nodes.append(
            Node(
                id=item_id,
                kind=kind,
                name=name,
                qualname=qn,
                language=self.language,
                file=builder.file,
                start_line=start_line(item),
                end_line=end_line(item),
                signature=header,
                docstring=doc,
                summary=_summary(doc),
                bases=bases,
                visibility=Visibility.PUBLIC if public else Visibility.PRIVATE,
                is_exported=public,
            )
        )
        builder.contains(parent_id, item_id, start_line(item))
        for base in bases:
            builder.ref(item_id, base, EdgeKind.EXTENDS, start_line(item))
        body = field(item, "body")
        if body is not None:
            self._visit_items(
                named_children(body),
                builder,
                data,
                source,
                parent_id=item_id,
                parent_qn=qn,
                parent_kind=kind,
                inherited_exported=public,
            )

    def _implementation(
        self,
        item: Any,
        builder: TreeSitterBuilder,
        data: bytes,
        source: str,
        parent_id: str,
        parent_qn: str,
    ) -> None:
        target_node = field(item, "type")
        target = node_text(target_node, data) if target_node is not None else "unknown"
        target = _type_name(target)
        trait_node = field(item, "trait")
        trait = compact(node_text(trait_node, data)) if trait_node is not None else None
        label = f"impl {trait} for {target}" if trait else f"impl {target}"
        qn = f"{parent_qn}::{label}@{start_line(item)}"
        impl_id = node_id(builder.file, qn, NodeKind.NAMESPACE)
        doc = _doc_comment(item, source)
        builder.nodes.append(
            Node(
                id=impl_id,
                kind=NodeKind.NAMESPACE,
                name=label,
                qualname=qn,
                language=self.language,
                file=builder.file,
                start_line=start_line(item),
                end_line=end_line(item),
                signature=_header(item, data),
                docstring=doc,
                summary=_summary(doc),
                metadata={"implementation_target": target, "trait": trait},
            )
        )
        builder.contains(parent_id, impl_id, start_line(item))
        if trait:
            builder.ref(impl_id, trait, EdgeKind.IMPLEMENTS, start_line(item))
        body = field(item, "body")
        member_qn = f"{parent_qn}::{target}"
        if trait:
            member_qn = f"{member_qn}::{{{trait}}}"
        if body is not None:
            self._visit_items(
                named_children(body),
                builder,
                data,
                source,
                parent_id=impl_id,
                parent_qn=member_qn,
                parent_kind=NodeKind.NAMESPACE,
                inherited_exported=False,
            )

    def _function(
        self,
        item: Any,
        builder: TreeSitterBuilder,
        data: bytes,
        source: str,
        parent_id: str,
        parent_qn: str,
        *,
        is_method: bool,
        inherited_exported: bool,
    ) -> None:
        name = _name(item, data)
        if not name:
            return
        kind = NodeKind.METHOD if is_method else NodeKind.FUNCTION
        qn = f"{parent_qn}::{name}"
        item_id = node_id(builder.file, qn, kind)
        public = _is_public(item, data, inherited=inherited_exported)
        doc = _doc_comment(item, source)
        header = _header(item, data)
        builder.nodes.append(
            Node(
                id=item_id,
                kind=kind,
                name=name,
                qualname=qn,
                language=self.language,
                file=builder.file,
                start_line=start_line(item),
                end_line=end_line(item),
                signature=header,
                docstring=doc,
                summary=_summary(doc),
                visibility=Visibility.PUBLIC if public else Visibility.PRIVATE,
                is_exported=public,
                is_async=bool(re.search(r"\basync\s+fn\b", header)),
            )
        )
        builder.contains(parent_id, item_id, start_line(item))
        body = field(item, "body")
        if body is not None:
            self._calls(body, item_id, builder, data)

    def _simple_definition(
        self,
        item: Any,
        kind: str,
        builder: TreeSitterBuilder,
        data: bytes,
        source: str,
        parent_id: str,
        parent_qn: str,
        inherited_exported: bool,
    ) -> None:
        name = _name(item, data)
        if not name:
            return
        qn = f"{parent_qn}::{name}"
        item_id = node_id(builder.file, qn, kind)
        public = _is_public(item, data, inherited=inherited_exported)
        doc = _doc_comment(item, source)
        builder.nodes.append(
            Node(
                id=item_id,
                kind=kind,
                name=name,
                qualname=qn,
                language=self.language,
                file=builder.file,
                start_line=start_line(item),
                end_line=end_line(item),
                signature=_header(item, data),
                docstring=doc,
                summary=_summary(doc),
                visibility=Visibility.PUBLIC if public else Visibility.PRIVATE,
                is_exported=public,
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
                if target is not None:
                    builder.ref(
                        function_id,
                        node_text(target, data),
                        EdgeKind.CALLS,
                        start_line(node),
                    )
            elif node.type == "macro_invocation":
                target = field(node, "macro")
                if target is not None:
                    builder.ref(
                        function_id,
                        f"{node_text(target, data)}!",
                        EdgeKind.CALLS,
                        start_line(node),
                    )
