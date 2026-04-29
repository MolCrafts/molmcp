# Naming convention

Three kinds of names appear across the MolCrafts ecosystem; each has its own
axes and grammar. Following these rules keeps names predictable for users and
lets new domains plug in without renaming churn.

| Kind | Where | Pattern |
|---|---|---|
| **MCP tools** | Provider source (Python functions decorated with `@mcp.tool`) | `<verb>_<object>` |
| **Skills** | `.claude/skills/<name>/` (slash commands) | `<domain>-<phase>[-<scope>]` |
| **Subagents** | `.claude/agents/<name>.md` | `<domain>-<role>` |

The three patterns are orthogonal: a tool is a noun-shaped capability, a skill
is a verb-shaped workflow, an agent is a role.

---

## MCP tools

Tools are exposed by providers via `@mcp.tool`. The provider is mounted into a
gateway with `mcp.mount(provider, namespace="<ns>")`, and the namespace is
prepended automatically. **The tool function name MUST NOT include the
domain** — that prefix comes from the mount, and including it twice is
redundant.

### Form

```
<verb>_<object>
```

- `snake_case`
- Object is a noun. Plural for collection returns (`list`, `search`),
  singular for single-item returns (`get`, `inspect`, `validate`).

### Verb vocabulary

Pick from this closed set. Do not invent new verbs.

**Read** (no side effects):

| Verb | Returns | Example |
|---|---|---|
| `list` | a collection | `list_readers`, `list_experiments` |
| `get` | one item by ID/key | `get_run`, `get_doc_index` |
| `search` | matches for a query | `search_howtos` |
| `inspect` | structured analysis of an input | `inspect_structure` |
| `validate` | pass/fail + diagnostics | `validate_script` |

**Write** (side effects):

| Verb | Action | Example |
|---|---|---|
| `run` | execute a job | `run_simulation` |
| `create` | new entity | `create_experiment` |
| `update` | mutate entity | `update_run_status` |
| `delete` | remove entity | `delete_asset` |

**Domain extension** (use only when no read verb fits):

| Verb | Use when |
|---|---|
| `parse` | text → structured (and the output is the parse tree, not analysis) |
| `explain` | input → human-readable narrative beyond `inspect` |
| `plan` | input → action sequence / workflow outline |

If you find yourself reaching for a different verb, check first whether
`get` or `inspect` fits — most "where to find X" tools are `get`, most
"analyze X" tools are `inspect`.

### Examples

| Bad | Why | Good (mounted as `<ns>_…`) |
|---|---|---|
| `list_molpy_readers` | domain repeated | `list_readers` → `molpy_list_readers` |
| `inspect_structure_file` | "file" implicit from inputs | `inspect_structure` → `molpy_inspect_structure` |
| `where_to_read_lammps_command` | not a verb; domain repeated | `get_command_doc` → `lammps_get_command_doc` |
| `lookup_lammps_error` | `lookup` redundant with `get` | `explain_error` → `lammps_explain_error` |
| `read_metrics` | `read` not in vocab | `get_metrics` → `molexp_get_metrics` |

---

## Skills (slash commands)

Skills live under `.claude/skills/<name>/`. Each is a workflow the user
triggers as `/<name>`.

### Form

```
<domain>-<phase>[-<scope>]
```

- `domain`: project name (`molexp`, `molmcp`, `molvis`, …)
- `phase`: one of the closed phase verbs below
- `scope`: optional, narrows the phase to a specific layer/object

### Phase vocabulary (closed)

| Phase | Means |
|---|---|
| `plan` | turn a goal into a structured spec / approach |
| `add` | implement new functionality |
| `fix` | corrective change for a known defect |
| `debug` | investigate without committing to a fix |
| `test` | author or expand tests |
| `review` | quality / architecture review |
| `refactor` | restructure without behaviour change |
| `design` | visual / UX work |
| `docs` | docstrings, READMEs, OpenAPI descriptions |
| `note` | capture decisions, observations, follow-ups |

### Scope vocabulary (open, project-specific)

Scope names live in each project's `CLAUDE.md`. Add as needed but document
them. Common scopes:

`api`, `ui`, `task`, `step`, `tool`, `schema`, `agent`, `db`, `provider`

### Examples

| Skill | Decomposition | Triggers |
|---|---|---|
| `/molexp-plan` | molexp · plan | spec drafting |
| `/molexp-add` | molexp · add | full feature implementation |
| `/molexp-add-api` | molexp · add · api | API endpoint scaffold |
| `/molexp-add-ui` | molexp · add · ui | renderer + state + mock |
| `/molexp-add-task` | molexp · add · task | workflow `Task`/`Actor` |
| `/molexp-add-tool` | molexp · add · tool | PydanticAI agent tool |
| `/molexp-test` | molexp · test | TDD authoring |
| `/molexp-review` | molexp · review | architecture / perf review |
| `/molexp-design` | molexp · design | visual polish pass |
| `/molexp-fix` | molexp · fix | corrective change |
| `/molexp-debug` | molexp · debug | investigation only |
| `/molexp-refactor` | molexp · refactor | structural cleanup |
| `/molexp-docs` | molexp · docs | doc updates |
| `/molexp-note` | molexp · note | capture insight |

---

## Subagents

Subagents represent reviewer roles invoked from skills. They are role
nouns, not workflows.

### Form

```
<domain>-<role>
```

- `role` is a singular noun ending in `-er` / `-or` describing the
  perspective: `architect`, `optimizer`, `reviewer`, `tester`,
  `documenter`, `designer`, `integrity`-like exception only when the
  role name has no `-er` form.

### Examples

`molexp-architect`, `molexp-optimizer`, `molexp-tester`,
`molexp-documenter`, `molexp-designer`, `molexp-security`.

---

## Why this is extensible

- **New tool**: pick a verb from the closed table, add the new object
  noun. No domain churn — namespace handles that.
- **New skill**: combine an existing phase with a new scope. The phase
  table only grows by ecosystem-wide consensus.
- **New domain**: a new project (`molcfg`, `molnex`, …) reuses the same
  three patterns; only the domain prefix changes.
- **New role**: append a new `-er` agent under the same domain.

The closed verb / phase tables are the load-bearing part. They are kept
small on purpose: contributors should not have to learn 30 verbs to
predict what something is called.
