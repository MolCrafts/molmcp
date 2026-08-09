"""Module-refresh primitives for the ``molvis`` provider (MCP-free).

An agent edits a package on disk and expects the next ``exec`` call to run
the new code. That holds for pure Python: dropping a module from
``sys.modules`` makes the next import re-read the source. It does **not**
hold for a compiled extension (``.so`` / ``.pyd`` / ``.dylib``) — the
dynamic loader maps it once per process and CPython offers no way to swap
it. Only a new server process picks up a rebuild.

Reporting that difference is the whole point of this module. A refresh
that silently leaves a stale extension mapped is worse than no refresh at
all: the agent then exercises the old behaviour and reports it as the new
one, and the operator trusts a verdict about code that never ran.

So :func:`refresh_modules` returns two lists, never one — what it purged,
and what it *cannot* purge and therefore still needs a restart for.
"""

from __future__ import annotations

import importlib
import os
import sys
import time
from dataclasses import dataclass

#: Wall-clock time this module was first imported — a lower bound for when
#: the server process began.
#:
#: Used one-sidedly on purpose. A file whose mtime is later than this
#: definitely changed after start-up, so the mapped copy is suspect and is
#: reported. A file older than this *may* still be current, and is not
#: reported. The direction that would hurt — quietly calling something
#: fresh — is the one this cannot do.
PROCESS_START = time.time()

#: Suffixes of files the dynamic loader maps once per process.
NATIVE_SUFFIXES = (".so", ".pyd", ".dylib")


@dataclass(frozen=True)
class NativeModule:
    """A loaded compiled extension and how its file looks on disk now.

    Attributes:
        module: Fully-qualified module name as it appears in ``sys.modules``.
        path: Absolute path of the mapped binary.
        mtime: File mtime, in seconds since the Unix epoch.
        changed_since_start: The file was modified after this process
            began, so the mapped copy is not the one on disk.
    """

    module: str
    path: str
    mtime: float
    changed_since_start: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "module": self.module,
            "path": self.path,
            "mtime": self.mtime,
            "changed_since_start": self.changed_since_start,
        }


@dataclass(frozen=True)
class RefreshReport:
    """Outcome of one :func:`refresh_modules` call.

    Attributes:
        purged: Modules dropped from ``sys.modules``; the next import of
            each re-reads its source.
        native: Compiled extensions still mapped under the same prefixes.
            Anything with ``changed_since_start`` set needs a server
            restart — this call could not and did not update it.
        refused: Standard-library prefixes this call declined to touch.
        restart_required: True when any ``native`` entry changed on disk.
    """

    purged: tuple[str, ...]
    native: tuple[NativeModule, ...]
    refused: tuple[str, ...] = ()

    @property
    def restart_required(self) -> bool:
        return any(mod.changed_since_start for mod in self.native)

    def as_dict(self) -> dict[str, object]:
        return {
            "purged": list(self.purged),
            "native": [mod.as_dict() for mod in self.native],
            "refused": list(self.refused),
            "restart_required": self.restart_required,
        }


#: Never purged — see :func:`refresh_modules` for why re-importing one of
#: these corrupts the running process rather than refreshing it.
_STDLIB = sys.stdlib_module_names


def _matches(name: str, prefixes: tuple[str, ...]) -> bool:
    """Is *name* one of *prefixes*, or a submodule of one?

    Matching on the dotted boundary keeps ``molrs`` from also selecting an
    unrelated ``molrs_helpers``.
    """
    return any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes)


def native_modules(prefixes: tuple[str, ...]) -> tuple[NativeModule, ...]:
    """Describe every loaded compiled extension under *prefixes*.

    Args:
        prefixes: Top-level module names to look under.

    Returns:
        One entry per mapped binary, sorted by module name. Modules whose
        file has vanished are skipped — there is nothing to say about a
        path that no longer exists.
    """
    found: list[NativeModule] = []
    for name, module in list(sys.modules.items()):
        if not _matches(name, prefixes):
            continue
        path = getattr(module, "__file__", None)
        if not path or not path.endswith(NATIVE_SUFFIXES):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        found.append(
            NativeModule(
                module=name,
                path=path,
                mtime=mtime,
                changed_since_start=mtime > PROCESS_START,
            )
        )
    return tuple(sorted(found, key=lambda mod: mod.module))


def refresh_modules(prefixes: tuple[str, ...]) -> RefreshReport:
    """Drop pure-Python modules under *prefixes* so the next import re-reads them.

    Compiled extensions are deliberately left in place: unmapping one is
    not something CPython supports, and removing it from ``sys.modules``
    would only re-bind the *same* mapped code under a fresh module object
    while making the swap look successful. They are reported instead.

    Live objects are not migrated. A stage, a parsed molecule, anything an
    earlier ``exec`` bound in the namespace, keeps pointing at the classes
    it was built from. Refresh a package whose objects are still in use and
    the session ends up straddling two versions of it — rebuild those
    objects afterwards, or open a new session.

    Standard-library prefixes are refused rather than purged. Dropping one
    does not reload it for anybody: every module that already imported it
    keeps the old module object while a re-import installs a new one, so
    the two stop sharing classes and an ``except json.JSONDecodeError``
    elsewhere in the process quietly stops matching. That is corruption
    wearing a refresh's clothes, and this plane's own error handling is
    among the things it breaks.

    Args:
        prefixes: Top-level module names to refresh, e.g. ``("molpy",)``.

    Returns:
        A :class:`RefreshReport`. ``restart_required`` is the field that
        matters: when it is set, some of the code the agent is about to
        exercise is still the old build. ``refused`` names any stdlib
        prefix that was asked for and skipped.
    """
    refused = tuple(sorted(p for p in prefixes if p.split(".")[0] in _STDLIB))
    prefixes = tuple(p for p in prefixes if p not in refused)
    native = native_modules(prefixes)
    native_names = {mod.module for mod in native}

    purged: tuple[str, ...] = ()
    if prefixes:
        purged = tuple(
            sorted(
                name
                for name in list(sys.modules)
                if _matches(name, prefixes) and name not in native_names
            )
        )
    for name in purged:
        sys.modules.pop(name, None)
    importlib.invalidate_caches()

    # Re-read after purging: a package whose __init__ is pure Python is gone
    # now, but its mapped extension submodule is still there to report.
    return RefreshReport(purged=purged, native=native, refused=refused)
