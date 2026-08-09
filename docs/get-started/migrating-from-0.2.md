# Migrating from 0.2

0.5 replaces the single `molmcp` server with one server per product domain.
Nothing carries over automatically: **every tool id on the wire changed**, the
CLI grew a required argument, the config file's schema version moved, and the
environment variables stopped being read.

If you are upgrading from 0.2.1 — the last published release — this page is the
whole list. There is no compatibility layer; each break is loud except where
noted.

## Installing 0.5 with uv

`uv add molcrafts-molmcp` needs `--prerelease=allow` until FastMCP 4.0.0
ships. See [Installation](installation.md#with-uv) for why; pip needs
nothing extra.

## One server became five

Before, `molmcp serve` started one process that mounted every provider and
prefixed their tools. Now each product domain is its own MCP connection:

| Plane | Serves |
|---|---|
| `catalog` | Which planes exist and which to route to |
| `molcrafts` | Knowledge and discovery over installed packages |
| `molq` | Job lifecycle |
| `molexp` | Experiment-data workspaces |
| `molvis` | A live viewer session |

A client connects to the planes it wants, as separate servers. There is no
mega-server to fall back to: passing more than one provider raises
`ValueError: multi-provider servers are removed; serve one plane per process`.

## Every tool id changed

Tool names are bare now and the server name carries the domain, so the id your
agent sees is different for every tool. There is **no overlap** with the old
set — nothing silently keeps working:

| 0.2 | 0.5 |
|---|---|
| `mcp__molmcp__molcrafts_packages` | `mcp__molcrafts__packages` |
| `mcp__molmcp__molcrafts_search` | `mcp__molcrafts__search` |
| `mcp__molmcp__molcrafts_open` | `mcp__molcrafts__open` |
| `mcp__molmcp__molvis_open` | `mcp__molvis__open` |
| `mcp__molmcp__molq_list_jobs` | `mcp__molq__list_jobs` |

Any prompt, allowlist, or auto-approve rule naming a tool must be rewritten.

## Client configuration

`molmcp serve` now takes a **required** plane argument, so an existing entry
fails at startup with an argparse error rather than serving anything:

```jsonc
// 0.2 — no longer starts
{ "mcpServers": { "molmcp": { "command": "molmcp", "args": ["serve"] } } }
```

```jsonc
// 0.5 — one entry per plane you want
{
  "mcpServers": {
    "molcrafts": { "command": "molmcp", "args": ["serve", "molcrafts"] },
    "molq":      { "command": "molmcp", "args": ["serve", "molq"] }
  }
}
```

`molmcp client <host>` generates this for you and omits planes whose package is
not installed.

Bare `molmcp` no longer starts a server either — it prints the plane catalog.

## Environment variables became settings

Eight variables are no longer read. **This is the one silent break**: a shell
that exports them still runs, and molmcp simply ignores them. Settings replace
them because a value living in one shell cannot be reported by
`molmcp config list`, and two clients launching the server differently would
disagree about it with nothing to point at.

| 0.2 environment variable | 0.5 |
|---|---|
| `MOLMCP_SOURCES` | `molmcp config set sources.<name> <locator>` |
| `MOLMCP_ENV` | `molmcp config set pythonEnv <locator>` |
| `MOLMCP_DISCOVER` | `molmcp config set discoverInclude` / `discoverExclude` |
| `MOLMCP_CACHE_DIR` | `molmcp config set cacheDir <path>` |
| `XDG_CACHE_HOME` | `molmcp config set cacheDir <path>` |
| `MOLQ_DB_PATH` | `molmcp config set molq.database <path>` |
| `MOLMCP_MOLQ_SUBMIT` | `molmcp config set molq.allowSubmit true` |
| `MOLEXP_WORKSPACE` | `molmcp config set molexp.workspace <path>` |

Settings live in `~/.molmcp/settings.json`, with optional per-project
`.molmcp/settings.json` and `.molmcp/settings.local.json` layered over it.
`molmcp config list` shows the merged result and which files produced it.

Unknown keys are rejected, including nested ones — `molq.allowsubmit` is an
error naming the keys that do exist, rather than a setting that stores fine and
is read by nothing.

Two environment variables remain, both secrets, because a settings file is
meant to be committable: the bearer token an HTTP-transport server compares
against, and `GITHUB_TOKEN` for `github:` sources. Each is named *by* a
setting rather than storing its value.

## The config file

`CONFIG_SCHEMA_VERSION` moved from `"1"` to `"2"`, so an existing
`molcrafts.json` is rejected with a message naming the expected version. Bump
`schema_version` after checking the fields against
[Settings](installation.md#settings).

`./molcrafts.json` is also **no longer auto-loaded** from the working
directory. Pass `--config path/to/molcrafts.json` explicitly. A working
directory that silently changes which packages a server indexes is a surprise
worth removing.

## Discovery cache

The extract cache was renamed `extract.db` → `code-index.db`. The old file is
deleted on the first index and the content re-extracted; nothing is lost but
the first run after upgrading is a full re-index.

`graph.db` itself is unchanged — `SCHEMA_VERSION` and `ANALYZER_VERSION` did
not move, so an existing graph is still read.

**If you had `XDG_CACHE_HOME` set, delete the old cache by hand.** 0.2 put the
cache under `$XDG_CACHE_HOME/molmcp/discovery`; 0.5 always uses
`~/.cache/molmcp/discovery`, and points `cacheDir` at anywhere else you want:

```bash
du -sh "${XDG_CACHE_HOME:?not set — nothing to clean}/molmcp/discovery"
rm -rf "$XDG_CACHE_HOME/molmcp/discovery"
molmcp config set cacheDir /path/you/prefer   # optional
```

molmcp cannot clean that up for you, because finding it would mean reading the
variable it no longer reads. The old tree is inert but it is not small — the
extract cache alone routinely reached several gigabytes.

## Removed Python API

`molmcp.registry` is gone, along with `Registry`, `CatalogItemV1`,
`ExecutableCapabilityV1` and `CAPABILITY_ENTRY_POINT_GROUP` from `molmcp`'s
top level, and the `molmcp registry` CLI command.

The `molmcp.capabilities` entry-point group is no longer read by anything. A
package still declaring it is ignored — silently, since nothing remains to
report the group.

`create_server` is now a thin wrapper over `create_plane`: `name` means the
plane id, `provider_names=` is dropped, and `providers=[a, b]` raises. Prefer
`create_plane(plane_id)` directly.
