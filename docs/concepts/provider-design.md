# Provider design contract

molmcp is **not** a tool-registration mirror of upstream packages. The
primary mechanism for an agent to use a MolCrafts package is the
[discovery engine](discovery.md): query the indexed code graph for
symbols, relationships, and examples, then call the API from a Python
snippet or the package's CLI. A Provider that adds a hand-curated tool
catalog has to justify its existence against this baseline — otherwise
we ship maintenance burden (every upstream API change becomes a molmcp
PR) and double-source the truth.

## When does a tool earn a slot?

A tool may be registered by a Provider only if **all four** conditions
hold:

1. **Stable signature.** Inputs are 0–2 primitive parameters that won't
   drift when upstream evolves. If you find yourself adding optional
   keyword args every release to keep up with upstream, the tool is
   wrong.
2. **Read-only or idempotent.** Anything that mutates user state
   (`register_cluster`, `refresh_cluster`, file writes) belongs in the
   upstream API and should be invoked by the agent through Python or
   the CLI — not exposed as an MCP tool. Mutations carry blast radius
   that a tool's surface can't communicate.
3. **Every-session frequency.** "What's running?" / "What projects
   exist?" / "Is the cluster reachable?" are dashboard-class queries
   the agent will want to call within seconds of starting work. A tool
   that's used once per quarter is dead weight.
4. **Single-shot answer.** The result is one value or one short list.
   If the agent needs to *join, filter, or compose* multiple calls to
   answer the user's question, it should write the script itself —
   that's exactly the use case introspection unlocks.

If any condition fails: **don't** add the tool. The agent gets the
capability through the discovery engine plus a 3-line Python or CLI
invocation.

## What's currently shipped

Five providers. Their tools fall into three categories, each clearing the
four conditions for a different reason.

**Stateful runtime queries** — the answer depends on local state that no
amount of introspection over upstream *source* can recover:

| Provider | Tool | Why it earned a slot |
|---|---|---|
| `MolqProvider` | `molq_list_jobs` | "What's in the queue?" — primary dashboard query. Filters are stable, output is a flat list. |
| `MolexpProvider` | `molexp_list_projects` | Top-level workspace navigation. No inputs. |
| `MolexpProvider` | `molexp_list_runs` | Per-project / per-experiment run query. Stable filter set, flat output. |

