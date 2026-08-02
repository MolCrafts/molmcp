"""Environment auto-discovery policy for the MolMCP application layer.

A pure *policy* engine, beside :mod:`molmcp.config` in the app layer and
MCP-free, that decides which distributions in a Python environment belong to
the MolCrafts family and what discovery source spec represents each one.

The central guarantee: this module **never imports or executes the target
environment**. Every decision reads distribution metadata (``*.dist-info``
files) and performs pure path operations only; no discovered distribution is
loaded and no interpreter -- not even the target one -- is ever launched, so
pointing at an untrusted environment can never run any of its code.

Public API: :func:`resolve_site_paths` normalizes an environment locator (a
``site-packages`` directory, a virtualenv root, or a Python executable file)
into the ``site-packages`` directories to enumerate; :func:`discover_sources`
enumerates a self or foreign environment into an :class:`EnvironmentReport`.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from .config import ConfigurationError

_FAMILY_ENTRY_POINT_PREFIX = "molmcp."
_FAMILY_KEYWORD = "molcrafts"
_DISCOVER_ENV_VAR = "MOLMCP_DISCOVER"
_FILE_URL_PREFIX = "file://"
_PEP503_RE = re.compile(r"[-_.]+")
_TOKEN_SPLIT_RE = re.compile(r"[,\s]+")
_NAME_DISALLOWED_RE = re.compile(r"[^a-z0-9._-]")
_NAME_LEADING_RE = re.compile(r"^[^a-z]+")

# Distributions that are MolCrafts-family but **not** a public Python API
# surface for agent discovery / codegraph. Their types are reached through
# the higher-level package (e.g. ``molpy.Frame``, never ``import molrs``).
# Explicit ``molcrafts.json`` sources and ``MOLMCP_DISCOVER=+…`` still win.
_NON_PYTHON_API_DISTRIBUTIONS: frozenset[str] = frozenset(
    {
        "molrs",
        "molcrafts-molrs",
        "molcrafts_molrs",
    }
)


@dataclass(frozen=True, slots=True)
class DiscoveredSource:
    """One MolCrafts distribution discovered in an environment.

    Attributes:
        name: Sanitized lowercase source-name candidate (starts with a letter,
            only ``[a-z0-9._-]``), compatible with the config source-naming
            rules; dedup and final validation are deferred to the wiring layer.
        spec: The discovery source spec -- ``pkg:<top_level>`` for the current
            (self) environment or ``local:<package-dir>`` for a foreign one.
        identified_by: The signals that flagged this distribution, from the
            frozen literals ``"entry_point"``/``"keyword"``/``"editable"``/
            ``"override"``.
        distribution: The distribution name exactly as reported by its metadata.
        version: The distribution version string (empty when unavailable).
    """

    name: str
    spec: str
    identified_by: tuple[str, ...]
    distribution: str
    version: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable mapping of this source."""
        return {
            "name": self.name,
            "spec": self.spec,
            "identified_by": list(self.identified_by),
            "distribution": self.distribution,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class EnvironmentReport:
    """The full diagnostic result of one discovery pass.

    Attributes:
        locator: The raw locator string resolved, or ``None`` for self.
        is_self: ``True`` for the current interpreter environment (default
            finders).
        site_paths: The absolute ``site-packages`` directories enumerated;
            empty for a self pass.
        sources: The discovered sources, sorted by ``DiscoveredSource.name``.
        skipped: Diagnostic strings (name + reason) for fail-soft drops.
        excluded: Distribution names force-excluded via ``MOLMCP_DISCOVER``.
    """

    locator: str | None
    is_self: bool
    site_paths: tuple[Path, ...]
    sources: tuple[DiscoveredSource, ...]
    skipped: tuple[str, ...]
    excluded: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable mapping of this report."""
        return {
            "locator": self.locator,
            "is_self": self.is_self,
            "site_paths": [str(path) for path in self.site_paths],
            "sources": [source.to_dict() for source in self.sources],
            "skipped": list(self.skipped),
            "excluded": list(self.excluded),
        }


class _Outcome(NamedTuple):  # internal per-distribution classification result
    kind: str
    source: DiscoveredSource | None = None
    note: str = ""


def resolve_site_paths(locator: str) -> tuple[Path, ...]:
    """Normalize an environment locator into its ``site-packages`` directories.

    Resolution is purely structural (path inspection and globbing): the target
    Python is **never executed** and no distribution is imported.

    Args:
        locator: A filesystem path pointing at a ``site-packages`` directory
            (named ``site-packages`` or containing a ``*.dist-info``), a
            virtualenv root (holding a ``pyvenv.cfg`` or a ``bin``/``Scripts``
            directory), or a Python executable file (env root derived
            structurally as ``<exe>.parent.parent``).

    Returns:
        A tuple of resolved, absolute ``site-packages`` paths.

    Raises:
        ConfigurationError: If the locator does not exist, or no existing
            ``site-packages`` directory can be resolved from it (fail-closed).
    """
    base = Path(locator).expanduser()
    if not base.exists():
        raise ConfigurationError(f"environment locator does not exist: {locator}")
    if base.is_file():
        paths = _venv_site_packages(base.parent.parent)
        if paths:
            return paths
        raise ConfigurationError(
            f"no site-packages found for python executable: {locator}"
        )
    if _is_site_packages(base):
        return (base.resolve(),)
    if _is_venv_root(base):
        paths = _venv_site_packages(base)
        if paths:
            return paths
    raise ConfigurationError(
        f"locator is neither a site-packages nor a virtualenv root: {locator}"
    )


def _is_site_packages(path: Path) -> bool:
    if path.name == "site-packages":
        return True
    return any(path.glob("*.dist-info"))


def _is_venv_root(path: Path) -> bool:
    return (
        (path / "pyvenv.cfg").exists()
        or (path / "bin").is_dir()
        or (path / "Scripts").is_dir()
    )


def _venv_site_packages(root: Path) -> tuple[Path, ...]:
    candidates: list[Path] = [
        match.resolve()
        for match in sorted(root.glob("lib/python*/site-packages"))
        if match.is_dir()
    ]
    windows_libs = root / "Lib" / "site-packages"
    if windows_libs.is_dir():
        candidates.append(windows_libs.resolve())
    return tuple(dict.fromkeys(candidates))  # de-duplicate, preserve order


def discover_sources(locator: str | None = None) -> EnvironmentReport:
    """Discover MolCrafts family distributions in an environment.

    The environment is inspected by reading distribution metadata only; none of
    its code is imported or executed.

    Args:
        locator: ``None`` to enumerate the current interpreter environment via
            the default finders (family packages emit ``pkg:<top_level>``).
            Otherwise a locator string (see :func:`resolve_site_paths`)
            selecting a foreign environment (emits ``local:<package-dir>``).

    Returns:
        An immutable :class:`EnvironmentReport` with sources sorted by name,
        plus fail-soft ``skipped`` and ``excluded`` diagnostics.

    Raises:
        ConfigurationError: Only when ``locator`` itself is invalid; per-dist
            metadata errors are recorded in ``skipped`` and never abort the
            enumeration.
    """
    includes, excludes = _parse_discover(os.environ.get(_DISCOVER_ENV_VAR, ""))
    # Default: hide non-public Python API packages (molrs is the Rust core;
    # agents use molpy.Frame, never import molrs). Explicit
    # ``MOLMCP_DISCOVER=+molrs`` re-enables; ``-name`` still excludes more.
    default_api_excludes = (
        frozenset(_normalize(name) for name in _NON_PYTHON_API_DISTRIBUTIONS) - includes
    )
    excludes = frozenset({*excludes, *default_api_excludes})
    if locator is None:
        dists = importlib.metadata.distributions()
        site_paths: tuple[Path, ...] = ()
        is_self = True
    else:
        site_paths = resolve_site_paths(locator)
        dists = importlib.metadata.distributions(
            path=[str(path) for path in site_paths]
        )
        is_self = False

    sources: list[DiscoveredSource] = []
    skipped: list[str] = []
    excluded: list[str] = []
    for dist in dists:
        dist_name = _safe_name(dist)
        try:
            outcome = _classify(dist, dist_name, is_self, includes, excludes)
        except Exception as exc:  # per-dist fail-soft: enumeration must go on.
            skipped.append(f"{dist_name}: {exc}")
            continue
        if outcome.kind == "source" and outcome.source is not None:
            sources.append(outcome.source)
        elif outcome.kind == "excluded":
            excluded.append(outcome.note)
        elif outcome.kind == "skipped":
            skipped.append(outcome.note)

    sources.sort(key=lambda source: source.name)
    return EnvironmentReport(
        locator=locator,
        is_self=is_self,
        site_paths=site_paths,
        sources=tuple(sources),
        skipped=tuple(skipped),
        excluded=tuple(excluded),
    )


def _classify(
    dist: importlib.metadata.Distribution,
    dist_name: str,
    is_self: bool,
    includes: frozenset[str],
    excludes: frozenset[str],
) -> _Outcome:
    normalized = _normalize(dist_name)
    direct_url = _read_direct_url(dist)
    editable = _is_editable(direct_url)

    signals: list[str] = []
    if _has_entry_point_signal(dist):
        signals.append("entry_point")
    if _has_keyword_signal(dist):
        signals.append("keyword")
    if editable:
        signals.append("editable")

    is_included = normalized in includes
    is_excluded = normalized in excludes
    has_signal = bool(signals)

    if is_excluded and (has_signal or is_included):
        return _Outcome("excluded", note=dist_name)
    if not (has_signal or is_included):
        return _Outcome("none")

    identified_by = tuple(signals)
    if is_included:
        identified_by += ("override",)

    top_level = _top_level(dist, dist_name, editable, direct_url)
    if is_self:
        spec = f"pkg:{top_level}"
    else:
        package_dir = _foreign_package_dir(dist, top_level, editable, direct_url)
        if package_dir is None:
            return _Outcome(
                "skipped",
                note=f"{dist_name}: no importable package directory found",
            )
        spec = f"local:{package_dir}"

    source = DiscoveredSource(
        name=_source_name(dist_name),
        spec=spec,
        identified_by=identified_by,
        distribution=dist_name,
        version=dist.version or "",
    )
    return _Outcome("source", source=source)


def _parse_discover(raw: str) -> tuple[frozenset[str], frozenset[str]]:
    includes: set[str] = set()
    excludes: set[str] = set()
    for token in _TOKEN_SPLIT_RE.split(raw.strip()):
        if token.startswith("+"):
            includes.add(_normalize(token[1:]))
        elif token.startswith("-"):
            excludes.add(_normalize(token[1:]))
    return frozenset(includes), frozenset(excludes)


def _has_entry_point_signal(dist: importlib.metadata.Distribution) -> bool:
    return any(
        entry_point.group.startswith(_FAMILY_ENTRY_POINT_PREFIX)
        for entry_point in dist.entry_points
    )


def _has_keyword_signal(dist: importlib.metadata.Distribution) -> bool:
    raw = dist.metadata.get("Keywords") or ""
    return any(
        token.lower() == _FAMILY_KEYWORD
        for token in _TOKEN_SPLIT_RE.split(raw)
        if token
    )


def _read_direct_url(
    dist: importlib.metadata.Distribution,
) -> dict[str, object] | None:
    raw = dist.read_text("direct_url.json")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _is_editable(direct_url: dict[str, object] | None) -> bool:
    if direct_url is None:
        return False
    dir_info = direct_url.get("dir_info")
    return isinstance(dir_info, dict) and dir_info.get("editable") is True


def _top_level(
    dist: importlib.metadata.Distribution,
    dist_name: str,
    editable: bool,
    direct_url: dict[str, object] | None,
) -> str:
    """Resolve the import top-level package name of a distribution.

    ``top_level.txt`` wins when present. PEP 660 editable wheels usually omit
    it, and the distribution name is then not a reliable guess (a dist named
    ``acme-widget`` may import as ``widget``), so an editable install with a
    resolvable checkout is probed on disk before falling back to the guess.

    Args:
        dist: The distribution whose metadata is read (never imported).
        dist_name: The distribution name as reported by its metadata.
        editable: ``True`` when ``direct_url`` marks a PEP 660 editable install.
        direct_url: The parsed ``direct_url.json`` mapping, or ``None``.

    Returns:
        The top-level package name; ``dist_name`` with ``-`` folded to ``_``
        when neither metadata nor the checkout yields a better answer.
    """
    declared = _declared_top_level(dist)
    if declared is not None:
        return declared
    if editable and direct_url is not None:
        checkout = _url_to_path(direct_url.get("url"))
        if checkout is not None:
            probed = _probe_top_level(checkout, dist_name)
            if probed is not None:
                return probed
    return dist_name.replace("-", "_")


def _declared_top_level(dist: importlib.metadata.Distribution) -> str | None:
    raw = dist.read_text("top_level.txt")
    if not raw:
        return None
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _probe_top_level(checkout: Path, dist_name: str) -> str | None:
    """Derive a top-level package name from an editable checkout on disk.

    ``<checkout>/src`` (src layout) is probed before ``<checkout>`` itself
    (flat layout), so a repo root full of ``tests``/``docs`` packages never
    shadows the real ``src`` package.
    """
    for root in (checkout / "src", checkout):
        selected = _select_top_level(_package_dir_names(root), dist_name)
        if selected is not None:
            return selected
    return None


def _package_dir_names(root: Path) -> tuple[str, ...]:
    """Return the sorted names of ``root`` subdirectories holding ``__init__.py``."""
    try:
        entries = sorted(entry.name for entry in root.iterdir() if entry.is_dir())
    except OSError:  # unreadable / missing checkout: nothing to probe.
        return ()
    return tuple(name for name in entries if (root / name / "__init__.py").is_file())


def _select_top_level(candidates: tuple[str, ...], dist_name: str) -> str | None:
    """Pick the package directory that plausibly *is* the distribution.

    A candidate whose normalized name is contained in the normalized
    distribution name wins (``widget`` in ``acme-widget``); otherwise a lone
    candidate is accepted. Anything ambiguous returns ``None`` so the caller
    keeps its distribution-name fallback.
    """
    normalized_dist = _normalize(dist_name)
    matches = [name for name in candidates if _normalize(name) in normalized_dist]
    if len(matches) == 1:
        return matches[0]
    if matches:
        exact = [name for name in matches if _normalize(name) == normalized_dist]
        return exact[0] if len(exact) == 1 else None
    return candidates[0] if len(candidates) == 1 else None


def _foreign_package_dir(
    dist: importlib.metadata.Distribution,
    top_level: str,
    editable: bool,
    direct_url: dict[str, object] | None,
) -> Path | None:
    if editable and direct_url is not None:
        checkout = _url_to_path(direct_url.get("url"))
        if checkout is None:
            return None
        for candidate in (checkout / top_level, checkout / "src" / top_level):
            if (candidate / "__init__.py").is_file():
                return candidate.resolve()
        return None
    package_dir = Path(dist.locate_file(top_level))
    return package_dir.resolve() if package_dir.is_dir() else None


def _url_to_path(url: object) -> Path | None:
    if not isinstance(url, str) or not url:
        return None
    if url.startswith(_FILE_URL_PREFIX):
        return Path(url[len(_FILE_URL_PREFIX) :])
    if url.startswith("/"):
        return Path(url)
    return None


def _source_name(dist_name: str) -> str:
    cleaned = _NAME_DISALLOWED_RE.sub("", dist_name.lower())
    stripped = _NAME_LEADING_RE.sub("", cleaned)
    if stripped:
        return stripped
    return f"pkg{cleaned}" if cleaned else "pkg"


def _normalize(name: str) -> str:
    return _PEP503_RE.sub("-", name).lower()


def _safe_name(dist: importlib.metadata.Distribution) -> str:
    try:
        name = dist.name
    except Exception:
        name = None
    return str(name) if name else "unknown-distribution"
