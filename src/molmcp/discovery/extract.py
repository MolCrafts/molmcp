"""Extraction (phase 1): a Snapshot -> a raw CodeGraph.

Dispatches each file to its language analyzer and aggregates the result.
Analyzer failures are recorded per-file and never abort the index — a
repo with un-analyzable files still produces a usable graph.
"""

from __future__ import annotations

import time
from pathlib import Path

from .analyzers import AnalyzerNotAvailable, get_analyzer_for
from .schema import CodeGraph, FileRecord
from .source import Snapshot


class Extractor:
    """Runs phase-1 extraction over a snapshot's files."""

    def extract(self, snapshot: Snapshot) -> CodeGraph:
        graph = CodeGraph()
        now = time.time()
        for wf in snapshot.files:
            record = FileRecord(
                path=wf.rel_path,
                language=wf.language,
                content_hash=wf.content_hash,
                size=wf.size,
                indexed_at=now,
            )
            analyzer = get_analyzer_for(wf.rel_path)
            if analyzer is None:
                graph.files.append(record)
                continue
            try:
                source = Path(wf.abs_path).read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError as exc:
                record.errors.append(f"read failed: {exc}")
                graph.files.append(record)
                continue
            try:
                result = analyzer.analyze(record, source)
            except AnalyzerNotAvailable as exc:
                record.errors.append(f"analyzer unavailable: {exc}")
                graph.files.append(record)
                continue
            except Exception as exc:  # noqa: BLE001 - isolate analyzer bugs
                record.errors.append(
                    f"analyzer error: {type(exc).__name__}: {exc}"
                )
                graph.files.append(record)
                continue
            graph.nodes.extend(result.nodes)
            graph.edges.extend(result.edges)
            graph.unresolved.extend(result.unresolved)
            record.node_count = len(result.nodes)
            record.errors.extend(result.errors)
            graph.files.append(record)
        return graph
