from __future__ import annotations

from molmcp.discovery.analyzers.typescript import TypeScriptAnalyzer
from molmcp.discovery.schema import EdgeKind, FileRecord, NodeKind

_SOURCE = """
import { Scene } from "./scene";

export interface Renderable {
  render(scene: Scene): void;
}

/** Molecular viewer. */
export class Viewer implements Renderable {
  constructor(public scene: Scene) {}
  render(scene: Scene): void {
    drawScene(scene);
  }
}

export function createViewer(scene: Scene): Viewer {
  return new Viewer(scene);
}

export const DEFAULT_SCALE = 1.0;
"""


def _analyze():
    file = FileRecord(
        path="src/viewer.ts",
        language="typescript",
        content_hash="x",
        size=len(_SOURCE),
    )
    return TypeScriptAnalyzer().analyze(file, _SOURCE)


def test_typescript_extracts_exported_api():
    result = _analyze()
    assert result.errors == []
    by_name = {node.name: node for node in result.nodes}
    assert by_name["Renderable"].kind == NodeKind.INTERFACE
    assert by_name["Viewer"].kind == NodeKind.CLASS
    assert by_name["Viewer"].is_exported is True
    assert by_name["render"].kind == NodeKind.METHOD
    assert by_name["createViewer"].kind == NodeKind.FUNCTION
    assert by_name["DEFAULT_SCALE"].kind == NodeKind.CONSTANT


def test_typescript_records_imports_calls_and_inheritance_refs():
    result = _analyze()
    refs = {(ref.kind, ref.name) for ref in result.unresolved}
    assert any(kind == EdgeKind.IMPORTS and "scene" in name for kind, name in refs)
    assert any(kind == EdgeKind.CALLS and "drawScene" in name for kind, name in refs)
    assert any(
        kind in {EdgeKind.EXTENDS, EdgeKind.IMPLEMENTS} and "Renderable" in name
        for kind, name in refs
    )
