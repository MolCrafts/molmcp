"""Read-only survey of a legacy data directory.

Walks a source tree, classifies each directory against the four-tier
``Workspace → Project → Experiment → Run`` shape, and records the oddities
(broken links, escaping symlinks, empty files) a later transfer has to answer
for. **Nothing here writes.**

Log classification is delegated to ``molexp.plugins.metrics_ingest`` so the
survey and the ingest step cannot disagree about what a file is. When molexp
is absent the detector degrades to "no hits" — the survey still describes the
layout, it just cannot promise which logs are convertible.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: How deep the walk descends below the source root.
DEFAULT_MAX_DEPTH = 6

#: Directory names skipped unless the caller overrides ``excludes``.
DEFAULT_EXCLUDES: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        ".tox",
        ".cache",
        "__pycache__",
        ".ipynb_checkpoints",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
    }
)

#: Suffixes that make a file read as the output of a simulation run.
_ARTIFACT_SUFFIXES: frozenset[str] = frozenset(
    {
        ".log",
        ".lammps",
        ".out",
        ".dat",
        ".npy",
        ".npz",
        ".h5",
        ".hdf5",
        ".csv",
        ".xyz",
        ".pdb",
        ".dcd",
        ".xtc",
        ".trr",
        ".lammpstrj",
        ".chk",
        ".pt",
        ".pth",
    }
)

#: Filename stems that mark a run even with an unremarkable suffix.
_ARTIFACT_STEMS: tuple[str, ...] = (
    "params",
    "result",
    "checkpoint",
    "thermo",
    "metrics",
    "log",
    "out",
)

#: TensorBoard event files carry the format in the name, not the suffix.
_TFEVENT_PREFIX = "events.out.tfevents."

RUN = "run"
EXPERIMENT = "experiment"
PROJECT = "project"
LOOSE = "loose"


@dataclass(frozen=True, slots=True)
class FileInfo:
    """One regular file (or symlink) directly inside a surveyed directory."""

    rel: str
    size: int
    is_symlink: bool = False

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.rel, "size": self.size, "symlink": self.is_symlink}


@dataclass(frozen=True, slots=True)
class LogHit:
    """One ingestible log detected inside a run candidate."""

    format: str
    rel: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"format": self.format, "path": self.rel, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class Oddity:
    """Something the operator must decide about before bytes move."""

    kind: str
    path: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "path": self.path, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class DirNode:
    """One directory in the source tree with its heuristic classification."""

    rel: str
    depth: int
    kind: str
    files: tuple[FileInfo, ...] = ()
    subdirs: tuple[str, ...] = ()
    logs: tuple[LogHit, ...] = ()
    has_metrics_buffer: bool = False

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.rel,
            "depth": self.depth,
            "kind": self.kind,
            "file_count": len(self.files),
            "total_bytes": self.total_bytes,
            "subdirs": list(self.subdirs),
            "logs": [hit.to_dict() for hit in self.logs],
            "has_metrics_buffer": self.has_metrics_buffer,
        }


@dataclass(frozen=True, slots=True)
class Survey:
    """The full read-only picture of one source directory."""

    root: str
    nodes: tuple[DirNode, ...] = ()
    oddities: tuple[Oddity, ...] = ()
    excluded: tuple[str, ...] = ()
    truncated: bool = False

    def by_kind(self, kind: str) -> tuple[DirNode, ...]:
        return tuple(node for node in self.nodes if node.kind == kind)

    def node(self, rel: str) -> DirNode | None:
        return next((node for node in self.nodes if node.rel == rel), None)

    def to_dict(self) -> dict[str, Any]:
        runs = self.by_kind(RUN)
        log_counts: dict[str, int] = {}
        for node in runs:
            for hit in node.logs:
                log_counts[hit.format] = log_counts.get(hit.format, 0) + 1
        return {
            "root": self.root,
            "counts": {
                kind: len(self.by_kind(kind))
                for kind in (PROJECT, EXPERIMENT, RUN, LOOSE)
            },
            "total_files": sum(len(node.files) for node in self.nodes),
            "total_bytes": sum(node.total_bytes for node in self.nodes),
            "max_depth_reached": max((n.depth for n in self.nodes), default=0),
            "truncated": self.truncated,
            "logs": {
                "by_format": log_counts,
                "runs_with_buffer": sum(1 for n in runs if n.has_metrics_buffer),
                "runs_without_logs": sum(1 for n in runs if not n.logs),
            },
            "excluded": list(self.excluded),
            "oddities": [odd.to_dict() for odd in self.oddities],
            "nodes": [node.to_dict() for node in self.nodes],
        }


#: A log classifier: run directory → detected hits.
LogDetector = Callable[[Path], Sequence[LogHit]]


def molexp_log_detector(run_dir: Path) -> tuple[LogHit, ...]:
    """Classify logs with molexp's own detector; empty when molexp is absent."""
    try:
        from molexp.plugins.metrics_ingest import detect_log_formats
    except ImportError:
        return ()
    hits: list[LogHit] = []
    for hit in detect_log_formats(run_dir):
        path = Path(hit.path)
        try:
            rel = path.relative_to(run_dir).as_posix()
        except ValueError:
            rel = path.name
        hits.append(LogHit(format=str(hit.format), rel=rel, detail=hit.detail))
    return tuple(hits)


def looks_like_artifact(name: str) -> bool:
    """True when a filename reads as run output rather than source or notes."""
    if name.startswith(_TFEVENT_PREFIX):
        return True
    lowered = name.lower()
    if Path(lowered).suffix in _ARTIFACT_SUFFIXES:
        return True
    return any(lowered.startswith(stem) for stem in _ARTIFACT_STEMS)


