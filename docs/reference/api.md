# API reference

Public Python surface of molmcp (multi-plane). Prefer the CLI for day-to-day
use; import the builders when embedding a plane in tests or a custom host.

```python
from molmcp import (
    create_plane,
    create_server,  # thin wrapper → create_plane
    Provider,
    discover_providers,
    known_plane_ids,
    list_plane_infos,
    route_task,
    load_config,
    AppConfig,
    MolCraftsContextProvider,
    PROVIDER_ENTRY_POINT_GROUP,
)
```

## `create_plane`

```python
def create_plane(
    plane: str,
    *,
    config: AppConfig | None = None,
    discover_entry_points: bool = True,
    provider: Provider | None = None,
    # … middleware / instructions kwargs — see source
) -> FastMCP
```

Build **one** FastMCP server for a single plane id. The MCP server **name** is
the plane id (`catalog`, `molcrafts`, `molvis`, …). Tools register with bare
names; clients see `molvis__open`, not `molmcp__molvis_open`.

| Plane | Content |
|-------|---------|
| `catalog` | `list_planes`, `route` |
| `molcrafts` | Knowledge tools via `MolCraftsContextProvider` (needs config sources) |
| provider name | Entry-point or injected `Provider` for that product |

```python
from molmcp import create_plane, load_config

mcp = create_plane("catalog")
mcp.run(transport="stdio")
```

## `create_server`

Compatibility wrapper that forwards to `create_plane`. New code should call
`create_plane` with an explicit plane id.

## Planes helpers

```python
known_plane_ids() -> frozenset[str]
list_plane_infos() -> list[PlaneInfo]
route_task(task: str) -> dict
```

Used by `molmcp planes` / `molmcp route` and by the catalog plane tools.

## `Provider`

```python
class Provider(Protocol):
    name: str
    def register(self, mcp: FastMCP) -> None: ...
```

Each provider is its **own** plane (`molmcp serve <name>`). Register via the
`molmcp.providers` entry-point group (`PROVIDER_ENTRY_POINT_GROUP`). See
[Provider design](../concepts/provider-design.md).

## `MolCraftsContextProvider`

Registers hierarchical knowledge tools on the **molcrafts** plane:

| Tool | Role |
|------|------|
| `packages` | L0 package directory |
| `outline` | Module / symbol map for one source |
| `open` | One symbol page (optional source body) |
| `search` / `suggest` | Index helpers |
| `compose` | Budgeted multi-page pack |
| `info` | Ops / health |

Tool names are bare; with server name `molcrafts` clients call
`molcrafts__packages`, etc.

Science APIs are **not** MCP tools — discover them here, then call them from
agent Python or `molvis` `exec`.

## Discovery engine (MCP-free)

```python
from molmcp.discovery import DiscoveryEngine

engine = DiscoveryEngine()
result = engine.index("pkg:molpy")
query = engine.query("pkg:molpy")
```

The knowledge plane builds on this graph. See
[Discovery engine](../concepts/discovery.md).

## Config

```python
from molmcp import load_config, AppConfig

cfg = load_config("molcrafts.json")  # schema_version "2"
```

Schema v1 mega-server configs are not supported.

## Middleware & safety

Path-safety and response-limit middleware still apply on plane servers.
Annotation validation requires tools to declare `readOnlyHint` or
`destructiveHint`. Details: [Middleware](../concepts/middleware.md),
[Security](../guides/security.md).

## Read next

- [CLI reference](cli.md)
- [Architecture](../concepts/architecture.md)
- [Write a Provider](../guides/write-a-provider.md)
