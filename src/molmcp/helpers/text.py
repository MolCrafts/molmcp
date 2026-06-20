"""Text helpers — wrap untrusted file content to neutralize prompt-injection."""

from __future__ import annotations


def fence_untrusted(content: str, label: str = "untrusted file content") -> str:
    """Wrap ``content`` in a clearly marked block.

    The marker tells the consuming LLM that anything inside is data to
    summarize/quote, not instructions to follow. Use this when a tool
    returns raw file content (e.g. PDB headers, comment lines) that an
    attacker could have written.
    """
    return f"<!-- BEGIN {label} -->\n{content}\n<!-- END {label} -->"
