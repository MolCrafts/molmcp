"""Extraction (phase 1): a Snapshot -> a raw CodeGraph.

Dispatches each file to its language analyzer and aggregates the result.
When an :class:`ExtractCache` is supplied, unchanged files are served
from the cache and skip the analyzer entirely — that is what makes a
re-index incremental. Analyzer failures are recorded per-file and never
abort the index.
"""

from __future__ import annotations

import time
from pathlib import Path

from .analyzers import AnalyzerNotAvailable, get_analyzer_for
from .cache.extractcache import ExtractCache
from .schema import CodeGraph, FileRecord
from .source import Snapshot


class Extractor:
    """Runs phase-1 extraction over a snapshot's files."""

    def __init__(self, extract_cache: ExtractCache | None = None) -> None:
        self.cache = extract_cache
        self.stats: dict = {"analyzed": 0, "reused": 0, "files": 0}

    def extract(self, snapshot: Snapshot) -> CodeGraph:
        graph = CodeGraph()
        now = time.time()
        analyzed = 0
        reused = 0
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

            result = None
            if self.cache is not None:
                result = self.cache.get(wf.rel_path, wf.content_hash)

            if result is not None:
                reused += 1
            else:
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
                analyzed += 1
                if self.cache is not None:
                    self.cache.put(wf.rel_path, wf.content_hash, result)

            graph.nodes.extend(result.nodes)
            graph.edges.extend(result.edges)
            graph.unresolved.extend(result.unresolved)
            record.node_count = len(result.nodes)
            record.errors.extend(result.errors)
            graph.files.append(record)

        if self.cache is not None:
            self.cache.flush()
        self.stats = {
            "analyzed": analyzed,
            "reused": reused,
            "files": len(graph.files),
        }
        return graph
