# Installation

molmcp is published on PyPI as **`molcrafts-molmcp`** and requires Python ≥ 3.12.
The import name is `molmcp`.

## With pip

```bash
pip install molcrafts-molmcp
```

## With uv

```bash
uv add molcrafts-molmcp
```

## What gets installed

The base install is infrastructure only: the multi-plane MCP runtime, knowledge
index, and CLI. Domain packages (molpy, molvis, molq, …) stay optional — install
them when you need a provider plane or richer local discovery.

## Optional extras

| Extra | Purpose | Command |
|-------|---------|---------|
| `dev` | pytest + ruff for the test suite and linting | `pip install "molcrafts-molmcp[dev]"` |
| `docs` | local preview of this documentation site | `pip install "molcrafts-molmcp[docs]"` |

Docs pin: `zensical>=0.0.53` and `molcrafts-zensical-theme>=0.2.5`.

## Verify the install

```bash
python -c "import molmcp; print(molmcp.__version__)"
molmcp planes
molmcp --help
```

`molmcp planes` lists connectable product domains. Each plane is a **separate**
MCP process (`molmcp serve <plane>`).

## Editable install (contributors)

```bash
git clone https://github.com/MolCrafts/molmcp.git
cd molmcp
uv sync --extra dev
uv run pytest -v
```

## Knowledge sources (`molcrafts.json`)

The **molcrafts** plane indexes packages from a config file (schema_version
`"2"`). Provider planes do not require it.

```json
{
  "schema_version": "2",
  "sources": {
    "workspace": ".",
    "molpy": "pkg:molpy"
  },
  "watch": true,
  "server": { "transport": "stdio" }
}
```

Optional env allowlist: `MOLMCP_SOURCES=molpy,molrs` restricts which knowledge
sources appear in `packages` / `outline` / `open`.

## Next steps

- **[Quickstart](quickstart.md)** — serve catalog + molcrafts and wire a client
- **[Architecture](../concepts/architecture.md)** — one plane per connection
- **[Deploy](deploy.md)** — multi-link stdio layout for Claude Code
