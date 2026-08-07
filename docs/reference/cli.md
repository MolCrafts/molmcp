# CLI reference

```
molmcp [-h] {serve,planes,route,info,search,explore,index,registry} ...
python -m molmcp …
```

The `molmcp` script is installed by `pip install molcrafts-molmcp`.
`python -m molmcp` is equivalent when the package is importable.

**Default with no arguments:** `molmcp planes` (list connectable planes).
There is **no** bare `molmcp` that starts a mega-server.

## `molmcp serve <plane>`

Start **one** MCP plane (one process, one server name = plane id).

```bash
molmcp serve catalog
molmcp serve molcrafts
molmcp serve molvis
molmcp serve molq
```

| Argument / flag | Meaning |
|-----------------|---------|
| `plane` | Required. `catalog` \| `molcrafts` \| a provider name (`molvis`, `molq`, …). Run `molmcp planes`. |
| `--config PATH` | `molcrafts.json` (default `./molcrafts.json` when present). Required for useful `molcrafts` knowledge. |
| `--env LOCATOR` | Python env to discover packages from (venv root, interpreter, or site-packages). |
| `--transport {stdio,streamable-http}` | Override transport (default stdio / config). |
| `--host` / `--port` | HTTP bind (streamable-http only). Non-loopback needs `server.auth_token_env`. |
| `--no-discover` | Do not load `molmcp.providers` entry points (provider plane needs inject). |

Tool ids on the client are `<plane>__<tool>` (e.g. `molcrafts__packages`,
`molvis__open`).

## `molmcp planes`

List connectable product domains (on-demand multi-link catalog).

```bash
molmcp planes
molmcp planes --json
```

## `molmcp route <task>`

Suggest which plane(s) to connect for a free-text task.

```bash
molmcp route "draw dopamine"
molmcp route "list slurm jobs"
```

## Offline knowledge helpers

These drive the collection index without an MCP client (need `molcrafts.json`
sources):

| Command | Role |
|---------|------|
| `molmcp info` | Registry + index coverage |
| `molmcp search <query>` | Full collection search (`--kind`, `--namespace`, `--source`, `--limit`) |
| `molmcp explore <task>` | Bounded task context pack (`--budget-chars`, …) |
| `molmcp index` | Index configured sources (`--force`, optional source list) |
| `molmcp registry` | Inspect capability manifests |

```bash
molmcp search "Conformer" --source molpy
molmcp index --force
```

## Client wiring (multi-link)

```bash
claude mcp add catalog -- molmcp serve catalog
claude mcp add molcrafts -- molmcp serve molcrafts
claude mcp add molvis -- molmcp serve molvis
```

See [Deploy](../get-started/deploy.md) for the full layout.

## Read next

- [Architecture](../concepts/architecture.md)
- [API reference](api.md)
- [Quickstart](../get-started/quickstart.md)
