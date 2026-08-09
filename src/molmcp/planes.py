"""MCP planes — one product domain per MCP server process.

Each plane is an independent MCP server identity. Client configs default to
**all planes enabled**; operators toggle with ``--enable`` / ``--disable``.
There is no mega-server that mounts every provider under one ``molmcp`` name.

Planes
------
catalog
    Bootstrap only. Lists available planes and routes a task string to which
    plane(s) to connect. No science, no discovery index.
molcrafts
    Knowledge plane: packages / outline / open / search / compose / suggest.
    Science APIs are discovered here and invoked elsewhere (e.g. molvis exec).
molvis / molq / molexp / …
    Stateful provider planes from ``molmcp.providers`` entry points. Each
    process hosts exactly one provider's tools, with bare tool names
    (client sees ``molvis__open``, not ``molmcp__molvis_open``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .provider import discover_providers

#: Built-in planes that are not entry-point providers.
BUILTIN_PLANE_IDS = frozenset({"catalog", "molcrafts"})

#: Intent routing table for the catalog ``route`` tool.
#: Patterns are lowercase substrings matched against the task string.
_ROUTE_HINTS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        (
            "draw",
            "viewer",
            "canvas",
            "visualize",
            "smiles",
            "molecule",
            "structure",
            "3d",
            "stage",
            "画",
            "可视化",
            "分子",
            "结构",
            "展示",
            "渲染",
            "多巴胺",
            "阿司匹林",
        ),
        "molvis",
        "Live molecular viewer session (open → exec Python → poll_events).",
    ),
    (
        (
            "job",
            "queue",
            "slurm",
            "submit",
            "sbatch",
            "cluster",
            "scancel",
            "作业",
            "队列",
            "提交",
            "集群",
        ),
        "molq",
        "Job store and cluster submit/cancel (mutations opt-in).",
    ),
    (
        (
            "experiment",
            "workspace",
            "molexp",
            "project",
            "run scaffold",
            "adopt",
            "metrics",
            "实验",
            "工作区",
            "整理数据",
        ),
        "molexp",
        "Experiment workspace layout, scaffold, and legacy-directory adoption.",
    ),
    (
        (
            "api",
            "symbol",
            "docstring",
            "import",
            "how to",
            "search code",
            "package",
            "查",
            "文档",
            "符号",
            "接口",
        ),
        "molcrafts",
        "Discover package/module/symbol pages before writing code.",
    ),
)


@dataclass(frozen=True, slots=True)
class PlaneInfo:
    """Public description of one connectable MCP plane."""

    id: str
    kind: str  # "builtin" | "provider"
    purpose: str
    when_to_connect: str
    serve_command: str
    requires_config: bool
    tools_hint: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "purpose": self.purpose,
            "when_to_connect": self.when_to_connect,
            "serve_command": self.serve_command,
            "requires_config": self.requires_config,
            "tools_hint": list(self.tools_hint),
        }


def _catalog_info() -> PlaneInfo:
    return PlaneInfo(
        id="catalog",
        kind="builtin",
        purpose="List planes and route a task to which MCP connection(s) to open.",
        when_to_connect=(
            "Bootstrap routing; safe to leave enabled with everything else."
        ),
        serve_command="molmcp serve catalog",
        requires_config=False,
        tools_hint=("list_planes", "route"),
    )


def _molcrafts_info() -> PlaneInfo:
    return PlaneInfo(
        id="molcrafts",
        kind="builtin",
        purpose="Inject knowledge pages (packages → outline → open → compose).",
        when_to_connect=(
            "Before writing science code: discover real symbols and examples. "
            "Never invent APIs; miss means SYMBOL_NOT_FOUND."
        ),
        serve_command="molmcp serve molcrafts",
        requires_config=True,
        tools_hint=(
            "info",
            "packages",
            "outline",
            "open",
            "compose",
            "search",
            "suggest",
        ),
    )


_PROVIDER_META: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "molvis": (
        "Live molvis viewer: persistent Python namespace + browser canvas.",
        "User wants to draw, load, select, or interact with a molecule in 3D.",
        (
            "open",
            "exec",
            "poll_events",
            "list_sessions",
            "capabilities",
            "refresh",
            "close",
        ),
    ),
    "molq": (
        "molq job lifecycle: list/get/logs destinations; opt-in submit/cancel.",
        "User wants cluster jobs, queue status, or submission.",
        ("list_jobs", "get_job", "job_logs", "list_destinations", "list_queue"),
    ),
    "molexp": (
        "molexp workspace navigation, idempotent scaffold, and adoption of a "
        "legacy data directory (not a run driver).",
        "User works with experiment workspaces, projects, FAIR layout, or has "
        "a folder of results to lift into one.",
        (
            "list_projects",
            "list_experiments",
            "list_runs",
            "workspace_layout",
            "check_layout",
            "materialize_workspace",
            "add_project",
            "add_experiment",
            "create_run",
            "validate_workflow",
            "plan_adoption",
            "run_adoption",
            "adoption_status",
            "ingest_metrics",
        ),
    ),
}


def list_plane_infos(*, include_unavailable_providers: bool = False) -> list[PlaneInfo]:
    """Return planes this install can serve (catalog first).

    By default only providers whose optional upstream package is installed
    appear (**silent omit** of missing science deps — not a test skip).
    Pass ``include_unavailable_providers=True`` for diagnostics.
    """
    planes: list[PlaneInfo] = [_catalog_info(), _molcrafts_info()]
    available = {p.name: p for p in discover_providers(only_available=True)}
    if include_unavailable_providers:
        loaded = {p.name: p for p in discover_providers(only_available=False)}
        names = sorted(set(loaded) | set(_PROVIDER_META))
        by_name = loaded
    else:
        names = sorted(available)
        by_name = available
    for name in names:
        if name not in by_name and not include_unavailable_providers:
            continue
        purpose, when, tools = _PROVIDER_META.get(
            name,
            (
                f"Provider plane '{name}' (entry point molmcp.providers).",
                f"When work needs the '{name}' product surface.",
                (),
            ),
        )
        planes.append(
            PlaneInfo(
                id=name,
                kind="provider",
                purpose=purpose,
                when_to_connect=when,
                serve_command=f"molmcp serve {name}",
                requires_config=False,
                tools_hint=tools,
            )
        )
    return planes


def known_plane_ids(*, only_available: bool = False) -> frozenset[str]:
    """Ids that ``molmcp serve <id>`` may accept.

    Explicit serve still accepts discovered providers even when
    ``probe()`` is false (user gets a clear install error from
    ``register``). Catalogs use *only_available*.
    """
    provider_names = {p.name for p in discover_providers(only_available=only_available)}
    if only_available:
        return frozenset(BUILTIN_PLANE_IDS | provider_names)
    return frozenset(BUILTIN_PLANE_IDS | provider_names | set(_PROVIDER_META))


def route_task(task: str) -> dict[str, Any]:
    """Map a free-text task to plane ids the client should connect.

    Returns a structured routing answer — never executes science.
    """
    text = task.strip().lower()
    matched: list[dict[str, str]] = []
    seen: set[str] = set()
    for keywords, plane_id, reason in _ROUTE_HINTS:
        if any(k in text for k in keywords) and plane_id not in seen:
            seen.add(plane_id)
            matched.append({"plane": plane_id, "reason": reason})
    # Default: knowledge first when nothing matched hard.
    if not matched:
        matched.append(
            {
                "plane": "molcrafts",
                "reason": "No strong product signal; discover APIs before coding.",
            }
        )
    # Drawing almost always needs molcrafts for API truth + molvis for canvas.
    plane_ids = [m["plane"] for m in matched]
    if "molvis" in plane_ids and "molcrafts" not in plane_ids:
        matched.append(
            {
                "plane": "molcrafts",
                "reason": "Look up molpy/molvis symbols before writing exec code.",
            }
        )
    return {
        "ok": True,
        "task": task,
        "planes": matched,
        "serve_commands": [f"molmcp serve {m['plane']}" for m in matched],
        "client_hint": (
            "Default client installs every plane; use "
            "`molmcp client grok --disable …` to drop ones you do not want. "
            "Science APIs are never MCP tools — discover them on the "
            "molcrafts plane, then call them inside molvis exec (or agent Python)."
        ),
    }


__all__ = [
    "BUILTIN_PLANE_IDS",
    "PlaneInfo",
    "known_plane_ids",
    "list_plane_infos",
    "route_task",
]
