"""OKF-style browse facade — knowledge pages for context injection.

Codegraph is an index; these functions **open pages** (markdown + structured
data) that agents inject into prompts. Ranking is not the primary product.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from molmcp.guide import build_routing_guide, role_for_source

from .index import DEFAULT_CONTEXT_BUDGET, MAX_CONTEXT_BUDGET, CollectionIndex
from .models import SearchHit

__all__ = [
    "compose_context",
    "open_ref",
    "outline_source",
    "packages_catalog",
    "search_scoped",
]


def packages_catalog(collection: CollectionIndex) -> dict[str, Any]:
    """L0: inject a package directory page for every configured source.

    One query handle per source. This used to take two — ``collection.info()``
    opened one to report state and each card opened another — and every open
    re-walks and re-hashes the source from disk.
    """
    states: dict[str, dict[str, Any]] = {}
    cards: list[dict[str, Any]] = []
    for binding in collection.sources:
        state, card = _state_and_card(binding)
        states[binding.name] = state
        cards.append(card)
    cards.sort(key=lambda c: str(c.get("name")))
    return {
        "ok": True,
        "code": None,
        "error": None,
        "markdown": _packages_markdown(cards),
        "data": {
            "packages": cards,
            "freshness": _states_freshness(states),
            "coverage": {
                "source_count": len(states),
                "available_sources": sum(
                    state["status"] == "ok" for state in states.values()
                ),
            },
        },
    }


def _state_and_card(binding: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Open one source once, and answer both questions from that handle."""
    card: dict[str, Any] = {
        "name": binding.name,
        "status": "ok",
        "spec": binding.spec,
        "freshness": "unknown",
        "summary": None,
        "summary_source": None,
        "module_count": None,
        "role_hint": role_for_source(binding.name),
        "role_hint_source": "name_fragment" if role_for_source(binding.name) else None,
        "warnings": [],
    }
    state: dict[str, Any] = {
        "status": "ok",
        "spec": binding.spec,
        "namespace": binding.namespace,
        "snapshot": None,
        "freshness": "unknown",
    }
    try:
        query = binding.open_query()
    except Exception as exc:  # noqa: BLE001 — source isolation
        state.update(status="error", error=str(exc))
        card.update(status="error", error=str(exc), summary_source="unavailable")
        return state, card
    try:
        snapshot = getattr(query, "snapshot", None)
        state["snapshot"] = str(getattr(snapshot, "snapshot_id", "") or "") or None
        freshness = str(getattr(query, "freshness", "unknown"))
        state["freshness"] = freshness
        card["freshness"] = freshness
        summary = query.package_card()
        card.update(summary)
        if not summary["summary"]:
            card["warnings"].append("package summary missing from index")
    except Exception as exc:  # noqa: BLE001 — source isolation
        state.update(status="error", error=str(exc))
        card.update(status="error", error=str(exc), summary_source="unavailable")
    finally:
        _close_query(query)
    return state, card


