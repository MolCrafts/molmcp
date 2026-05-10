# Provider design contract

molmcp is **not** a tool-registration mirror of upstream packages. The
primary mechanism for an agent to use a MolCrafts package is
introspection: read the source via `IntrospectionProvider`, then call
the API from a Python snippet or the package's CLI. A Provider that
adds a hand-curated tool catalog has to justify its existence against
this baseline — otherwise we ship maintenance burden (every upstream
API change becomes a molmcp PR) and double-source the truth.

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
capability through `IntrospectionProvider` plus a 3-line Python or CLI
invocation.

## What's currently shipped

Two providers, three tools:

| Provider | Tool | Why it earned a slot |
|---|---|---|
| `MolqProvider` | `molq_list_jobs` | "What's in the queue?" — primary dashboard query. Filters are stable, output is a flat list. |
| `MolexpProvider` | `molexp_list_projects` | Top-level workspace navigation. No inputs. |
| `MolexpProvider` | `molexp_list_runs` | Per-project / per-experiment run query. Stable filter set, flat output. |

Both providers exist **only** because their answers depend on local
runtime state (`~/.molq/jobs.db`, a workspace's catalog) that no amount
of introspection over upstream source can recover.

Things that were deliberately *not* shipped despite living in earlier
revisions:

- `register_cluster`, `refresh_cluster`, `molq_submit`, `molq_cancel`, `molq_cleanup` — write ops; agent should script them after introspecting `molq` or invoke the `molq` CLI directly.
- `molq_status`, `list_ssh_hosts` — derivable from `cat ~/.ssh/config` or reading `molq.ssh_config` via introspection.
- `get_job`, `get_job_transitions`, `get_job_dependencies` — derivable from `molq_list_jobs` + a few lines.
- `list_experiments`, `get_run`, `get_metrics`, `get_asset_text` — derivable from `molexp_list_runs` + reading `molexp.workspace` source.
- The entire `LammpsProvider`, `MolPyProvider`, `MolPackProvider`, `MolRsProvider` packages — each was a hand-curated re-export of an upstream API. Replaced by `--import-root <pkg>` with `IntrospectionProvider`.

## Introspection-first workflow

The CLI defaults `--import-root` to whichever of `{molpy, molpack, molrs, molq, molexp}` are installed in the active Python environment. Without any explicit configuration the agent therefore gets:

- 7 introspection tools (`list_modules`, `list_symbols`, `get_source`, `get_docstring`, `get_signature`, `read_file`, `search_source`) over the installed MolCrafts packages.
- Whichever of the 3 stateful tools above belong to packages that successfully register.

Upstream adds a new function? The agent finds it via
`list_symbols(prefix="molpy.newfeature")` and reads its docstring. molmcp
ships nothing.

Upstream renames a function? The agent's introspection-driven script
fails with a clean Python `AttributeError`, the agent re-introspects,
and continues. molmcp ships nothing.

A user invents a workflow that combines six molq calls into a custom
analysis? The agent writes the analysis. molmcp ships nothing.

That's the design.

## When to add a new provider tool

Walk the four conditions, in order, and write down which one fails for
your candidate tool. If you can't find one that fails — *and* the
answer genuinely needs runtime state introspection cannot see — that's
the bar. Otherwise, push back and document the introspection recipe in
the relevant guide instead.

## Read next

- **[Providers](providers.md)** — the technical Protocol and registration mechanics.
- **[Middleware](middleware.md)** — what wraps every registered tool.
