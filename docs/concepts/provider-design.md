# Provider design contract

molmcp is **not** a tool-registration mirror of upstream packages, and it
is **not** a single mega-server. Each provider is its own MCP plane
(`molmcp serve <name>`); clients connect planes on demand.

The primary mechanism for an agent to use a MolCrafts package is the
[discovery engine](discovery.md) on the **molcrafts** plane: query the
indexed code graph for symbols, relationships, and examples, then call
the API from agent Python or `molvis` `exec`. A Provider that adds a
hand-curated tool catalog has to justify its existence against this
baseline — otherwise we ship maintenance burden (every upstream API
change becomes a molmcp PR) and double-source the truth.

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

1. **Explicit opt-in** — a settings gate, default off
   (`molmcp config set molq.allowSubmit true`). It must be *settings*: every
   provider is built with `cls()`, so a constructor keyword is unreachable
   from the CLI a client actually launches, and there are no environment
   switches. A gate no client can open is the same as a tool that never works.
2. **Frozen flat signature** — CLI-shaped primitives, not the full
   upstream object graph.
3. **Path safety** — workdirs constrained by middleware / allowlist;
   no `shell=True`.
4. **Annotations** — `MUTATION` (`read_only_hint=False`, `destructive_hint=True`); no
   long blocking wait (agent polls with a read tool).
5. **Documented blast radius** — this page updated with the tool.

Batch sweeps, open-ended resource mirrors, and reverse-control of remote
agents stay out of MCP.

## Where providers live

| Kind | Placement |
|------|-----------|
| **First-party** (molq, molexp, …) | `src/molmcp/providers/<name>/` + entry point `molmcp.providers.<name>`. Upstream package is a **lazy optional** import. Zero FastMCP in the science package. |
| **Third-party** | Sibling package or package `mcp` extra — see [Write a Provider](../guides/write-a-provider.md). |

## The shape every provider has

A provider subclasses `ProviderBase` and declares each tool as a **method**
carrying `@tool(...)`. There is no `register()` to write: the base collects
the declarations, checks the upstream package once, and registers them
bare. Bound methods reach FastMCP directly, so `self` stays out of the tool
schema and the docstring an agent reads is the one on the method.

This replaced three hand-written `register()` methods of 349, 402 and 424
lines — most of a class each — that had drifted into three availability
probes, three differently-worded install hints, and three annotation sets
that disagreed with one another.

**Reaching upstream happens at declared seams.** Every place a provider
touches its science package is a constructor-injectable factory, defaulting
to the real thing:

| Plane | Seams |
|-------|-------|
| molvis | `stage_factory` |
| molq | `store_factory`, `submitor_factory`, `destinations_factory` |
| molexp | workspace factory and ingest fn (in `adopt/`) |

That is not a testing convenience bolted on afterwards — it is what makes
the plane servable by an embedder with its own backend, and `probe()`
reports available when every seam is injected. It is also why these planes
are covered without their science packages installed, which is the only way
CI can test molmcp rather than testing molq.

## First-party providers

### molexp — `src/molmcp/providers/molexp/`

Tools are **bare names** on the `molexp` plane (client: `molexp__list_projects`).
Never `molexp_list_projects` or `molexp_molexp_*`.

| Tool | Kind | Role |
|------|------|------|
| `list_projects` | Read-only | Workspace project navigation |
| `list_experiments` | Read-only | Experiments under a project |
| `list_runs` | Read-only | Runs by scope / status |
| `workspace_layout` | Read-only | On-disk workspace contract (the law) |
| `validate_workspace` | Read-only | Report layout/OKF **errors that need fixing** (actionable hints) |
| `validate_workflow` | Read-only | Check a workflow definition without running it |
| `materialize_workspace`, `add_project`, `add_experiment`, `create_run` | Idempotent create-or-get | Materialize tree nodes; never drive run batches or workflow runtime |
| `plan_adoption` | Read-only | Survey a legacy directory and propose a mapping; writes nothing |
| `adoption_status` | Read-only | Progress of an in-flight adoption from its ledger |
| `run_adoption` | **Controlled mutation** | Execute a plan. **In move mode it unlinks each source file after verifying its hash** — the one destructive tool on this plane. Resumable from the ledger |
| `ingest_metrics` | Idempotent create-or-get | Convert a run's logs into a metrics buffer; writes nothing else into the run |

Deleting an adopted source directory is deliberately **not** a tool. Every
other step in that flow is provable and resumable; an irreversible bulk delete
is neither, so it stays a human decision made with the ledger in hand.

### molq — `src/molmcp/providers/molq/`

Entry point: `molq = "molmcp.providers.molq:MolqProvider"`.
Upstream: lazy `import molq` (package `molcrafts-molq`).

Bare names on the `molq` plane (client: `molq__list_jobs`).

| Tool | Kind | Role |
|------|------|------|
| `list_jobs` | Read-only | Queue dashboard from the molq job store |
| `get_job` | Read-only | Single job (+ optional scheduler refresh / transitions) |
| `job_logs` | Read-only | stdout/stderr text (tail; no follow) |
| `list_destinations` | Read-only | Profiles + SSH Host aliases |
| `list_queue` | Read-only | Live scheduler queue (not the job store) |
| `submit_job` | Controlled mutation | Single job; CLI-shaped argv fields; opt-in; no block-wait |
| `cancel_job` | Controlled mutation | Cancel one job by id; same opt-in as submit |

