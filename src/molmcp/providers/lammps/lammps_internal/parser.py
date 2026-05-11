"""LAMMPS input-script tokenizer.

Pure function over a string. Handles continuation lines (``&``),
comments (``#`` outside quotes), single-line variable extraction, and
preserves source line numbers. No interpretation of arguments — that
is for the linter / explainer to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Command:
    """One logical LAMMPS command extracted from the script."""

    line: int
    raw: str
    command: str
    args: tuple[str, ...]
    comment: str | None


_QUOTES: Final = ('"', "'")


def _strip_comment(text: str) -> tuple[str, str | None]:
    """Strip a ``#`` comment outside quoted regions. Returns (code, comment)."""
    in_quote: str | None = None
    for i, ch in enumerate(text):
        if in_quote:
            if ch == in_quote:
                in_quote = None
            continue
        if ch in _QUOTES:
            in_quote = ch
            continue
        if ch == "#":
            return text[:i].rstrip(), text[i + 1 :].strip()
    return text.rstrip(), None


def _tokenize(text: str) -> list[str]:
    """Split a code string into tokens, respecting double/single quotes."""
    tokens: list[str] = []
    cur: list[str] = []
    in_quote: str | None = None
    for ch in text:
        if in_quote:
            if ch == in_quote:
                in_quote = None
                continue
            cur.append(ch)
            continue
        if ch in _QUOTES:
            in_quote = ch
            continue
        if ch.isspace():
            if cur:
                tokens.append("".join(cur))
                cur = []
            continue
        cur.append(ch)
    if in_quote:
        # unbalanced quotes; flush whatever was buffered
        tokens.append("".join(cur))
    elif cur:
        tokens.append("".join(cur))
    return tokens


def _join_continuations(content: str) -> list[tuple[int, str]]:
    """Yield (line_number, full_line) after joining ``&`` continuations.

    Line numbers reported are the *first* physical line of each logical
    line, matching how LAMMPS reports parse errors.
    """
    lines = content.splitlines()
    out: list[tuple[int, str]] = []
    buf: list[str] = []
    start_line = 0
    for idx, raw in enumerate(lines, start=1):
        rstripped = raw.rstrip()
        # Detect trailing & (outside comments). Use the comment-stripped
        # form so a "&" inside a comment is not treated as continuation.
        code_only, _ = _strip_comment(rstripped)
        if code_only.endswith("&"):
            if not buf:
                start_line = idx
            buf.append(code_only[:-1])
            continue
        if buf:
            buf.append(rstripped)
            out.append((start_line, " ".join(buf).strip()))
            buf = []
            start_line = 0
        else:
            out.append((idx, rstripped))
    if buf:
        out.append((start_line, " ".join(buf).strip()))
    return out


def tokenize(content: str) -> dict:
    """Tokenise an input script into structured commands.

    Returns a dict with:

    - ``commands``: list of Command-as-dict entries with line numbers.
    - ``variables``: mapping of variable name → string value, populated
      from ``variable NAME equal/string/index VALUE`` declarations.
      Only the declared form is captured; expansion is not performed.
    - ``warnings``: parser-level warnings (unbalanced quotes, etc.).
    """
    commands: list[dict] = []
    variables: dict[str, str] = {}
    warnings: list[str] = []

    for line_no, raw in _join_continuations(content):
        if not raw.strip():
            continue
        code, comment = _strip_comment(raw)
        if not code.strip():
            # comment-only line
            continue
        tokens = _tokenize(code)
        if not tokens:
            continue
        command = tokens[0]
        args = tuple(tokens[1:])
        if '"' in code or "'" in code:
            # detect unbalanced quotes
            double = code.count('"')
            single = code.count("'")
            if double % 2 != 0 or single % 2 != 0:
                warnings.append(
                    f"line {line_no}: unbalanced quote in `{code.strip()}`"
                )
        commands.append(
            {
                "line": line_no,
                "raw": raw.strip(),
                "command": command,
                "args": list(args),
                "comment": comment,
            }
        )
        if command == "variable" and len(args) >= 3:
            variables[args[0]] = " ".join(args[2:])

    return {
        "commands": commands,
        "variables": variables,
        "warnings": warnings,
    }


def to_command_objects(parsed: dict) -> list[Command]:
    """Convert ``tokenize`` output to immutable Command objects."""
    out: list[Command] = []
    for c in parsed["commands"]:
        out.append(
            Command(
                line=c["line"],
                raw=c["raw"],
                command=c["command"],
                args=tuple(c["args"]),
                comment=c["comment"],
            )
        )
    return out
