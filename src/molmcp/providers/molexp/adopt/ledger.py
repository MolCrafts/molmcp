"""The resumable migration ledger.

``<target>/.molexp-migration.json`` is the single source of truth for what an
adoption has already done. Every state change is written atomically (temp file
+ ``os.rename``), so a ``Ctrl-C`` or a crash leaves a readable ledger rather
than a truncated one, and re-running skips whatever is already verified.

The ledger is a plain JSON document with no molexp dependency — an operator
auditing a half-finished migration can read it with any tool.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

#: Ledger filename inside the target workspace root.
LEDGER_NAME = ".molexp-migration.json"

#: Bumped when the on-disk ledger shape changes incompatibly.
LEDGER_VERSION = 1

#: Terminal per-entry states — a resume never redoes these.
TERMINAL_STATUSES: frozenset[str] = frozenset({"verified", "moved", "skipped"})

PENDING = "pending"
VERIFIED = "verified"
MOVED = "moved"
SKIPPED = "skipped"
FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Entry:
    """One planned unit of work: a tree node, a file copy, or an ingest."""

    kind: str
    source: str
    target: str
    status: str = PENDING
    size: int = 0
    sha256: str | None = None
    detail: str = ""
    run_id: str = ""

    @property
    def done(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source": self.source,
            "target": self.target,
            "status": self.status,
            "size": self.size,
            "sha256": self.sha256,
            "detail": self.detail,
            "run_id": self.run_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Entry:
        return cls(
            kind=str(payload["kind"]),
            source=str(payload["source"]),
            target=str(payload["target"]),
            status=str(payload.get("status", PENDING)),
            size=int(payload.get("size", 0)),
            sha256=payload.get("sha256"),
            detail=str(payload.get("detail", "")),
            run_id=str(payload.get("run_id", "")),
        )


@dataclass(frozen=True, slots=True)
class Ledger:
    """The whole migration journal. Immutable — updates return a new value."""

    source: str
    target: str
    mode: str
    entries: tuple[Entry, ...] = ()
    version: int = LEDGER_VERSION

    def with_entries(self, entries: tuple[Entry, ...]) -> Ledger:
        return replace(self, entries=entries)

    def replace_entry(self, index: int, entry: Entry) -> Ledger:
        entries = list(self.entries)
        entries[index] = entry
        return self.with_entries(tuple(entries))

    def of_kind(self, kind: str) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.kind == kind)

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.status] = counts.get(entry.status, 0) + 1
        return counts

    @property
    def complete(self) -> bool:
        return all(entry.done for entry in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source": self.source,
            "target": self.target,
            "mode": self.mode,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Ledger:
        return cls(
            source=str(payload["source"]),
            target=str(payload["target"]),
            mode=str(payload["mode"]),
            entries=tuple(Entry.from_dict(e) for e in payload.get("entries", ())),
            version=int(payload.get("version", LEDGER_VERSION)),
        )


class LedgerMismatch(RuntimeError):
    """An existing ledger describes a different migration than the one asked for."""


def ledger_path(target: Path | str) -> Path:
    return Path(target).expanduser().resolve() / LEDGER_NAME


def read_ledger(target: Path | str) -> Ledger | None:
    """Load the ledger at *target*, or ``None`` when there is none."""
    path = ledger_path(target)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise LedgerMismatch(f"{path} does not hold a ledger object")
    return Ledger.from_dict(payload)


def write_ledger(ledger: Ledger) -> Path:
    """Persist *ledger* atomically; returns the ledger path."""
    path = ledger_path(ledger.target)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.partial")
    temp.write_text(
        json.dumps(ledger.to_dict(), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)
    return path


def ensure_compatible(
    existing: Ledger,
    *,
    source: str,
    target: str,
    mode: str,
    version: int = LEDGER_VERSION,
) -> None:
    """Refuse to resume a journal that describes a different migration.

    Raises:
        LedgerMismatch: source, target, mode, or version disagree — resuming
            would silently execute something other than what was approved.
    """
    wanted = {"source": source, "target": target, "mode": mode}
    for name, value in wanted.items():
        if getattr(existing, name) != value:
            raise LedgerMismatch(
                f"existing ledger {name} is {getattr(existing, name)!r}, "
                f"this run asks for {value!r}"
            )
    if existing.version != version:
        raise LedgerMismatch(
            f"ledger version {existing.version} != {version}; "
            "finish or remove the old migration first"
        )


def resume_or_create(ledger: Ledger) -> Ledger:
    """Merge *ledger* with an existing journal, or return it unchanged.

    Raises:
        LedgerMismatch: an existing ledger disagrees about source, target,
            mode, or version.
    """
    existing = read_ledger(ledger.target)
    if existing is None:
        return ledger
    ensure_compatible(
        existing,
        source=ledger.source,
        target=ledger.target,
        mode=ledger.mode,
        version=ledger.version,
    )
    done = {
        (entry.kind, entry.source, entry.target): entry
        for entry in existing.entries
        if entry.done
    }
    merged = tuple(
        done.get((entry.kind, entry.source, entry.target), entry)
        for entry in ledger.entries
    )
    return ledger.with_entries(merged)


def write_error_report(target: Path | str, detail: dict[str, Any]) -> Path:
    """Drop a sibling ``.molexp-migration.ERROR.json`` describing a hard stop."""
    path = ledger_path(target).with_name(f"{LEDGER_NAME[:-5]}.ERROR.json")
    temp = path.with_name(f"{path.name}.partial")
    temp.write_text(json.dumps(detail, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)
    return path