**Out of MCP for molq**

- Full `Submitor` / `JobResources` object mirror
- Cleanup / watch / daemon as default tools
- Nerve ingest or reverse-control from the MCP process
- Batch submit loops (agent script or molexp orchestration)

### molvis — `src/molmcp/providers/molvis/`

Entry point: `molvis = "molmcp.providers.molvis:MolvisProvider"`.
Upstream: lazy `import molvis` (package `molcrafts-molvis`) — the
MolCrafts molecular viewer: a Python-driven 3D structure view that
renders in a browser page and streams the user's interactions back.

This provider is a **workbench**, not a tool catalog. It keeps a live
molvis `Stage` — the Python object that controls one viewer — alive
inside the `molmcp serve` process and lends the agent a Python session
bound to it. That is precisely the state discovery cannot reach:
indexing sees the *source* of `draw_frame`, never the *running* stage,
the structure object built two calls ago, or the click the user just
made on the canvas.

| Tool | Kind | Role |
|------|------|------|
| `open` | Session lifecycle | Create a stage plus its Python namespace; returns `session_id` and the `connection_url` the user opens in a browser. A duplicate id is a structured error, never a silent attach |
| `close` | Session lifecycle | Close the stage, drop the namespace, remove the session |
| `list_sessions` | Read-only | Live sessions, as molvis's own session summary reports them |
| `exec` | Session write | Run agent-written Python in that namespace (`stage` prebound, bindings persist across calls); returns captured stdout, the last expression's `repr`, or a structured traceback |
| `poll_events` | Read-only | Pull viewer events (selection changed, mode changed, …) after a cursor; payloads verbatim, with a `truncated` flag when history was evicted |
| `capabilities` | Read-only | The live stage's public surface, read off the object: name, kind (`method` / `property` / `attribute`), signature, one-line summary — plus which build of molvis / molpy / molrs is loaded |
| `refresh` | Session write | Drop edited pure-Python packages from this process's module cache so the next `exec` re-reads them, and report every mapped compiled extension that a rebuild has left stale |

**No invented API.** All seven are generic primitives — session
lifecycle, code execution, event pull, runtime reflection — and not one
of them names a molecular concept. The vocabulary the agent uses *inside* `exec`
is molvis's and molpy's own public Python API (`stage.draw_frame(mol)`,
`stage.get_selected()`, `mp.parser.parse_molecule(…)`), learned through
[discovery](discovery.md) and never mirrored here. Upstream adds,
renames, or retires a method and molmcp changes by zero lines. Wrapper
tools of every granularity are refused for that reason: composite
(`show_smiles` = parse + embed + draw), 1:1 (`draw`, `clear`), and an
agent-facing JSON-RPC `call` surface alike — each buys convenience with
a second copy of the truth that molmcp would then have to keep in sync.

`capabilities` is the same rule seen from the other side, not an
exception to it. It defines no vocabulary — it reflects whatever the
stage happens to expose, so upstream still changes molmcp by zero lines.
What it adds is the part [discovery](discovery.md) structurally cannot
reach: a static index describes the source on disk, while an agent is
driving an object in *this* process. Whether a name is a property or a
method, and whether the loaded build is even the one on disk, are facts
about the running process. `refresh` owns the other half of that —
and reports what it could not refresh, because a refresh that quietly
leaves a rebuilt `.so` mapped makes an agent test the old code and
report the result as the new behaviour.

**Trust model.** `exec` runs unsandboxed in a server the user
started on their own machine, so a session carries the trust level of a
Jupyter kernel — no gating machinery, no env switches, all seven tools
always available. (It is not a [controlled
mutation](#controlled-mutations) in the sense above: it is a code
channel, not a frozen-signature write tool.)

**Four parties, one session.** The human operates the *display* surface
— looking at and clicking the browser canvas molvis renders; the agent
operates the *code* surface — the in-process Python session where the
structure object is the single source of truth and the canvas is only
its projection. The two wills meet asynchronously in session state: a
human selection reaches the agent through `poll_events`, an agent
edit reaches the human through the next redraw. The canvas↔code wire
protocol is molvis's internal business; molmcp neither touches nor
exposes it.

**Out of MCP for molvis**

- Named wrappers of any granularity, and a raw `send_cmd` / JSON-RPC tool surface
- Sandboxing, permission gates, or env-var opt-ins for `exec`
- Attaching to a viewer session started outside this process
- The end-to-end dialogue playbook — it lives out-of-tree, see
  [MolVis workbench](../guides/molvis-workbench.md)

How to fly these — build, draw, poll, read the selection, edit,
redraw — is taught once in
**[MolVis workbench](../guides/molvis-workbench.md)**; every API inside
the loop belongs to discovery.

### Other domain providers

There are none. molq, molexp and molvis are the three in-tree planes, and each
is here because it answers something a static index cannot: live job state, an
on-disk workspace, an in-process viewer session.

molpy, molpack, molrs and LAMMPS are reached through **discovery** instead —
their Python APIs are importable, so an agent finds the real symbols and
scripts them. Wrapping an importable API in named tools is the thing this page
exists to refuse.

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
