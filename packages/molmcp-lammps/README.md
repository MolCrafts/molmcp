# molmcp-lammps

MCP plugin exposing a knowledge navigator over docs.lammps.org. The
provider does **not** invoke `lmp`, **not** fetch docs over the network,
and **not** read the local filesystem outside its own Python modules.
Every tool is a pure function over small in-memory tables.

Thirteen tools spanning doc routing (`get_doc_index`,
`get_command_doc` / `get_style_doc` / `get_howto_doc`), task planning
(`plan_task`, `get_workflow_outline`), script tooling (`parse_script`,
`validate_script`, `explain_command`), howto registry (`list_howtos`,
`search_howtos`, `get_howto`), and error matcher (`explain_error`).

## Run standalone

```bash
uv run --package molmcp-lammps molmcp-lammps --transport stdio
```

## Maintenance: refresh the slug map

```bash
uv run --package molmcp-lammps molmcp-lammps doc update --version stable
uv run --package molmcp-lammps molmcp-lammps doc update --check        # diff only
```

## Mount under a gateway

```python
from fastmcp import FastMCP
from molmcp_lammps.server import mcp as lammps_mcp

gateway = FastMCP("my-gateway")
gateway.mount(lammps_mcp, namespace="lammps")
```

## Default doc version

Set `LAMMPS_MCP_DEFAULT_VERSION` to one of `stable`, `latest`,
`release` to override the default branch the tools point at when a
call omits the `version` argument.
