"""Deterministic Markdown structure analyzer.

Markdown is indexed as a document containing hierarchical heading sections and
fenced examples. Qualified inline-code references are left unresolved so the
normal graph resolver can connect them to code symbols when possible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..schema import (
    Edge,
    EdgeKind,
    FileRecord,
    Node,
    NodeKind,
    UnresolvedRef,
    node_id,
)
from .base import AnalyzerResult

_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)\s*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_INLINE_CODE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
_SYMBOL = re.compile(
    r"(?:@[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|"
    r"[A-Za-z_]\w*(?:(?:::|\.)[A-Za-z_]\w*)+)"
)


def markdown_qualname(path: str) -> str:
    normalized = path.replace("\\", "/")
    return re.sub(r"\.(?:md|mdx)$", "", normalized, flags=re.IGNORECASE)


def _slug(title: str) -> str:
    value = re.sub(r"[^\w\-]+", "-", title.casefold(), flags=re.UNICODE)
    return value.strip("-") or "section"


def _summary(text: str | None) -> str | None:
    if not text:
        return None
    for line in text.splitlines():
        stripped = re.sub(r"^[>*_\-\s]+", "", line).strip()
        if stripped:
            return stripped
    return None


@dataclass(slots=True)
class _Heading:
    line: int
    level: int
    title: str
    content_end: int = 0
    section_end: int = 0
    node: Node | None = None


@dataclass(slots=True)
class _CodeFence:
    start: int
    end: int
    info: str
    code: str


class MarkdownAnalyzer:
    """Extract headings, prose sections, fenced examples, and symbol refs."""

    language = "markdown"
    extensions = frozenset({".md", ".mdx"})

    def analyze(self, file: FileRecord, source: str) -> AnalyzerResult:
        lines = source.splitlines()
        line_count = source.count("\n") + 1
        headings, fences, errors = self._scan(lines)
        self._set_heading_spans(headings, line_count)

        document_qn = markdown_qualname(file.path)
        document_id = node_id(file.path, document_qn, NodeKind.DOCUMENT)
        first_heading_line = headings[0].line if headings else line_count + 1
        preamble = self._prose(lines, 1, first_heading_line - 1, fences)
        document = Node(
            id=document_id,
            kind=NodeKind.DOCUMENT,
            name=file.path.replace("\\", "/").rsplit("/", 1)[-1],
            qualname=document_qn,
            language=self.language,
            file=file.path,
            start_line=1,
            end_line=line_count,
            docstring=preamble or None,
            summary=_summary(preamble),
            is_exported=True,
            metadata={"format": "markdown"},
        )
        nodes = [document]
        edges: list[Edge] = []
        unresolved: list[UnresolvedRef] = []
        section_stack: list[_Heading] = []
        slug_counts: dict[str, int] = {}

        for heading in headings:
            while section_stack and section_stack[-1].level >= heading.level:
                section_stack.pop()
            parent = section_stack[-1].node if section_stack else document
            base_slug = _slug(heading.title)
            slug_counts[base_slug] = slug_counts.get(base_slug, 0) + 1
            suffix = "" if slug_counts[base_slug] == 1 else f"-{slug_counts[base_slug]}"
            qn = f"{parent.qualname}::{base_slug}{suffix}"
            section_id = node_id(file.path, qn, NodeKind.SECTION)
            prose = self._prose(lines, heading.line + 1, heading.content_end, fences)
            section = Node(
                id=section_id,
                kind=NodeKind.SECTION,
                name=heading.title,
                qualname=qn,
                language=self.language,
                file=file.path,
                start_line=heading.line,
                end_line=heading.section_end,
                signature=f"{'#' * heading.level} {heading.title}",
                docstring=prose or None,
                summary=_summary(prose),
                is_exported=True,
                metadata={"heading_level": heading.level},
            )
            heading.node = section
            nodes.append(section)
            edges.append(
                Edge(
                    source=parent.id,
                    target=section.id,
                    kind=EdgeKind.CONTAINS,
                    file=file.path,
                    line=heading.line,
                )
            )
            section_stack.append(heading)

        self._add_references(document, preamble, 1, unresolved)
        for heading in headings:
            if heading.node is None:
                continue
            prose = heading.node.docstring or ""
            self._add_references(heading.node, prose, heading.line + 1, unresolved)

        for number, fence in enumerate(fences, start=1):
            parent = self._section_at(headings, fence.start) or document
            qn = f"{parent.qualname}::example-{number}"
            example_id = node_id(file.path, qn, NodeKind.EXAMPLE)
            language = fence.info.split(maxsplit=1)[0] if fence.info else "text"
            example = Node(
                id=example_id,
                kind=NodeKind.EXAMPLE,
                name=f"example-{number}",
                qualname=qn,
                language=language,
                file=file.path,
                start_line=fence.start,
                end_line=fence.end,
                signature=fence.info or None,
                docstring=fence.code or None,
                summary=_summary(fence.code),
                is_exported=True,
                metadata={
                    "fence_info": fence.info,
                    "code": fence.code,
                    "source_language": self.language,
                },
            )
            nodes.append(example)
            edges.append(
                Edge(
                    source=parent.id,
                    target=example.id,
                    kind=EdgeKind.CONTAINS,
                    file=file.path,
                    line=fence.start,
                )
            )

        return AnalyzerResult(
            nodes=nodes, edges=edges, unresolved=unresolved, errors=errors
        )

    @staticmethod
    def _scan(lines: list[str]) -> tuple[list[_Heading], list[_CodeFence], list[str]]:
        headings: list[_Heading] = []
        fences: list[_CodeFence] = []
        errors: list[str] = []
        index = 0
        while index < len(lines):
            fence_match = _FENCE.match(lines[index])
            if fence_match:
                marker = fence_match.group(1)
                info = fence_match.group(2).strip()
                end = index + 1
                while end < len(lines):
                    closing = _FENCE.match(lines[end])
                    if (
                        closing
                        and closing.group(1)[0] == marker[0]
                        and len(closing.group(1)) >= len(marker)
                    ):
                        break
                    end += 1
                if end == len(lines):
                    errors.append(f"unclosed Markdown fence at line {index + 1}")
                    fence_end = len(lines)
                    code_lines = lines[index + 1 :]
                else:
                    fence_end = end + 1
                    code_lines = lines[index + 1 : end]
                fences.append(
                    _CodeFence(
                        start=index + 1,
                        end=fence_end,
                        info=info,
                        code="\n".join(code_lines),
                    )
                )
                index = end + 1
                continue

            atx = _ATX_HEADING.match(lines[index])
            if atx:
                headings.append(
                    _Heading(
                        line=index + 1,
                        level=len(atx.group(1)),
                        title=atx.group(2).strip(),
                    )
                )
                index += 1
                continue
            if index + 1 < len(lines):
                setext = _SETEXT.match(lines[index + 1])
                if setext and lines[index].strip():
                    headings.append(
                        _Heading(
                            line=index + 1,
                            level=1 if setext.group(1).startswith("=") else 2,
                            title=lines[index].strip(),
                        )
                    )
                    index += 2
                    continue
            index += 1
        return headings, fences, errors

    @staticmethod
    def _set_heading_spans(headings: list[_Heading], line_count: int) -> None:
        for index, heading in enumerate(headings):
            heading.content_end = (
                headings[index + 1].line - 1
                if index + 1 < len(headings)
                else line_count
            )
            heading.section_end = line_count
            for candidate in headings[index + 1 :]:
                if candidate.level <= heading.level:
                    heading.section_end = candidate.line - 1
                    break

    @staticmethod
    def _prose(lines: list[str], start: int, end: int, fences: list[_CodeFence]) -> str:
        if end < start:
            return ""
        excluded: set[int] = set()
        for fence in fences:
            excluded.update(range(fence.start, fence.end + 1))
        selected = [
            lines[line - 1]
            for line in range(max(1, start), min(end, len(lines)) + 1)
            if line not in excluded and not _ATX_HEADING.match(lines[line - 1])
        ]
        return "\n".join(selected).strip()

    @staticmethod
    def _section_at(headings: list[_Heading], line: int) -> Node | None:
        candidates = [
            heading
            for heading in headings
            if heading.node is not None and heading.line <= line <= heading.section_end
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda heading: (heading.level, heading.line)).node

    @staticmethod
    def _add_references(
        node: Node, prose: str, start: int, output: list[UnresolvedRef]
    ) -> None:
        seen: set[str] = set()
        for match in _INLINE_CODE.finditer(prose):
            value = match.group(1).strip()
            if not _SYMBOL.fullmatch(value) or value in seen:
                continue
            seen.add(value)
            line = start + prose[: match.start()].count("\n")
            output.append(
                UnresolvedRef(
                    from_node=node.id,
                    name=value,
                    kind=EdgeKind.REFERENCES,
                    file=node.file,
                    line=line,
                )
            )
