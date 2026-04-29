"""Regenerate ``_generated_slugs.py`` from docs.lammps.org index pages.

Invoked via ``molcrafts-mcp lammps doc update``. The MCP provider
itself never makes network calls — it only encodes pre-fetched
structural facts. This module is the one-shot maintenance tool that
the package maintainer runs when LAMMPS releases a new version with
new commands or styles.

Coverage:

- Top-level commands (``Commands_all.html`` ``general-commands`` section)
- ``fix``, ``compute``, ``pair_style``, ``kspace_style``, ``dump`` styles
- ``bond_style`` / ``angle_style`` / ``dihedral_style`` / ``improper_style``
  (sectioned within ``Commands_bond.html``)
- ``howto_topic`` (``Howto.html``)

Out of scope (handled in ``urls.py``'s ``MANUAL_PAGE_SLUGS``):

- ``atom_style`` and ``region`` — variants share single doc pages and
  are not enumerated in a Sphinx index table.
- The ``kspace_style`` solvers and the dump formats sharing
  ``dump.html``.
"""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

DOC_ROOT = "https://docs.lammps.org/"

VERSION_PREFIX: dict[str, str] = {
    "stable": "stable/",
    "latest": "latest/",
    "release": "",
}


# (kind label, source page basename, optional section anchor id).
# When a section anchor is given, only the slice from that anchor up to
# the next section header is parsed. This is how Commands_bond.html is
# split into bond/angle/dihedral/improper.
INDEX_SOURCES: tuple[tuple[str, str, str | None], ...] = (
    ("command", "Commands_all.html", "general-commands"),
    ("fix", "Commands_fix.html", None),
    ("compute", "Commands_compute.html", None),
    ("pair_style", "Commands_pair.html", None),
    ("kspace_style", "Commands_kspace.html", None),
    ("dump", "Commands_dump.html", None),
    ("bond_style", "Commands_bond.html", "bond"),
    ("angle_style", "Commands_bond.html", "angle"),
    ("dihedral_style", "Commands_bond.html", "dihedral"),
    ("improper_style", "Commands_bond.html", "improper"),
)

HOWTO_INDEX = "Howto.html"


# Match a Sphinx-rendered doc anchor: <a class="reference internal"
# href="slug.html"><span class="doc">name</span></a>. The href must not
# contain a fragment (#section) — those are sub-section pointers.
_ANCHOR_RE = re.compile(
    r'<a class="reference internal" href="([^"#]+)\.html">'
    r'<span class="doc">([^<]+)</span></a>'
)

# Match either <span id="x"></span> or <section id="x">. Both appear in
# LAMMPS docs depending on Sphinx version / page type.
_SECTION_OPEN_RE_TPL = (
    r'<(?:section|span) id="{anchor}"(?:></span>|>)'
)

# Match a section boundary — next anchored heading.
_SECTION_BOUNDARY_RE = re.compile(
    r'<(?:section|span) id="[a-z0-9\-]+"(?:></span><h\d|>\s*<h\d)'
)


# Strip suffix markers like "(k)", "(o)", "(g)", "(i)", "(t)" — these
# denote KOKKOS / OpenMP / GPU / Intel / Threaded acceleration of the
# same style. They're metadata, not distinct names.
_SUFFIX_MARKER_RE = re.compile(r"\s*\([a-z]+\)\s*$")


# Howto.html links use a different markup: a numbered title with no
# <span class="doc"> wrapper. Match the slug only.
_HOWTO_HREF_RE = re.compile(
    r'<a class="reference internal" href="(Howto_[A-Za-z0-9_]+)\.html"'
)


def fetch(url: str) -> str:
    """Fetch a URL with a short timeout."""
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