def node_path(root: Path, rel: str) -> Path:
    """Absolute path of a surveyed node (``rel == ""`` is the root itself)."""
    return root / rel if rel else root


def survey_source(
    root: Path | str,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    excludes: frozenset[str] = DEFAULT_EXCLUDES,
    detector: LogDetector | None = None,
) -> Survey:
    """Walk *root* and classify it. Read-only; never descends into symlinks.

    Args:
        root: The legacy data directory.
        max_depth: Levels below *root* to descend. Deeper directories are
            reported as ``depth_limit`` oddities rather than silently dropped.
        excludes: Directory names skipped wholesale (recorded in ``excluded``).
        detector: Log classifier. Defaults to molexp's, which yields nothing
            when molexp is not installed.

    Raises:
        NotADirectoryError: *root* is missing or is not a directory.
    """
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise NotADirectoryError(f"not a directory: {base}")
    detect = detector if detector is not None else molexp_log_detector

    oddities: list[Oddity] = []
    excluded: list[str] = []
    children: dict[str, tuple[str, ...]] = {}
    files: dict[str, tuple[FileInfo, ...]] = {}
    depths: dict[str, int] = {}
    truncated = False

    pending: list[tuple[Path, str, int]] = [(base, "", 0)]
    while pending:
        current, rel, depth = pending.pop()
        depths[rel] = depth
        dir_names: list[str] = []
        file_infos: list[FileInfo] = []
        for entry in _list_dir(current, rel, oddities):
            child_rel = f"{rel}/{entry.name}" if rel else entry.name
            if entry.is_symlink():
                # Never dereferenced: a link out of the tree would silently
                # widen the transfer, and a link back into it can cycle.
                _record_symlink(entry, child_rel, base, oddities)
                file_infos.append(FileInfo(rel=child_rel, size=0, is_symlink=True))
                continue
            if entry.is_dir():
                if entry.name in excludes:
                    excluded.append(child_rel)
                    continue
                if depth >= max_depth:
                    truncated = True
                    oddities.append(
                        Oddity("depth_limit", child_rel, f"below max_depth={max_depth}")
                    )
                    continue
                dir_names.append(entry.name)
                pending.append((entry, child_rel, depth + 1))
                continue
            file_infos.append(_file_info(entry, child_rel, oddities))
        children[rel] = tuple(sorted(dir_names))
        files[rel] = tuple(sorted(file_infos, key=lambda f: f.rel))

    kinds = _classify(children, files)
    nodes = tuple(
        DirNode(
            rel=rel,
            depth=depths[rel],
            kind=kinds[rel],
            files=files[rel],
            subdirs=children[rel],
            logs=tuple(detect(node_path(base, rel))) if kinds[rel] == RUN else (),
            has_metrics_buffer=(
                node_path(base, rel) / "metrics" / "metrics.jsonl"
            ).is_file(),
        )
        for rel in sorted(children)
    )
    return Survey(
        root=str(base),
        nodes=nodes,
        oddities=tuple(oddities),
        excluded=tuple(sorted(excluded)),
        truncated=truncated,
    )


def _list_dir(path: Path, rel: str, oddities: list[Oddity]) -> list[Path]:
    try:
        return sorted(path.iterdir())
    except OSError as exc:
        oddities.append(Oddity("unreadable_dir", rel or ".", str(exc)))
        return []


def _file_info(path: Path, rel: str, oddities: list[Oddity]) -> FileInfo:
    try:
        stat = path.stat()
    except OSError as exc:
        oddities.append(Oddity("unreadable_file", rel, str(exc)))
        return FileInfo(rel=rel, size=0)
    if stat.st_size == 0:
        oddities.append(Oddity("empty_file", rel, "zero bytes"))
    return FileInfo(rel=rel, size=stat.st_size)


def _record_symlink(path: Path, rel: str, base: Path, oddities: list[Oddity]) -> None:
    target = path.readlink()
    resolved = (path.parent / target).resolve()
    if not path.exists():
        oddities.append(Oddity("broken_symlink", rel, str(target)))
        return
    if resolved != base and base not in resolved.parents:
        oddities.append(Oddity("escaping_symlink", rel, str(resolved)))


def _classify(
    children: dict[str, tuple[str, ...]],
    files: dict[str, tuple[FileInfo, ...]],
) -> dict[str, str]:
    """Bottom-up ``run → experiment → project`` classification.

    A dir holding run-shaped files is a run; a dir whose every child is a run
    is an experiment; a dir whose every child is an experiment is a project.
    Anything else is loose, and loose files are never silently adopted.
    """
    kinds: dict[str, str] = {}
    for rel in sorted(children, key=_depth_key, reverse=True):
        subdirs = tuple(f"{rel}/{name}" if rel else name for name in children[rel])
        sub_kinds = {kinds[sub] for sub in subdirs}
        has_artifacts = any(looks_like_artifact(f.name) for f in files[rel])
        if subdirs and sub_kinds == {RUN}:
            kinds[rel] = EXPERIMENT
        elif subdirs and sub_kinds == {EXPERIMENT}:
            kinds[rel] = PROJECT
        elif has_artifacts and sub_kinds <= {LOOSE}:
            kinds[rel] = RUN
        else:
            kinds[rel] = LOOSE
    return kinds


def _depth_key(rel: str) -> int:
    return 0 if not rel else rel.count("/") + 1
