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

1. **Stable signature.** Inputs are a small frozen set of primitives that
   won't drift when upstream evolves. No open-ended kwargs bag that tracks
   the full upstream API.
2. **Read-only or idempotent** (default). Mutations carry blast radius that
   a tool surface can't fully communicate; prefer upstream API/CLI unless
   the tool qualifies as a [controlled mutation](#controlled-mutations).
3. **Every-session (or every-task) frequency.** Dashboard and layout tools
   the agent needs at the start of work — not one-off quarterly helpers.
4. **Single-shot answer.** One value or one short list. Composition and
   joins belong in agent-written scripts.

If any condition fails: **don't** add the tool. Use discovery + a short
Python or CLI invocation.

### Controlled mutations

A **narrow** non-idempotent write tool may ship **only** for in-tree
first-party providers (`src/molmcp/providers/<name>/`), and only when
**all** of the following hold:

1. **Explicit opt-in** — env and/or config gate; default off
   (e.g. `MOLMCP_MOLQ_SUBMIT=1` and config `allow_submit`).
2. **Frozen flat signature** — CLI-shaped primitives, not the full
   upstream object graph.
3. **Path safety** — workdirs constrained by middleware / allowlist;
   no `shell=True`.
4. **Annotations** — `readOnlyHint=False`, `destructiveHint=True`; no
   long blocking wait (agent polls with a read tool).
5. **Documented blast radius** — this page + changelog updated with the
   tool.

Batch sweeps, open-ended resource mirrors, and reverse-control of remote
agents stay out of MCP.

## Where providers live

| Kind | Placement |
|------|-----------|
| **First-party** (molq, molexp, …) | `src/molmcp/providers/<name>/` + entry point `molmcp.providers.<name>`. Upstream package is a **lazy optional** import. Zero FastMCP in the science package. |
| **Third-party** | Sibling package or package `mcp` extra — see [Write a Provider](../guides/write-a-provider.md). |

## First-party providers

### molexp — `src/molmcp/providers/molexp/`

| Tool | Kind | Role |
|------|------|------|
| `molexp_list_projects` | Read-only | Workspace project navigation |
| `molexp_list_experiments` | Read-only | Experiments under a project |
| `molexp_list_runs` | Read-only | Runs by scope / status |
| `molexp_workspace_layout` | Read-only | On-disk workspace contract |
| `molexp_check_layout` | Read-only | Lint a path against that contract |
| scaffold tools | Idempotent create-or-get | Materialize tree nodes; never drive run batches or workflow runtime |

### molq — `src/molmcp/providers/molq/`

Entry point: `molq = "molmcp.providers.molq:MolqProvider"`.
Upstream: lazy `import molq` (package `molcrafts-molq`).

| Tool | Kind | Role |
|------|------|------|
| `molq_list_jobs` | Read-only | Queue dashboard from the molq job store |
| `molq_get_job` | Read-only | Single job (+ optional scheduler refresh / transitions) |
| `molq_job_logs` | Read-only | stdout/stderr text (tail; no follow) |
| `molq_list_destinations` | Read-only | Profiles + SSH Host aliases |
| `molq_list_queue` | Read-only | Live scheduler queue (not the job store) |
| `molq_submit_job` | Controlled mutation | Single job; CLI-shaped argv fields; opt-in; no block-wait |
| `molq_cancel_job` | Controlled mutation | Cancel one job by id; same opt-in as submit |

**Out of MCP for molq**

- Full `Submitor` / `JobResources` object mirror
- Cleanup / watch / daemon as default tools
- Nerve ingest or reverse-control from the MCP process
- Batch submit loops (agent script or molexp orchestration)

### Other domain providers

| Provider | Path | Role |
|----------|------|------|
| molpy | `providers/molpy/` | Call-time catalogs (`list_compute_ops`, `list_readers`) and path actions (`inspect_structure`) |
| molpack | `providers/molpack/` | Live-module restraint/format catalogs; `inspect_script` |
| lammps | `providers/lammps/` | Doc/DSL navigator over in-memory tables (no `lmp` binary required to register) |

molrs is indexed by discovery only — no first-party provider entry point
(Python API is fully importable).

## Discovery-first workflow

Default discovery sources cover MolCrafts packages
`{molpy, molpack, molrs, molq, molexp, molnex}` (local install when present,
GitHub otherwise). Agents get:

- Discovery tools over the code graph (search, outline, open, relations, …)
- In-tree provider tools for registered providers (molexp, molq, …)

Upstream adds or renames a function? Re-index and rediscover — no hand-curated
API mirror in molmcp. Custom multi-step analysis? Agent writes the script.

## When to add a new provider tool

Walk the four conditions (and controlled-mutation rules if writing). If a
condition fails — and the answer does not need runtime state discovery cannot
see — push back and document a discovery recipe instead.

## Read next

- **[Providers](providers.md)** — Protocol and registration mechanics
- **[Middleware](middleware.md)** — What wraps every registered tool
- **[Write a Provider](../guides/write-a-provider.md)** — Third-party packaging