These exist **only** because their answers depend on local runtime state
(`~/.molq/jobs.db`, a workspace's catalog) that no amount of
introspection over upstream source can recover.

**Contract + linter:**

| Provider | Tool | Why it earned a slot |
|---|---|---|
| `MolexpProvider` | `molexp_workspace_layout` | The workspace on-disk *contract* (tree + naming law). No inputs, frozen output. |
| `MolexpProvider` | `molexp_check_layout` | Read-only lint of a directory against that contract. One path arg, single-shot verdict. |

The last two are a different category — a layout **contract + linter**,
the read-only counterpart to the `mol:adopt-workspace` skill. They are
not stateful dashboard queries, so condition 3 ("every-session
frequency") is read against the *task*, not the session: whenever an
agent organizes or onboards data into a FAIR workspace it needs the
layout spec first and lints as it goes. The contract is sourced from a
*frozen* molexp invariant (a drift test pins the mirror to the live
classes), so condition 1 holds despite the spec living partly in
upstream; and both tools are strictly read-only (condition 2) — the
actual, integrity-checked migration runs through the skill or molexp's
Python API, never an MCP write tool. This is the same reference/lint
category as the doc tools, not the runtime-query category the
four-condition gate was written for.

**Capability catalogs the code graph can't index** — capabilities that
live in a native extension or an external tool, walked from the *live*
module (or a hand-mirrored table) at call-time rather than hardcoded, or
a small execution shim for an *action* discovery can't perform:

| Provider | Tool | Why it earned a slot |
|---|---|---|
| `MolpyProvider` | `list_compute_ops`, `list_readers` | Walk `molpy.compute` / `molpy.io` at call-time for concrete subclasses — no static list to drift as upstream evolves. |
| `MolpyProvider` | `inspect_structure` | Executes a `molpy.io` reader on a path — an *action*, not a source lookup. |
| `MolpackProvider` | `list_restraints` | Walks the live `molpack` module for `*Restraint` classes; the native pyo3 classes don't surface to the code graph. |
| `MolpackProvider` | `list_formats` | Mirrors the format table in molpack's Rust `io.rs` — knowledge with no Python-side registry to index. |
| `MolpackProvider` | `inspect_script` | Parses a Packmol `.inp` via `molpack.load_script` — again an action, not a lookup. |
| `LammpsProvider` | 13 doc-navigation tools (`get_command_doc`, `get_style_doc`, `plan_task`, `validate_script`, `explain_error`, …) | LAMMPS is a C++ binary with a DSL — there is no Python source for the code graph to index. The navigator stays pure-function over in-memory tables (no `lmp`, no network, no filesystem), so it always registers. |

These are read-only (condition 2), single-shot (condition 4), and
answer questions static indexing structurally cannot — so they clear the
gate even though they are not runtime-state queries. What they are *not*
is a hand-curated mirror of a plain-Python upstream namespace: every
catalog is derived from the live module or a pinned source table, never a
retyped copy that drifts.

Things that were deliberately *not* shipped despite living in earlier
revisions:

- `register_cluster`, `refresh_cluster`, `molq_submit`, `molq_cancel`, `molq_cleanup` — write ops; agent should script them after introspecting `molq` or invoke the `molq` CLI directly.
- `molq_status`, `list_ssh_hosts` — derivable from `cat ~/.ssh/config` or reading `molq.ssh_config` via introspection.
- `get_job`, `get_job_transitions`, `get_job_dependencies` — derivable from `molq_list_jobs` + a few lines.
- `list_experiments`, `get_run`, `get_metrics`, `get_asset_text` — derivable from `molexp_list_runs` + reading `molexp.workspace` source.
- A blanket re-export of a plain-Python upstream namespace — a `compute_rdf` / `parse_smiles` / structure-I/O facade that retypes upstream signatures. That stays in the discovery engine plus a 3-line invocation. (`LammpsProvider`, `MolpyProvider`, and `MolpackProvider` returned in a later revision, but only as the call-time catalogs / execution shims listed above — not as static mirrors.)
- `MolrsProvider` — it exists in the source tree but is deliberately left out of the `molmcp.providers` entry points: molrs's Python API is fully importable, so the discovery engine indexes it directly.

## Discovery-first workflow

The CLI defaults discovery to the MolCrafts packages `{molpy, molpack, molrs, molq, molexp, molnex}` — each from a local install when present, from GitHub otherwise. Without any explicit configuration the agent therefore gets:

- 6 discovery tools (`molmcp_find_capability`, `molmcp_search_symbols`, `molmcp_describe_symbol`, `molmcp_relations`, `molmcp_outline`, `molmcp_refresh`) over the indexed code graph of the installed MolCrafts packages.
- The in-tree provider tools for whichever of those packages register — molq's job query, molexp's workspace + layout tools, and molpy's / molpack's call-time catalogs — plus the dependency-free LAMMPS doc navigator.

Upstream adds a new function? The agent finds it via
`molmcp_search_symbols` or `molmcp_find_capability` and reads its
signature and examples. molmcp ships nothing.

Upstream renames a function? The next index produces a new snapshot,
the agent re-discovers the symbol under its new name, and continues.
molmcp ships nothing.

A user invents a workflow that combines six molq calls into a custom
analysis? The agent writes the analysis. molmcp ships nothing.

That's the design.

## When to add a new provider tool

Walk the four conditions, in order, and write down which one fails for
your candidate tool. If you can't find one that fails — *and* the
answer genuinely needs runtime state the discovery engine cannot see —
that's the bar. Otherwise, push back and document the discovery recipe
in the relevant guide instead.

## Read next

- **[Providers](providers.md)** — the technical Protocol and registration mechanics.
- **[Middleware](middleware.md)** — what wraps every registered tool.