def slice_section(html: str, anchor: str | None) -> str:
    """Return HTML from ``anchor`` (inclusive) up to the next section boundary."""
    if anchor is None:
        return html
    open_re = re.compile(_SECTION_OPEN_RE_TPL.format(anchor=re.escape(anchor)))
    m = open_re.search(html)
    if not m:
        raise ValueError(f"section anchor {anchor!r} not found in HTML")
    start = m.end()
    rest = html[start:]
    boundary = _SECTION_BOUNDARY_RE.search(rest)
    end = start + boundary.start() if boundary else len(html)
    return html[start:end]


def strip_suffix(name: str) -> str:
    """Strip trailing suffix markers like ``(k)`` and surrounding whitespace."""
    return _SUFFIX_MARKER_RE.sub("", name).strip()


def parse_index(html: str, kind: str) -> list[tuple[str, str]]:
    """Return ``[(name, slug), ...]`` from a Sphinx index table slice."""
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for slug, raw_name in _ANCHOR_RE.findall(html):
        name = strip_suffix(raw_name)
        if not name:
            continue
        if slug.startswith("Commands_") or slug == "Commands":
            continue
        if kind != "command" and (name == kind or slug == kind):
            continue
        key = (name, slug)
        if key in seen:
            continue
        seen.add(key)
        pairs.append((name, slug))
    return pairs


def fetch_all(
    version: str,
) -> tuple[dict[tuple[str, str], str], tuple[str, ...]]:
    """Fetch all index pages and return ``(page_slugs, howto_topics)``."""
    prefix = VERSION_PREFIX[version]
    page_slugs: dict[tuple[str, str], str] = {}
    cache: dict[str, str] = {}

    for kind, page, anchor in INDEX_SOURCES:
        url = f"{DOC_ROOT}{prefix}{page}"
        if page not in cache:
            print(f"  fetching {url}", file=sys.stderr)
            cache[page] = fetch(url)
        sliced = slice_section(cache[page], anchor)
        for name, slug in parse_index(sliced, kind):
            page_slugs[(kind, name)] = slug

    howto_url = f"{DOC_ROOT}{prefix}{HOWTO_INDEX}"
    print(f"  fetching {howto_url}", file=sys.stderr)
    howto_html = fetch(howto_url)
    seen_topics: set[str] = set()
    for slug in _HOWTO_HREF_RE.findall(howto_html):
        topic = slug[len("Howto_"):]
        seen_topics.add(topic)
    return page_slugs, tuple(sorted(seen_topics))


def render_module(
    page_slugs: dict[tuple[str, str], str],
    howto_topics: tuple[str, ...],
    version: str,
) -> str:
    """Render the Python module body to write out."""
    lines: list[str] = []
    lines.append("# ruff: noqa: E501")
    lines.append('"""Auto-generated by ``molcrafts-mcp lammps doc update``.')
    lines.append("")
    lines.append("Do not edit by hand. Re-run the command to regenerate.")
    lines.append(f"Source: docs.lammps.org ({version} branch).")
    lines.append('"""')
    lines.append("")
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append(f"SOURCE_VERSION = {version!r}")
    lines.append("")
    lines.append("EXTRACTED_PAGE_SLUGS: dict[tuple[str, str], str] = {")
    for kind, name in sorted(page_slugs):
        slug = page_slugs[(kind, name)]
        lines.append(f"    ({kind!r}, {name!r}): {slug!r},")
    lines.append("}")
    lines.append("")
    lines.append("EXTRACTED_HOWTO_TOPICS: tuple[str, ...] = (")
    for topic in howto_topics:
        lines.append(f"    {topic!r},")
    lines.append(")")
    return "\n".join(lines) + "\n"


def diff_against_existing(
    existing: dict[tuple[str, str], str],
    new: dict[tuple[str, str], str],
) -> tuple[
    list[tuple[tuple[str, str], str]],
    list[tuple[tuple[str, str], str, str]],
    list[tuple[tuple[str, str], str]],
]:
    """Compute (added, changed, removed) for two slug maps."""
    added = [
        (key, new[key]) for key in sorted(set(new) - set(existing))
    ]
    removed = [
        (key, existing[key]) for key in sorted(set(existing) - set(new))
    ]
    changed = [
        (key, existing[key], new[key])
        for key in sorted(set(existing) & set(new))
        if existing[key] != new[key]
    ]
    return added, changed, removed


