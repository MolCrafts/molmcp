"""Explain a single LAMMPS command line by joining parser output + URL."""

from __future__ import annotations

from . import parser, urls

_STYLE_KIND_BY_COMMAND: dict[str, str] = {
    "fix": "fix",
    "compute": "compute",
    "dump": "dump",
}


def _style_position(command: str) -> int:
    """Return the index in args[] where the style name lives for fix/compute/dump.

    fix ID group-ID style ...    → args[2]
    compute ID group-ID style ...→ args[2]
    dump ID group-ID style ...   → args[2]
    """
    return 2 if command in _STYLE_KIND_BY_COMMAND else -1


def _style_kind_for(command: str) -> str | None:
    return _STYLE_KIND_BY_COMMAND.get(command)


def _section_descriptors() -> list[dict[str, str]]:
    return [{"name": n, "purpose": p} for n, p in urls.COMMAND_PAGE_SECTIONS]


def explain(line: str, version: str = urls.DEFAULT_VERSION) -> dict:
    """Tokenise one logical line and resolve to a doc URL via the alias map."""
    urls._validate_version(version)
    parsed = parser.tokenize(line)
    if not parsed["commands"]:
        return {
            "raw": line.strip(),
            "version": version,
            "error": "no command parsed from line",
            "warnings": parsed["warnings"],
        }
    cmd = parsed["commands"][0]
    command = cmd["command"]
    args = list(cmd["args"])
    style_kind = _style_kind_for(command)
    style_name: str | None = None
    keywords: list[str] = []
    keyword_groups: list[dict] = []
    if style_kind is not None:
        pos = _style_position(command)
        if len(args) > pos:
            style_name = args[pos]
            keywords = args[pos + 1 :]

    # url resolution
    url: str | None = None
    shared_with: list[dict[str, str]] = []
    rationale = None
    if style_kind is not None and style_name is not None:
        key = (style_kind, style_name)
        if key in urls.PAGE_SLUGS:
            slug = urls.PAGE_SLUGS[key]
            url = urls.build_url(slug, version)
            shared_with = [
                {"kind": k, "name": n}
                for (k, n) in urls.SHARED_WITH.get(slug, ())
                if (k, n) != key
            ]
            rationale = (
                f"alias-map hit for {style_kind} {style_name}"
                + (
                    f" (shared page covering {len(shared_with)} other variant(s))"
                    if shared_with
                    else ""
                )
            )
    else:
        key = ("command", command)
        if key in urls.PAGE_SLUGS:
            url = urls.build_url(urls.PAGE_SLUGS[key], version)
            rationale = f"alias-map hit for top-level command `{command}`"

    if url is None:
        # fallback: command index
        url = urls.doc_root_url(version) + "Commands.html"
        rationale = (
            "no alias-map entry; falling back to the command index for hand search"
        )

    out: dict[str, object] = {
        "raw": cmd["raw"],
        "version": version,
        "command": command,
        "url": url,
        "url_rationale": rationale,
        "sections_to_read": _section_descriptors(),
        "tokens": {
            "positional": args[: _style_position(command)] if style_kind else args,
            "style": style_name,
            "keywords": keywords,
        },
        "next_action": (
            "Fetch the URL and verify each token against the Syntax section."
        ),
    }
    if style_kind is not None:
        out["style"] = style_name
    if shared_with:
        out["shared_with"] = shared_with
    if keyword_groups:
        out["keyword_groups"] = keyword_groups
    if cmd["comment"]:
        out["comment"] = cmd["comment"]
    return out
