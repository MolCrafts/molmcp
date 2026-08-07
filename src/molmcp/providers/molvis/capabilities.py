"""Live-stage introspection for the ``molvis`` provider (MCP-free).

The provider invents no domain API, and this module keeps that promise: it
reports the surface the stage actually has, it does not define one. Every
name, signature and summary here is read off the live object at call time,
so a molvis release that adds a method needs no change in this package.

Why it exists at all, when static discovery already indexes molvis: a
stage is a *runtime* object, and several of the things an agent gets wrong
about it are invisible to an index. Whether a name is a method or a
property (calling ``n_frames()`` when it is a property raises ``'int'
object is not callable``), which arguments are required, and — the one an
index cannot know — whether the loaded build is even the one on disk.
Discovery can also simply be unavailable: a source whose index failed to
build reports nothing at all, and the agent falls back to guessing.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from .refresh import NativeModule, native_modules

#: Module prefixes whose versions and mapped binaries describe the stage's
#: provenance. molvis draws, molpy builds what it draws, molrs is the
#: compiled core under both — a stale binary there changes results without
#: changing a line of visible Python.
PROVENANCE_PREFIXES: tuple[str, ...] = ("molvis", "molpy", "molrs")


@dataclass(frozen=True)
class Capability:
    """One public member of a live stage.

    Attributes:
        name: Attribute name.
        kind: ``"method"``, ``"property"``, or ``"attribute"``.
        signature: Call signature for methods, else ``None``. A property
            has none — reading it is not a call, and treating it as one is
            the single most common way to misuse this surface.
        summary: First line of the docstring, or ``None``.
    """

    name: str
    kind: str
    signature: str | None
    summary: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "signature": self.signature,
            "summary": self.summary,
        }


def _summary(obj: object) -> str | None:
    """First non-empty line of *obj*'s docstring."""
    doc = inspect.getdoc(obj)
    if not doc:
        return None
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _signature(obj: object) -> str | None:
    """Render *obj*'s call signature, or ``None`` when it has none."""
    try:
        return str(inspect.signature(obj))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def describe_stage(stage: object, *, pattern: str | None = None) -> list[Capability]:
    """List the public capabilities of a live *stage*.

    Properties are resolved on the type rather than the instance, so
    reading them never triggers a side effect — a property that dials the
    browser must not fire merely because someone asked what exists.

    Args:
        stage: The live viewer object.
        pattern: Case-insensitive substring filter on the name. Omit for
            everything.

    Returns:
        Capabilities sorted by name. Private names (leading underscore) are
        excluded: they are not the surface being described.
    """
    needle = pattern.lower() if pattern else None
    stage_type = type(stage)
    found: list[Capability] = []

    for name in dir(stage):
        if name.startswith("_"):
            continue
        if needle and needle not in name.lower():
            continue

        # Look the attribute up on the class first. Only that distinguishes
        # a property from its computed value, and only that avoids
        # evaluating it.
        class_attr = inspect.getattr_static(stage_type, name, None)
        if isinstance(class_attr, property):
            found.append(
                Capability(
                    name=name,
                    kind="property",
                    signature=None,
                    summary=_summary(class_attr),
                )
            )
            continue

        try:
            value = getattr(stage, name)
        except Exception:  # noqa: BLE001 — a broken member is still a fact
            found.append(
                Capability(
                    name=name,
                    kind="attribute",
                    signature=None,
                    summary="unreadable on this instance",
                )
            )
            continue

        if callable(value):
            found.append(
                Capability(
                    name=name,
                    kind="method",
                    signature=_signature(value),
                    summary=_summary(value),
                )
            )
        else:
            found.append(
                Capability(
                    name=name,
                    kind="attribute",
                    signature=None,
                    summary=None,
                )
            )

    return sorted(found, key=lambda cap: cap.name)


def _version(distribution: str) -> str | None:
    """Installed version of *distribution*, or ``None`` when absent."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


def provenance() -> dict[str, object]:
    """Describe which build of the molecular stack this process is running.

    Returns:
        Dict with ``versions`` (distribution name → version or ``None``)
        and ``native`` (mapped compiled extensions). Any native entry with
        ``changed_since_start`` means the file was rebuilt after this
        process started: the agent is exercising the older build, and no
        amount of module refreshing will change that.
    """
    mapped: tuple[NativeModule, ...] = native_modules(PROVENANCE_PREFIXES)
    return {
        "versions": {
            name: _version(name)
            for name in ("molcrafts-molvis", "molcrafts-molpy", "molcrafts-molrs")
        },
        "native": [mod.as_dict() for mod in mapped],
        "restart_required": any(mod.changed_since_start for mod in mapped),
    }