def _states_freshness(states: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    per_source = {
        name: str(state.get("freshness", "unknown")) for name, state in states.items()
    }
    values = set(per_source.values())
    if "stale" in values:
        overall = "stale"
    elif "pending" in values:
        overall = "pending"
    elif not values or "unknown" in values:
        overall = "unknown"
    else:
        overall = "fresh"
    return {"overall": overall, "sources": per_source}


def outline_source(
    collection: CollectionIndex,
    source: str,
    *,
    path: str | None = None,
    top_symbols_limit: int = 15,
) -> dict[str, Any]:
    """L1: inject a module directory page for one source."""
    if not source or not str(source).strip():
        return {
            "ok": False,
            "code": "SOURCE_REQUIRED",
            "error": "source is required",
            "hint": "call `packages` first, then outline(source=…)",
            "markdown": "",
            "data": None,
        }
    binding = _binding(collection, source)
    if binding is None:
        return {
            "ok": False,
            "code": "SOURCE_NOT_FOUND",
            "error": f"unknown source {source!r}",
            "hint": "use a name from `packages`",
            "markdown": "",
            "data": None,
        }
    query = binding.open_query()
    try:
        raw = query.outline(path=path)
        modules = []
        for mod in raw.get("modules") or []:
            if not isinstance(mod, dict):
                continue
            symbols = list(mod.get("symbols") or [])
            # Prefer exported-looking public names; cap list for injection size.
            top = symbols[: max(0, top_symbols_limit)]
            modules.append(
                {
                    "qualname": mod.get("qualname"),
                    "kind": mod.get("kind"),
                    "summary": mod.get("summary"),
                    "file": mod.get("file"),
                    "top_symbols": top,
                    "symbol_count": len(symbols),
                }
            )
        data = {
            "source": source,
            "path": path,
            "modules": modules,
            "module_count": len(modules),
            "freshness": str(getattr(query, "freshness", "unknown")),
        }
        return {
            "ok": True,
            "code": None,
            "error": None,
            "markdown": _outline_markdown(source, path, modules),
            "data": data,
        }
    except Exception as exc:  # noqa: BLE001 — source isolation
        return {
            "ok": False,
            "code": "OUTLINE_FAILED",
            "error": str(exc),
            "source": source,
            "markdown": "",
            "data": None,
        }
    finally:
        _close_query(query)


def open_ref(
    collection: CollectionIndex,
    ref: str,
    *,
    include_source: bool = False,
) -> dict[str, Any]:
    """L2: inject one symbol/capability page (usage-first)."""
    detail = collection.describe(
        ref, include_source=include_source, include_examples=True
    )
    if detail is None:
        return {
            "ok": False,
            "code": "SYMBOL_NOT_FOUND",
            "error": "ref_not_found_or_stale",
            "ref": ref,
            "hint": "packages → outline → search(source=…) → open exact ref",
            "markdown": "",
            "data": None,
        }
    examples = detail.get("examples") or []
    tests = detail.get("tests") or []
    if not isinstance(examples, list):
        examples = []
    if not isinstance(tests, list):
        tests = []
    coverage = {
        "examples": len(examples),
        "tests": len(tests),
        "has_signature": bool(detail.get("signature")),
        "has_summary": bool(detail.get("summary") or detail.get("docstring")),
    }
    usage = {
        "ref": ref,
        "qualname": detail.get("qualname") or detail.get("title"),
        "signature": detail.get("signature"),
        "summary": detail.get("summary") or detail.get("docstring"),
        "examples": examples,
        "tests": tests,
        "executable": bool(detail.get("executable")),
        "executable_capability_id": detail.get("executable_capability_id"),
        "relationships": detail.get("relationships") or {},
        "coverage": coverage,
    }
    return {
        "ok": True,
        "code": None,
        "error": None,
        "ref": ref,
        "markdown": _open_markdown(ref, usage, detail),
        "data": {"usage": usage, "detail": detail, "coverage": coverage},
    }


def search_scoped(
    collection: CollectionIndex,
    query: str,
    *,
    kinds: Sequence[str] | None = None,
    namespaces: Sequence[str] | None = None,
    sources: Sequence[str] | None = None,
    path: str | None = None,
    limit: int = 20,
    mode: str = "all",
) -> dict[str, Any]:
    """Index helper: find refs (prefer scoped source= after packages/outline)."""
    try:
        hits = collection.search(
            query,
            kinds=kinds,
            namespaces=namespaces,
            sources=sources,
            limit=min(max(limit, 1), 100),
        )
    except ValueError as exc:
        return {
            "ok": False,
            "code": "SOURCE_NOT_FOUND",
            "error": str(exc),
            "hint": "use a name from `packages`",
            "query": query,
            "sources": list(sources) if sources else None,
            "result_count": 0,
            "results": [],
            "markdown": "",
        }
    if path:
        path_norm = path.strip().strip("/")
        hits = [
            h
            for h in hits
            if path_norm in (h.ref or "")
            or path_norm.replace("/", ".") in (h.title or "")
            or (h.span and path_norm in str(h.span.get("file") or ""))
        ]
    if mode == "executable":
        hits = [h for h in hits if h.executable]
    results = [h.to_dict() for h in hits]
    payload: dict[str, Any] = {
        "ok": True,
        "code": None,
        "error": None,
        "query": query,
        "mode": mode,
        "sources": list(sources) if sources else None,
        "path": path,
        "result_count": len(results),
        "results": results,
        "markdown": _search_markdown(query, results),
        "freshness": _hit_freshness(hits),
    }
    if mode == "executable" and not hits:
        payload["ok"] = False
        payload["code"] = "CAPABILITY_NOT_FOUND"
        payload["error"] = "no_executable_capability_matched"
        payload["hint"] = (
            "no executable capability matched — open packages/outline or "
            "register a capability manifest"
        )
    return payload


def compose_context(
    collection: CollectionIndex,
    *,
    task: str | None = None,
    refs: Sequence[str] | None = None,
    sources: Sequence[str] | None = None,
    budget_chars: int = DEFAULT_CONTEXT_BUDGET,
) -> dict[str, Any]:
    """Bind multiple knowledge pages into a budgeted ContextPack + markdown."""
    budget = min(max(budget_chars, 1), MAX_CONTEXT_BUDGET)
    pages: list[str] = []
    packages = packages_catalog(collection)
    pages.append(str(packages.get("markdown") or ""))

    # The routing guide only needs each source's name and state, which the
    # cards above already carry. Calling collection.info() for it re-opened
    # — and so re-walked and re-hashed — every source a second time.
    data = packages.get("data") if isinstance(packages.get("data"), dict) else {}
    src_map = {
        str(card.get("name")): card
        for card in (data.get("packages") or [])
        if isinstance(card, dict) and card.get("name")
    }
    suggest = build_routing_guide(task or "", sources=src_map)
    pages.append(_suggest_markdown(suggest))

    pack_dict: dict[str, Any] | None = None
    if task and task.strip():
        pack = collection.explore(
            task.strip(),
            sources=sources,
            budget_chars=budget,
        )
        pack_dict = pack.to_dict()
        for detail in pack_dict.get("details") or []:
            if isinstance(detail, dict):
                pages.append(_detail_as_md(detail))

    opened: list[dict[str, Any]] = []
    for ref in refs or ():
        page = open_ref(collection, ref)
        opened.append(page)
        if page.get("markdown"):
            pages.append(str(page["markdown"]))

    markdown = _fit_markdown(pages, budget)
    return {
        "ok": True,
        "code": None,
        "error": None,
        "markdown": markdown,
        "data": {
            "packages": packages.get("data"),
            "suggest": suggest,
            "explore": pack_dict,
            "opened": opened,
            "budget_chars": budget,
            "used_chars": len(markdown),
        },
    }


# ── helpers ────────────────────────────────────────────────────────────────


def _binding(collection: CollectionIndex, source: str) -> Any | None:
    from molmcp.guide import resolve_source_alias

    names = [b.name for b in collection.sources]
    resolved = source if source in names else resolve_source_alias(source, names)
    if resolved is None:
        return None
    for binding in collection.sources:
        if binding.name == resolved:
            return binding
    return None


def _close_query(query: Any) -> None:
    close = getattr(query, "close", None)
    if callable(close):
        close()


def _package_card(
    collection: CollectionIndex, name: str, state: Mapping[str, Any]
) -> dict[str, Any]:
    status = str(state.get("status") or "unknown")
    card: dict[str, Any] = {
        "name": name,
        "status": status,
        "spec": state.get("spec"),
        "freshness": state.get("freshness"),
        "summary": None,
        "summary_source": None,
        "module_count": None,
        "role_hint": role_for_source(name),
        "role_hint_source": "name_fragment" if role_for_source(name) else None,
        "warnings": [],
    }
    if status != "ok":
        card["error"] = state.get("error")
        card["summary_source"] = "unavailable"
        return card
    binding = _binding(collection, name)
    if binding is None:
        card["summary_source"] = "unavailable"
        return card
    query = binding.open_query()
    try:
        outline = query.outline()
        modules = outline.get("modules") or []
        card["module_count"] = len(modules)
        # Prefer root package node summary (shortest qualname matching source).
        summary, source_kind = _pick_package_summary(modules, name)
        card["summary"] = summary
        card["summary_source"] = source_kind
        if not summary:
            card["warnings"].append("package summary missing from index")
    except Exception as exc:  # noqa: BLE001
        card["status"] = "error"
        card["error"] = str(exc)
        card["summary_source"] = "unavailable"
    finally:
        _close_query(query)
    return card


def _pick_package_summary(
    modules: list[Any], source_name: str
) -> tuple[str | None, str | None]:
    if not modules:
        return None, None
    # Prefer kind=package, then shortest qualname.
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for mod in modules:
        if not isinstance(mod, dict):
            continue
        q = str(mod.get("qualname") or "")
        kind = str(mod.get("kind") or "")
        kind_rank = 0 if kind == "package" else 1
        scored.append((kind_rank, len(q), mod))
    scored.sort(key=lambda t: (t[0], t[1]))
    for _, _, mod in scored[:5]:
        summary = mod.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip(), "package_docstring"
    # Fallback: first module with any summary
    for _, _, mod in scored:
        summary = mod.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip(), "module_docstring"
    _ = source_name
    return None, "missing"


def _packages_markdown(cards: list[dict[str, Any]]) -> str:
    lines = [
        "# MolCrafts packages",
        "",
        "Read each summary and choose sources yourself.",
        "This is a directory page, not a ranking.",
        "",
    ]
    for card in cards:
        name = card.get("name")
        status = card.get("status")
        summary = card.get("summary") or "*(no package summary in index)*"
        lines.append(f"## {name}  `{status}`")
        if card.get("role_hint"):
            lines.append(f"- role_hint: `{card['role_hint']}`")
        lines.append(f"- spec: `{card.get('spec')}`")
        lines.append(f"- freshness: `{card.get('freshness')}`")
        if card.get("module_count") is not None:
            lines.append(f"- modules indexed: {card['module_count']}")
        if card.get("error"):
            lines.append(f"- error: {card['error']}")
        lines.append("")
        lines.append(str(summary))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _outline_markdown(
    source: str, path: str | None, modules: list[dict[str, Any]]
) -> str:
    title = f"# Outline: {source}" + (f" / {path}" if path else "")
    lines = [
        title,
        "",
        "Module directory. Read summaries, then `open` exact refs.",
        "",
    ]
    for mod in modules:
        q = mod.get("qualname")
        summary = mod.get("summary") or "*(no module summary)*"
        lines.append(f"## `{q}` ({mod.get('kind')})")
        lines.append(str(summary))
        tops = mod.get("top_symbols") or []
        if tops:
            lines.append("")
            lines.append("Exported symbols (sample):")
            for sym in tops[:15]:
                if not isinstance(sym, dict):
                    continue
                sig = sym.get("signature") or ""
                sm = sym.get("summary") or ""
                lines.append(
                    f"- `{sym.get('qualname')}` "
                    f"({sym.get('kind')}) {sig} {('— ' + sm) if sm else ''}".rstrip()
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _open_markdown(ref: str, usage: dict[str, Any], detail: dict[str, Any]) -> str:
    lines = [
        f"# Open `{ref}`",
        "",
        f"- qualname: `{usage.get('qualname')}`",
        f"- signature: `{usage.get('signature')}`",
        f"- executable: `{usage.get('executable')}`",
        f"- coverage: examples={usage['coverage']['examples']} "
        f"tests={usage['coverage']['tests']}",
        "",
        "## Summary",
        "",
        str(usage.get("summary") or detail.get("docstring") or "*(no summary)*"),
        "",
    ]
    examples = usage.get("examples") or []
    lines.append("## Examples")
    lines.append("")
    if not examples:
        lines.append("*(no example nodes in index — trust signature + summary only)*")
    else:
        for ex in examples[:5]:
            if isinstance(ex, dict):
                lines.append(f"- `{ex.get('qualname')}`: {ex.get('summary') or ''}")
            else:
                lines.append(f"- {ex}")
    lines.append("")
    tests = usage.get("tests") or []
    lines.append("## Tests")
    lines.append("")
    if not tests:
        lines.append("*(no test nodes linked)*")
    else:
        for t in tests[:5]:
            if isinstance(t, dict):
                lines.append(f"- `{t.get('qualname')}`")
            else:
                lines.append(f"- {t}")
    lines.append("")
    return "\n".join(lines)


def _search_markdown(query: str, results: list[dict[str, Any]]) -> str:
    lines = [
        f"# Search `{query}`",
        "",
        "Index helper. Open exact refs with `open` before coding.",
        "",
    ]
    for item in results[:30]:
        lines.append(
            f"- `{item.get('title')}` ({item.get('kind')}) "
            f"source=`{item.get('source')}` exec=`{item.get('executable')}`"
        )
        if item.get("summary"):
            lines.append(f"  {item['summary']}")
        if item.get("ref"):
            lines.append(f"  ref: `{item['ref']}`")
    return "\n".join(lines).rstrip() + "\n"


def _suggest_markdown(suggest: dict[str, Any]) -> str:
    lines = ["# Suggest (optional shortcut)", ""]
    for item in suggest.get("checklist") or []:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- **{item.get('role')}**: {item.get('when')} "
            f"→ prefer {item.get('prefer_packages')} "
            f"(available={item.get('available')})"
        )
    for w in suggest.get("warnings") or []:
        lines.append(f"- warning: {w}")
    lines.append("")
    return "\n".join(lines)


def _detail_as_md(detail: dict[str, Any]) -> str:
    q = detail.get("qualname") or detail.get("title") or detail.get("ref")
    return (
        f"## `{q}`\n\n"
        f"signature: `{detail.get('signature')}`\n\n"
        f"{detail.get('summary') or detail.get('docstring') or ''}\n"
    )


def _fit_markdown(pages: list[str], budget: int) -> str:
    out: list[str] = []
    used = 0
    for page in pages:
        if not page:
            continue
        if used + len(page) + 2 > budget:
            remain = budget - used - 40
            if remain > 80:
                out.append(page[:remain] + "\n\n…*(truncated)*\n")
            break
        out.append(page)
        used += len(page) + 2
    return "\n\n".join(out)


def _hit_freshness(hits: list[SearchHit]) -> dict[str, Any]:
    values = {hit.freshness for hit in hits}
    if "stale" in values:
        overall = "stale"
    elif "pending" in values:
        overall = "pending"
    elif not values or "unknown" in values:
        overall = "unknown"
    else:
        overall = "fresh"
    return {"overall": overall}
