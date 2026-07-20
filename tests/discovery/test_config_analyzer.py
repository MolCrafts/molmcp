from __future__ import annotations

from molmcp.discovery.analyzers.config import JsonAnalyzer, TomlAnalyzer
from molmcp.discovery.schema import FileRecord, NodeKind


def test_json_indexes_top_level_keys():
    source = '{\n  "schema_version": "1",\n  "sources": {"molpy": "pkg:molpy"}\n}'
    result = JsonAnalyzer().analyze(
        FileRecord("molcrafts.json", "json", "x", len(source)), source
    )
    keys = {
        node.name: node for node in result.nodes if node.kind == NodeKind.CONFIG_KEY
    }
    assert keys["schema_version"].metadata["value"] == "1"
    assert keys["sources"].metadata["child_keys"] == ["molpy"]
    assert keys["sources"].start_line == 3


def test_toml_indexes_top_level_tables_and_reports_parse_errors():
    source = '[project]\nname = "molmcp"\n\n[tool.ruff]\nline-length = 88\n'
    result = TomlAnalyzer().analyze(
        FileRecord("pyproject.toml", "toml", "x", len(source)), source
    )
    keys = {node.name for node in result.nodes if node.kind == NodeKind.CONFIG_KEY}
    assert keys == {"project", "tool"}

    broken = TomlAnalyzer().analyze(FileRecord("bad.toml", "toml", "x", 3), "[x")
    assert broken.nodes == []
    assert broken.errors
