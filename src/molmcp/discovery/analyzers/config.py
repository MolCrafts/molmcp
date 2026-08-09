"""JSON and TOML configuration analyzers."""

from __future__ import annotations

import json
import re
import tomllib
from typing import Any

from ..schema import Edge, EdgeKind, FileRecord, Node, NodeKind, node_id
from .base import AnalyzerResult


def config_qualname(path: str) -> str:
    """Use the normalized path as the unambiguous config-document name."""
    return path.replace("\\", "/")


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return type(value).__name__


def _value_summary(value: Any) -> str:
    if isinstance(value, dict):
        suffix = "key" if len(value) == 1 else "keys"
        return f"{len(value)} {suffix}"
    if isinstance(value, list):
        suffix = "item" if len(value) == 1 else "items"
        return f"{len(value)} {suffix}"
    rendered = json.dumps(value, ensure_ascii=False, default=str)
    return rendered if len(rendered) <= 160 else f"{rendered[:157]}..."


class _ConfigAnalyzer:
    language: str
    extensions: frozenset[str]

    def analyze(self, file: FileRecord, source: str) -> AnalyzerResult:
        try:
            value = self._loads(source)
        except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            return AnalyzerResult(errors=[f"{type(exc).__name__}: {exc}"])

        document_qn = config_qualname(file.path)
        document_id = node_id(file.path, document_qn, NodeKind.CONFIG)
        line_count = source.count("\n") + 1
        root_type = _value_type(value)
        document = Node(
            id=document_id,
            kind=NodeKind.CONFIG,
            name=file.path.replace("\\", "/").rsplit("/", 1)[-1],
            qualname=document_qn,
            language=self.language,
            file=file.path,
            start_line=1,
            end_line=line_count,
            summary=f"{self.language.upper()} {root_type}",
            is_exported=True,
            metadata={"format": self.language, "root_type": root_type},
        )
        nodes = [document]
        edges: list[Edge] = []
        if not isinstance(value, dict):
            return AnalyzerResult(nodes=nodes)

        for key, item in value.items():
            name = str(key)
            qn = f"{document_qn}::{name}"
            key_id = node_id(file.path, qn, NodeKind.CONFIG_KEY)
            line = self._key_line(source, name)
            kind = _value_type(item)
            metadata: dict[str, Any] = {
                "value_type": kind,
                "top_level": True,
            }
            if isinstance(item, dict):
                metadata["child_keys"] = [str(child) for child in item]
            elif isinstance(item, (str, int, float, bool)) or item is None:
                metadata["value"] = item
            node = Node(
                id=key_id,
                kind=NodeKind.CONFIG_KEY,
                name=name,
                qualname=qn,
                language=self.language,
                file=file.path,
                start_line=line,
                end_line=line,
                signature=f"{name}: {kind}",
                summary=_value_summary(item),
                is_exported=True,
                metadata=metadata,
            )
            nodes.append(node)
            edges.append(
                Edge(
                    source=document_id,
                    target=key_id,
                    kind=EdgeKind.CONTAINS,
                    file=file.path,
                    line=line,
                )
            )
        return AnalyzerResult(nodes=nodes, edges=edges)

    def _loads(self, source: str) -> Any:
        raise NotImplementedError

    def _key_line(self, source: str, key: str) -> int:
        raise NotImplementedError


class JsonAnalyzer(_ConfigAnalyzer):
    """Parse JSON with the standard library and index top-level keys."""

    language = "json"
    extensions = frozenset({".json"})

    def _loads(self, source: str) -> Any:
        return json.loads(source)

    def _key_line(self, source: str, key: str) -> int:
        quoted = re.escape(json.dumps(key, ensure_ascii=False))
        pattern = re.compile(rf"^\s*{quoted}\s*:")
        for number, line in enumerate(source.splitlines(), start=1):
            if pattern.match(line):
                return number
        return 1


class TomlAnalyzer(_ConfigAnalyzer):
    """Parse TOML with ``tomllib`` and index top-level keys/tables."""

    language = "toml"
    extensions = frozenset({".toml"})

    def _loads(self, source: str) -> Any:
        return tomllib.loads(source)

    def _key_line(self, source: str, key: str) -> int:
        escaped = re.escape(key)
        assignment = re.compile(rf"^\s*(?:{escaped}|[\"']{escaped}[\"'])\s*=")
        table = re.compile(
            rf"^\s*\[\[?\s*(?:{escaped}|[\"']{escaped}[\"'])(?:\.|\s*\])"
        )
        for number, line in enumerate(source.splitlines(), start=1):
            if assignment.match(line) or table.match(line):
                return number
        return 1
