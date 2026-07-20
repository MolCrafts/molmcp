# MolMCP

MolMCP is the local-first LLM context plane for the MolCrafts ecosystem. It
combines a strict capability registry with graph-indexed source discovery, then
exposes a small MCP surface for finding the right package, inspecting exact
evidence, and handing trusted executable capabilities to Molexp.

MolMCP does not execute workflows or schedule jobs. Molexp owns planning,
approval, execution, artifacts, and audit; Molq owns local/HPC job lifecycle.

## Core MCP surface

The default server exposes exactly four read-only tools:

| Tool | Purpose |
|---|---|
| `molcrafts_info` | Report sources, registry coverage, freshness, providers, and warnings. |
| `molcrafts_search` | Search registry items, code, docs, examples, and tests across all configured sources. |
| `molcrafts_describe` | Resolve one exact registry or snapshot-qualified symbol reference. |
| `molcrafts_explore` | Build a bounded, provenance-rich context pack for a task. |

A code or documentation hit is evidence, never an executable action. Only an
explicit `ExecutableCapabilityV1` from a validated manifest can be executable.
Remote manifests without a matching `expected_digest` are `search_only` by
default and cannot be handed to Molexp.

## Install and run

```bash
uv sync --extra dev
uv run molmcp serve
```

With no configuration file, MolMCP indexes the current workspace. A project can
define `molcrafts.json`:

```json
{
  "schema_version": "1",
  "sources": {
    "workspace": ".",
    "molpack": "pkg:molpack",
    "molvis": "github:MolCrafts/molvis@main"
  },
  "registries": [
    {"kind": "installed"},
    {
      "kind": "url",
      "location": "https://registry.example/{namespace}/manifest.json",
      "namespace": "@molpack",
      "expected_digest": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "headers": {"Authorization": "Bearer ${MOLMCP_REGISTRY_TOKEN}"}
    }
  ],
  "providers": ["molexp", "molq"],
  "watch": true,
  "server": {"transport": "stdio"}
}
```

Useful CLI commands:

```bash
uv run molmcp info
uv run molmcp search "build a solvated molecular box"
uv run molmcp explore "pack water around a polymer"
uv run molmcp index
uv run molmcp registry validate ./molcrafts.registry.json
uv run molmcp registry list
```

Streamable HTTP is opt-in. A non-loopback bind is rejected unless
`server.auth_token_env` names a populated bearer-token environment variable.
Registry credentials must also be environment references; they are never
returned by MCP tools.

## Registry and providers

Packages publish strict `molcrafts.registry.json` manifests through:

```toml
[project.entry-points."molmcp.capabilities"]
molpack = "molpack.molmcp:manifest_path"
```

Package-owned MCP extensions use a separate entry-point group:

```toml
[project.entry-points."molmcp.providers"]
molq = "molq.molmcp:MolqProvider"
```

Provider names are authority boundaries and automatic namespaces. A provider
named `molq` contributes tools as `molq_<tool>`; duplicate, invalid, or reserved
names fail closed. Package-specific adapters should depend only on public
upstream APIs and migrate to the package that owns them.

## Discovery

The MCP-free discovery engine indexes Python, Rust, TypeScript/JavaScript,
Markdown, JSON, and TOML. Each immutable source snapshot has an isolated SQLite
graph. Retrieval uses field-weighted lexical search plus deterministic
reciprocal-rank fusion; graph relationships add evidence after retrieval and
heuristic call edges never influence relevance.

Cache identity includes schema, analyzer, resolver, engine, overlay, and catalog
state. Writes use a process lock, temporary database, fsync, and atomic replace.

## Development

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -v
```

The active design and acceptance contract is
[`.Codex/specs/molmcp-vnext.md`](.Codex/specs/molmcp-vnext.md).

License: BSD-3-Clause.
