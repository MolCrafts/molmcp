"""Structural lint rules for LAMMPS input scripts.

All rules are pure functions over the parser's output. The linter does
not validate per-command argument syntax (that requires reading the
docs); for those it emits ``info``-level diagnostics that point the
LLM at the right doc URL via the alias map in :mod:`urls`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from . import parser, urls

MAX_DIAGNOSTICS = 200

_PRE_READ_DATA_REQUIRED = ("units", "atom_style")
_PRE_READ_DATA_RECOMMENDED = ("boundary", "newton", "dimension")
_SCRIPT_INIT_BARRIERS = ("read_data", "read_restart", "create_box")
_PAIR_COEFF_REQUIRES = "pair_style"

_LONG_RANGE_PAIR_SUFFIXES = ("/coul/long", "/coul/msm", "/long")


@dataclass(frozen=True)
class Diagnostic:
    level: str
    line: int
    message: str
    source: str
    command: str | None = None
    doc_url: str | None = None
    suggested_action: str | None = None
    next_action: str | None = None

    def to_dict(self) -> dict:
        out: dict[str, object] = {
            "level": self.level,
            "line": self.line,
            "message": self.message,
            "source": self.source,
        }
        if self.command is not None:
            out["command"] = self.command
        if self.doc_url is not None:
            out["doc_url"] = self.doc_url
        if self.suggested_action is not None:
            out["suggested_action"] = self.suggested_action
        if self.next_action is not None:
            out["next_action"] = self.next_action
        return out


def _doc_url_for_command(name: str, version: str) -> str:
    key = ("command", name)
    if key in urls.PAGE_SLUGS:
        return urls.build_url(urls.PAGE_SLUGS[key], version)
    return urls.doc_root_url(version) + "Commands.html"


def _doc_url_for_style(category: str, name: str, version: str) -> str | None:
    key = (category, name)
    if key in urls.PAGE_SLUGS:
        return urls.build_url(urls.PAGE_SLUGS[key], version)
    return None


def _rule_init_before_read_data(
    commands: list[parser.Command], version: str
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    barrier_idx: int | None = None
    seen_init: dict[str, int] = {}
    for idx, c in enumerate(commands):
        if barrier_idx is None and c.command in _SCRIPT_INIT_BARRIERS:
            barrier_idx = idx
            break
        if c.command in _PRE_READ_DATA_REQUIRED + _PRE_READ_DATA_RECOMMENDED:
            seen_init.setdefault(c.command, idx)
    if barrier_idx is None:
        return diags
    barrier = commands[barrier_idx]
    for required in _PRE_READ_DATA_REQUIRED:
        if required not in seen_init:
            diags.append(
                Diagnostic(
                    level="warning",
                    line=barrier.line,
                    message=(
                        f"`{required}` should be set before "
                        f"`{barrier.command}` (line {barrier.line})."
                    ),
                    source="ordering",
                    command=barrier.command,
                    doc_url=_doc_url_for_command(required, version),
                    suggested_action=(
                        f"Add `{required} ...` near the top of the script."
                    ),
                )
            )
    return diags


def _rule_pair_coeff_after_pair_style(
    commands: list[parser.Command], version: str
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    pair_style_seen = False
    for c in commands:
        if c.command == "pair_style":
            pair_style_seen = True
            continue
        if c.command == "pair_coeff" and not pair_style_seen:
            diags.append(
                Diagnostic(
                    level="error",
                    line=c.line,
                    message=(
                        "`pair_coeff` requires a preceding `pair_style` "
                        "declaration."
                    ),
                    source="ordering",
                    command="pair_coeff",
                    doc_url=_doc_url_for_command(_PAIR_COEFF_REQUIRES, version),
                    suggested_action=(
                        "Insert `pair_style ...` before this `pair_coeff`."
                    ),
                )
            )
    return diags


def _rule_kspace_required_for_long_range(
    commands: list[parser.Command], version: str
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    long_range_lines: list[tuple[int, str]] = []
    kspace_seen = False
    for c in commands:
        if c.command == "kspace_style":
            kspace_seen = True
            continue
        if c.command == "pair_style" and c.args:
            style_name = c.args[0]
            for suffix in _LONG_RANGE_PAIR_SUFFIXES:
                if style_name.endswith(suffix):
                    long_range_lines.append((c.line, style_name))
                    break
    if long_range_lines and not kspace_seen:
        for line, style_name in long_range_lines:
            diags.append(
                Diagnostic(
                    level="error",
                    line=line,
                    message=(
                        f"`pair_style {style_name}` requires a "
                        "`kspace_style` declaration."
                    ),
                    source="ordering",
                    command="pair_style",
                    doc_url=_doc_url_for_command("kspace_style", version),
                    suggested_action=(
                        "Add `kspace_style pppm 1.0e-4` (or another kspace "
                        "style) after pair_coeff."
                    ),
                )
            )
    return diags


def _track_ids_per_kind(
    commands: list[parser.Command],
) -> tuple[
    dict[str, set[str]], list[tuple[parser.Command, str, str]]
]:
    """Return (defined_per_kind, references) for fix/compute/dump.

    references: list of (Command, kind, id) for every reference command
    (unfix, uncompute, undump, fix_modify, compute_modify, dump_modify).
    """
    defined: dict[str, set[str]] = {"fix": set(), "compute": set(), "dump": set()}
    refs: list[tuple[parser.Command, str, str]] = []
    define_cmds = {"fix", "compute", "dump"}
    ref_cmds = {
        "unfix": "fix",
        "fix_modify": "fix",
        "uncompute": "compute",
        "compute_modify": "compute",
        "undump": "dump",
        "dump_modify": "dump",
    }
    for c in commands:
        if c.command in define_cmds and c.args:
            defined[c.command].add(c.args[0])
            continue
        if c.command in ref_cmds and c.args:
            kind = ref_cmds[c.command]
            target = c.args[0]
            refs.append((c, kind, target))
    return defined, refs


def _rule_reference_integrity(
    commands: list[parser.Command], version: str
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    defined, refs = _track_ids_per_kind(commands)
    # rebuild defined set incrementally so we only flag forward-references
    seen: dict[str, set[str]] = {"fix": set(), "compute": set(), "dump": set()}
    define_cmds = {"fix", "compute", "dump"}
    ref_cmds = {
        "unfix": "fix",
        "fix_modify": "fix",
        "uncompute": "compute",
        "compute_modify": "compute",
        "undump": "dump",
        "dump_modify": "dump",
    }
    for c in commands:
        if c.command in define_cmds and c.args:
            seen[c.command].add(c.args[0])
            continue
        if c.command in ref_cmds and c.args:
            kind = ref_cmds[c.command]
            target = c.args[0]
            if target not in seen[kind] and target not in defined[kind]:
                diags.append(
                    Diagnostic(
                        level="error",
                        line=c.line,
                        message=(
                            f"`{c.command} {target}` references {kind} ID "
                            f"`{target}` which has not been defined "
                            "earlier in the script."
                        ),
                        source="reference",
                        command=c.command,
                        doc_url=_doc_url_for_command(c.command, version),
                        suggested_action=(
                            f"Verify the {kind} ID, or add a `{kind} "
                            f"{target} ...` definition before this line."
                        ),
                    )
                )
    return diags


def _rule_fix_id_uniqueness(
    commands: list[parser.Command], version: str
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    active: dict[str, int] = {}
    for c in commands:
        if c.command == "fix" and c.args:
            fid = c.args[0]
            if fid in active:
                diags.append(
                    Diagnostic(
                        level="error",
                        line=c.line,
                        message=(
                            f"fix ID `{fid}` was defined at line "
                            f"{active[fid]}; unfix it before redefining "
                            f"at line {c.line}."
                        ),
                        source="ordering",
                        command="fix",
                        doc_url=_doc_url_for_command("fix", version),
                        suggested_action=(
                            f"Insert `unfix {fid}` before line {c.line}."
                        ),
                    )
                )
            active[fid] = c.line
            continue
        if c.command == "unfix" and c.args:
            active.pop(c.args[0], None)
    return diags


def _rule_variable_resolution(
    commands: list[parser.Command],
    variables: dict[str, str],
    version: str,
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    declared: set[str] = set()
    for c in commands:
        if c.command == "variable" and c.args:
            declared.add(c.args[0])
            continue
        for token in c.args:
            for ref in _extract_var_refs(token):
                if ref not in declared and ref not in variables:
                    diags.append(
                        Diagnostic(
                            level="warning",
                            line=c.line,
                            message=(
                                f"variable `${{{ref}}}` referenced before "
                                "definition (or built-in not recognised)."
                            ),
                            source="reference",
                            command=c.command,
                            doc_url=_doc_url_for_command("variable", version),
                            suggested_action=(
                                f"Declare `variable {ref} equal ...` earlier "
                                "in the script."
                            ),
                        )
                    )
    return diags


def _extract_var_refs(token: str) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(token):
        if token[i] == "$" and i + 1 < len(token):
            nxt = token[i + 1]
            if nxt == "{":
                end = token.find("}", i + 2)
                if end != -1:
                    out.append(token[i + 2 : end])
                    i = end + 1
                    continue
            elif nxt.isalpha():
                # single-char form $X
                out.append(token[i + 1 : i + 2])
                i += 2
                continue
        i += 1
    return out


def _rule_content_check_pointers(
    commands: list[parser.Command], version: str
) -> list[Diagnostic]:
    """Emit info diagnostics pointing at the right doc URL for each style line."""
    diags: list[Diagnostic] = []
    style_categories = {
        "pair_style": "pair_style",
        "bond_style": "bond_style",
        "angle_style": "angle_style",
        "dihedral_style": "dihedral_style",
        "improper_style": "improper_style",
        "atom_style": "atom_style",
        "kspace_style": "kspace_style",
    }
    seen_lines: set[int] = set()
    for c in commands:
        if c.command in style_categories and c.args:
            style_name = c.args[0]
            cat = style_categories[c.command]
            url = _doc_url_for_style(cat, style_name, version)
            if url is None:
                # unknown style: point at the category index
                index_slug = urls.CATEGORY_INDEXES.get(cat, "Commands")
                url = (
                    urls.doc_root_url(version)
                    + (index_slug if "#" in index_slug else f"{index_slug}.html")
                )
                level = "warning"
                msg = (
                    f"Style `{c.command} {style_name}` not in alias map "
                    "(may be a recent addition or a typo)."
                )
            else:
                level = "info"
                msg = (
                    f"Verify `{c.command} {style_name}` argument syntax "
                    "against the docs."
                )
            if c.line in seen_lines:
                continue
            seen_lines.add(c.line)
            diags.append(
                Diagnostic(
                    level=level,
                    line=c.line,
                    message=msg,
                    source="content_check_required",
                    command=c.command,
                    doc_url=url,
                    next_action=(
                        f"Fetch the URL and verify the arguments at line "
                        f"{c.line} match the Syntax section."
                    ),
                )
            )
        elif c.command in {"fix", "compute", "dump"} and len(c.args) >= 2:
            # fix ID group-ID style ...   (style is c.args[2] for fix)
            # compute ID group-ID style ...
            # dump ID group-ID style ...
            if len(c.args) >= 3:
                style_name = c.args[2]
                cat = c.command
                url = _doc_url_for_style(cat, style_name, version)
                if url is None:
                    continue  # unknown styles surface elsewhere
                if c.line in seen_lines:
                    continue
                seen_lines.add(c.line)
                diags.append(
                    Diagnostic(
                        level="info",
                        line=c.line,
                        message=(
                            f"Verify `{c.command} {style_name}` argument "
                            "syntax against the docs."
                        ),
                        source="content_check_required",
                        command=c.command,
                        doc_url=url,
                        next_action=(
                            f"Fetch the URL and verify the arguments at "
                            f"line {c.line} match the Syntax section."
                        ),
                    )
                )
    return diags


_RULES = (
    _rule_init_before_read_data,
    _rule_pair_coeff_after_pair_style,
    _rule_kspace_required_for_long_range,
    _rule_reference_integrity,
    _rule_fix_id_uniqueness,
    _rule_content_check_pointers,
)


def _summarise(diags: Iterable[Diagnostic]) -> dict[str, int]:
    counts = {"errors": 0, "warnings": 0, "infos": 0}
    for d in diags:
        if d.level == "error":
            counts["errors"] += 1
        elif d.level == "warning":
            counts["warnings"] += 1
        elif d.level == "info":
            counts["infos"] += 1
    return counts


def lint(content: str, version: str = urls.DEFAULT_VERSION) -> dict:
    """Run all structural rules and return a single result envelope."""
    urls._validate_version(version)
    parsed = parser.tokenize(content)
    cmd_objs = parser.to_command_objects(parsed)
    diagnostics: list[Diagnostic] = []
    for rule in _RULES:
        diagnostics.extend(rule(cmd_objs, version))
    diagnostics.extend(
        _rule_variable_resolution(cmd_objs, parsed["variables"], version)
    )
    diagnostics.sort(
        key=lambda d: (d.line, {"error": 0, "warning": 1, "info": 2}.get(d.level, 3))
    )
    truncated = False
    if len(diagnostics) > MAX_DIAGNOSTICS:
        diagnostics = diagnostics[:MAX_DIAGNOSTICS]
        truncated = True
    out: dict[str, object] = {
        "version": version,
        "diagnostics": [d.to_dict() for d in diagnostics],
        "summary": _summarise(diagnostics),
    }
    if parsed["warnings"]:
        out["parser_warnings"] = parsed["warnings"]
    if truncated:
        out["truncated"] = True
        out["truncation_limit"] = MAX_DIAGNOSTICS
    return out