def _print_summary(
    added: list[tuple[tuple[str, str], str]],
    changed: list[tuple[tuple[str, str], str, str]],
    removed: list[tuple[tuple[str, str], str]],
    howto_added: list[str],
    howto_removed: list[str],
) -> None:
    print()
    print("Diff vs existing _generated_slugs.py:")
    print(f"  page_slugs:   +{len(added)} ~{len(changed)} -{len(removed)}")
    print(f"  howto_topics: +{len(howto_added)} -{len(howto_removed)}")
    if added:
        print("  added:")
        for (kind, name), slug in added[:20]:
            print(f"    {kind} {name!r} -> {slug}")
        if len(added) > 20:
            print(f"    ... and {len(added) - 20} more")
    if changed:
        print("  changed:")
        for (kind, name), old, newval in changed[:20]:
            print(f"    {kind} {name!r}: {old} -> {newval}")
        if len(changed) > 20:
            print(f"    ... and {len(changed) - 20} more")
    if removed:
        print("  removed:")
        for (kind, name), slug in removed[:20]:
            print(f"    {kind} {name!r} (was -> {slug})")
        if len(removed) > 20:
            print(f"    ... and {len(removed) - 20} more")
    if howto_added:
        print("  howto added: " + ", ".join(howto_added[:20]))
    if howto_removed:
        print("  howto removed: " + ", ".join(howto_removed[:20]))


def _target_path() -> Path:
    """Path to the generated slug map inside the package."""
    return (
        Path(__file__).resolve().parent.parent
        / "lammps_internal"
        / "_generated_slugs.py"
    )


def _load_existing(
    target: Path,
) -> tuple[dict[tuple[str, str], str], tuple[str, ...]]:
    if not target.exists():
        return {}, ()
    namespace: dict[str, object] = {}
    exec(  # noqa: S102
        compile(target.read_text(), str(target), "exec"), namespace
    )
    return (
        namespace.get("EXTRACTED_PAGE_SLUGS", {}),  # type: ignore[return-value]
        namespace.get("EXTRACTED_HOWTO_TOPICS", ()),  # type: ignore[return-value]
    )


def run(check: bool = False, version: str = "stable") -> int:
    """Refresh the slug map.

    Args:
        check: If ``True``, print the diff but do not write the file.
        version: LAMMPS doc branch to scrape.

    Returns:
        Process exit code (``0`` on success).
    """
    if version not in VERSION_PREFIX:
        print(
            f"Unknown LAMMPS version branch {version!r}; "
            f"valid: {sorted(VERSION_PREFIX)}",
            file=sys.stderr,
        )
        return 2
    print(
        f"Fetching from docs.lammps.org ({version} branch)...",
        file=sys.stderr,
    )
    new_slugs, new_howtos = fetch_all(version)
    print(
        f"  parsed: {len(new_slugs)} (kind, name) pairs; "
        f"{len(new_howtos)} howto topics",
        file=sys.stderr,
    )

    target = _target_path()
    existing_slugs, existing_howtos = _load_existing(target)
    added, changed, removed = diff_against_existing(existing_slugs, new_slugs)
    howto_added = sorted(set(new_howtos) - set(existing_howtos))
    howto_removed = sorted(set(existing_howtos) - set(new_howtos))

    _print_summary(added, changed, removed, howto_added, howto_removed)

    if check:
        print()
        print("(--check) not writing file.")
        return 0

    rendered = render_module(new_slugs, new_howtos, version)
    target.write_text(rendered)
    print()
    try:
        rel = target.relative_to(Path.cwd())
    except ValueError:
        rel = target
    print(f"Wrote {rel}")
    return 0
