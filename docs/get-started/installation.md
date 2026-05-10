# Installation

molmcp is published on PyPI as **`molcrafts-molmcp`** and requires Python ≥ 3.12. The import name is `molmcp`.

## With pip

```bash
pip install molcrafts-molmcp
```

## With uv

```bash
uv add molcrafts-molmcp
```

## What gets installed

The base install pulls in molmcp itself plus its server-framework dependency. Nothing else — no NumPy, no MolCrafts packages, no domain dependencies. molmcp stays infrastructure-only on purpose.

## Optional extras

| Extra | Purpose | Command |
|-------|---------|---------|
| `dev` | pytest + pytest-asyncio for the test suite | `pip install "molcrafts-molmcp[dev]"` |
| `docs` | local preview of this documentation site | `pip install "molcrafts-molmcp[docs]"` |

## Verify the install

```bash
python -c "import molmcp; print(molmcp.__version__)"
```

```bash
molmcp --help
```

You should see the CLI usage. If `molmcp` isn't on your PATH, `python -m molmcp` is equivalent.

## Editable install (contributors)

```bash
git clone https://github.com/MolCrafts/molmcp.git
cd molmcp
pip install -e ".[dev]"
pytest
```

All collected tests should pass (currently 62).

## Adopting molmcp in a MolCrafts package

If you're maintaining a MolCrafts package and want it to expose tools through molmcp, declare molmcp as an *optional* dependency rather than a hard one — users who don't run an MCP client shouldn't pay for it:

```toml
# in your MolCrafts package's pyproject.toml
[project.optional-dependencies]
mcp = ["molcrafts-molmcp >= 0.2, < 0.3"]
```

Then ship a Provider class and an entry point. See [Writing a Provider](../guides/write-a-provider.md).

## Next steps

- **[Quickstart](quickstart.md)** — expose your first MolCrafts package in 60 seconds
- **[Architecture](../concepts/architecture.md)** — how the layers fit together
