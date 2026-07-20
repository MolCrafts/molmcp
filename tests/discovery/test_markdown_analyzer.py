from __future__ import annotations

from molmcp.discovery.analyzers.markdown import MarkdownAnalyzer
from molmcp.discovery.schema import EdgeKind, FileRecord, NodeKind

_SOURCE = """MolCrafts guide.

# Analyze trajectories

Use `molpy.compute.RDF` to compute g(r).

## Example

```python
result = RDF(frame).run()
```
"""


def test_markdown_extracts_document_sections_examples_and_refs():
    file = FileRecord(
        path="docs/rdf.md",
        language="markdown",
        content_hash="x",
        size=len(_SOURCE),
    )
    result = MarkdownAnalyzer().analyze(file, _SOURCE)
    kinds = [node.kind for node in result.nodes]
    assert NodeKind.DOCUMENT in kinds
    assert kinds.count(NodeKind.SECTION) == 2
    example = next(node for node in result.nodes if node.kind == NodeKind.EXAMPLE)
    assert "RDF(frame)" in example.metadata["code"]
    assert any(
        ref.kind == EdgeKind.REFERENCES and ref.name == "molpy.compute.RDF"
        for ref in result.unresolved
    )


def test_markdown_reports_unclosed_fence_without_losing_content():
    file = FileRecord("README.md", "markdown", "x", 8)
    result = MarkdownAnalyzer().analyze(file, "# A\n\n```py\nx = 1")
    assert result.nodes
    assert any("unclosed Markdown fence" in error for error in result.errors)
