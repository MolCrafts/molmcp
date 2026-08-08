"""Per-file transfer with mandatory SHA-256 verification.

Every payload byte moves the same way: stream-hash while writing a ``.partial``
sibling, ``os.replace`` it into place, re-read the destination and compare
hashes. There is deliberately no ``skip_verify`` switch — an adoption that
cannot prove the copy is not an adoption.

``move`` is *copy → verify → unlink source*, never ``os.rename``: a crash
mid-run then leaves the source partially intact and the ledger says exactly
which files were already unlinked.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

#: Bytes read per hashing chunk. Flat memory on multi-GB trajectories.
_CHUNK = 1024 * 1024

COPY = "copy"
MOVE = "move"
MODES: frozenset[str] = frozenset({COPY, MOVE})


class TransferError(RuntimeError):
    """A copy could not be proven correct; the operator must intervene."""


class HashMismatch(TransferError):
    """Source and destination hashes disagree after a write."""

    def __init__(self, source: Path, target: Path, expected: str, actual: str) -> None:
        super().__init__(
            f"SHA-256 mismatch copying {source} → {target}: "
            f"expected {expected}, read {actual}"
        )
        self.source = source
        self.target = target
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True, slots=True)
class TransferResult:
    """What one file transfer did."""

    source: Path
    target: Path
    sha256: str
    size: int
    moved: bool = False
    reused: bool = False


def sha256_file(path: Path) -> str:
    """Streaming SHA-256 of a file's contents."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def transfer_file(
    source: Path,
    target: Path,
    *,
    mode: str = COPY,
) -> TransferResult:
    """Copy (or move) one file and prove the bytes survived.

    A symlink is recreated as a symlink — never dereferenced, so a link out of
    the source tree cannot silently pull foreign bytes into the workspace.

    An existing destination is reused when its hash already matches (an
    interrupted run resuming) and refused otherwise — this never overwrites.

    Raises:
        HashMismatch: the destination does not match the source.
        TransferError: a different file already occupies the destination.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {sorted(MODES)}, got {mode!r}")
    target.parent.mkdir(parents=True, exist_ok=True)

    if source.is_symlink():
        return _transfer_symlink(source, target, mode=mode)

    expected = sha256_file(source)
    size = source.stat().st_size

    if target.exists():
        actual = sha256_file(target)
        if actual != expected:
            raise TransferError(
                f"refusing to overwrite {target}: it holds different bytes "
                f"({actual} != {expected}). Move it aside and re-run."
            )
        if mode == MOVE:
            source.unlink()
        return TransferResult(source, target, expected, size, mode == MOVE, True)

    partial = target.with_name(f"{target.name}.partial")
    digest = hashlib.sha256()
    try:
        with source.open("rb") as src, partial.open("wb") as dst:
            while chunk := src.read(_CHUNK):
                digest.update(chunk)
                dst.write(chunk)
        os.replace(partial, target)
    except OSError:
        partial.unlink(missing_ok=True)
        raise

    written = digest.hexdigest()
    actual = sha256_file(target)
    if actual != written:
        raise HashMismatch(source, target, written, actual)

    shutil.copystat(source, target, follow_symlinks=False)
    if mode == MOVE:
        source.unlink()
    return TransferResult(source, target, actual, size, mode == MOVE, False)


def _transfer_symlink(source: Path, target: Path, *, mode: str) -> TransferResult:
    link = source.readlink()
    if target.is_symlink():
        if target.readlink() != link:
            raise TransferError(
                f"refusing to replace symlink {target} → {target.readlink()} "
                f"with a link to {link}"
            )
    elif target.exists():
        raise TransferError(f"refusing to replace {target} with a symlink")
    else:
        target.symlink_to(link)
    if mode == MOVE:
        source.unlink()
    return TransferResult(source, target, "", 0, mode == MOVE, False)


def verify_present(pairs: list[tuple[Path, int]]) -> list[str]:
    """Cheap post-transfer check: every destination exists at its known size.

    Each file was already hashed on write and re-read before its ledger entry
    flipped to verified, so this pass exists to catch what happened *after*
    that — a truncation, a deletion, a half-materialized run directory. Use
    :func:`verify_tree` for a full re-hash audit.
    """
    problems: list[str] = []
    for path, size in pairs:
        if path.is_symlink():
            continue
        if not path.is_file():
            problems.append(f"missing after transfer: {path}")
            continue
        actual = path.stat().st_size
        if size and actual != size:
            problems.append(f"size drift at {path}: {actual} != {size}")
    return problems


def verify_tree(pairs: list[tuple[Path, str]]) -> list[str]:
    """Re-hash transferred files; return one message per divergence.

    Args:
        pairs: ``(path, expected_sha256)``. Entries with an empty hash
            (symlinks) are checked for existence only.
    """
    problems: list[str] = []
    for path, expected in pairs:
        if not expected:
            if not path.is_symlink() and not path.exists():
                problems.append(f"missing after transfer: {path}")
            continue
        if not path.is_file():
            problems.append(f"missing after transfer: {path}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            problems.append(f"hash drift at {path}: {actual} != {expected}")
    return problems
