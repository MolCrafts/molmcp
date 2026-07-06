#!/usr/bin/env python
"""Optional lightweight-model relevance judge for capability search.

The deterministic golden-set regression (``tests/discovery/test_golden_ranking``)
locks exact top-k ordering. This script is the *fuzzy* companion: it asks a
lightweight model (Claude Haiku) whether the symbols ``find_capability``
returns are actually relevant to each golden task, and prints a mean score.

Advisory only — it is NOT part of the CI gate. It runs against the same
hermetic fixture the pytest regression uses, so it needs no molpy checkout.

Usage::

    ANTHROPIC_API_KEY=... uv run python scripts/eval_relevance.py

Without ``ANTHROPIC_API_KEY`` set it prints SKIP and exits 0, so it is safe
to wire into any always-on runner without making it a hard dependency.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Reuse the single source of truth for fixture + golden cases.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests" / "discovery"))
from golden_queries import GOLDEN, materialize_fixture  # noqa: E402

_MODEL = "claude-haiku-4-5"
_TOP_K = 5


def _finder(cache_dir: Path, repo: Path):
    from molmcp.discovery import DiscoveryConfig, DiscoveryEngine
    from molmcp.discovery.evidence import EvidenceBuilder

    engine = DiscoveryEngine(DiscoveryConfig(cache_dir=cache_dir))
    return EvidenceBuilder(engine.query(str(repo)))


def _rank_symbols(finder, task: str) -> list[dict]:
    result = finder.find_capability(task, _TOP_K)
    return [
        {
            "rank": m["rank"],
            "qualname": m["node"]["qualname"],
            "signature": m.get("signature"),
            "summary": m.get("summary"),
        }
        for m in result["matches"]
    ]


def _judge(client, task: str, symbols: list[dict]) -> float:
    """Return the model's 0..1 relevance score for the rank-1 symbol."""
    prompt = (
        "You are grading a code-search result. A user asked:\n\n"
        f"    {task}\n\n"
        "The search returned these symbols (rank 1 = top):\n\n"
        f"{json.dumps(symbols, indent=2)}\n\n"
        "Is the RANK 1 symbol a correct, direct answer to the request? "
        "Reply with ONLY a JSON object: "
        '{"score": <0.0-1.0>, "reason": "<short>"}.'
    )
    msg = client.messages.create(
        model=_MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in msg.content if block.type == "text")
    try:
        return float(json.loads(text)["score"])
    except (json.JSONDecodeError, KeyError, ValueError):
        print(f"  ! could not parse judge output: {text!r}")
        return 0.0


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("SKIP: ANTHROPIC_API_KEY not set — relevance judge is optional.")
        return 0
    try:
        import anthropic
    except ImportError:
        print("SKIP: `anthropic` not installed (pip install anthropic).")
        return 0

    client = anthropic.Anthropic()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo = materialize_fixture(root / "repo")
        finder = _finder(root / "cache", repo)

        scores: list[float] = []
        for case in GOLDEN:
            task = case["task"]
            symbols = _rank_symbols(finder, task)
            score = _judge(client, task, symbols)
            scores.append(score)
            top1 = symbols[0]["qualname"] if symbols else "<none>"
            print(f"  {score:.2f}  {task!r} -> rank1 {top1}")

    mean = sum(scores) / len(scores) if scores else 0.0
    print(f"\nmean relevance ({_MODEL}): {mean:.3f} over {len(scores)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
