# API reference

The public Python API of molmcp. Everything listed here is exported from the top-level `molmcp` package.

```python
from molmcp import (
    create_server,
    Provider,
    DiscoveryProvider,
    DiscoveryEngine,
    DiscoveryConfig,
    discover_providers,
    ENTRY_POINT_GROUP,
    PathSafetyMiddleware,
    ResponseLimitMiddleware,
    MissingAnnotationsError,
    validate_tool_annotations,
    run_safe,
    SubprocessResult,
    fence_untrusted,
)
```

## `create_server`

```python
def create_server(
    name: str = "molmcp",
    *,
    discovery_sources: Iterable[str] | None = None,
    discovery_config: DiscoveryConfig | None = None,
    providers: Iterable[Provider] | None = None,
    discover_entry_points: bool = True,
    enable_path_safety: bool = True,
    enable_response_limit: bool = True,
    response_limit_bytes: int = 256 * 1024,
    validate_annotations: bool = True,
    instructions: str | None = None,
) -> FastMCP
```

Build a fully configured `FastMCP` server.

| Parameter | Description |
|-----------|-------------|
| `name` | Server name advertised to MCP clients. |
| `discovery_sources` | Source specs the discovery engine may index — local paths, `pkg:<name>` for installed packages, or `github:owner/repo[@ref]`. Empty/`None` disables discovery. |
| `discovery_config` | Optional `DiscoveryConfig` for the engine (cache directory, limits, …). |
| `providers` | Explicit `Provider` instances to register, in order. They run *after* auto-discovered Providers. |
| `discover_entry_points` | If `True`, auto-discover Providers via the `molmcp.providers` entry point group. |
| `enable_path_safety` | Mount `PathSafetyMiddleware`. |
| `enable_response_limit` | Mount `ResponseLimitMiddleware`. |
| `response_limit_bytes` | Per-response truncation threshold. |
| `validate_annotations` | After all Providers register, ensure every tool exposes `readOnlyHint` or `destructiveHint`. Raises `MissingAnnotationsError` on violation. |
| `instructions` | Server-level instructions string sent to clients. |

Returns a ready-to-run `FastMCP` server instance. Call `.run(transport=...)` on it to start serving.

## `Provider`

```python
class Provider(Protocol):
    name: str
    def register(self, mcp: FastMCP) -> None: ...
```

Runtime-checkable Protocol. Any class with these two members satisfies it. See **[Providers](../concepts/providers.md)**.

## `DiscoveryProvider`

```python
class DiscoveryProvider:
    name: str = "discovery"
    def __init__(
        self,
        sources: list[str] | None = None,
        config: DiscoveryConfig | None = None,
    ): ...
    def register(self, mcp: FastMCP) -> None: ...
```

The built-in MCP interface to the discovery engine. Registers six
read-only tools — `molmcp_find_capability`, `molmcp_search_symbols`,
`molmcp_describe_symbol`, `molmcp_relations`, `molmcp_outline`,
`molmcp_refresh` — over the given `sources`. Empty/`None` registers
nothing. Every tool returns a plain dict carrying a `snapshot` freshness
block (`snapshot_id`, `origin`, `spec`, `commit`, `file_count`,
`freshness`).

You usually don't instantiate this directly; `create_server(discovery_sources=[...])` does it for you.

See **[Discovery engine](../concepts/discovery.md)** for the pipeline,
graph schema, and tool semantics.

## `DiscoveryEngine`

```python
class DiscoveryEngine:
    def __init__(self, config: DiscoveryConfig | None = None): ...
    def index(self, source: str, *, force: bool = False) -> IndexResult: ...
    def query(self, source: str) -> DiscoveryQuery: ...
    def refresh(self, source: str) -> IndexResult: ...
    def get_graph(self, source: str) -> CodeGraph: ...
```

The MCP-free core of `molmcp.discovery`. It resolves a source spec to an
immutable snapshot, statically indexes it into a SQLite code graph, and
answers structured queries against it. Importable, scriptable, and
testable without FastMCP:

```python
from molmcp.discovery import DiscoveryEngine

engine = DiscoveryEngine()
query = engine.query("pkg:molpy")
for node in query.search("radial distribution function"):
    print(node.qualname, node.file, node.start_line)
```

## `DiscoveryConfig`

```python
class DiscoveryConfig: ...
```

Configuration for the discovery engine — cache directory (defaults to
`~/.cache/molmcp/discovery/`, overridable with `MOLMCP_CACHE_DIR`),
snapshot retention limits, and local-source watching. Pass an instance
to `create_server(discovery_config=...)`, `DiscoveryProvider(...)`, or
`DiscoveryEngine(...)`.

## `discover_providers`

```python
def discover_providers() -> list[Provider]
```

Enumerate Provider instances declared via the `molmcp.providers` entry point group. Each entry point must resolve to a class; the class is instantiated with no arguments. Providers raising during instantiation are logged and skipped.

## `ENTRY_POINT_GROUP`

```python
ENTRY_POINT_GROUP: str = "molmcp.providers"
```

The entry point group name. Re-exported so downstream packages can reference it programmatically rather than hard-coding the string.

## Middleware

### `PathSafetyMiddleware`

```python
class PathSafetyMiddleware(Middleware): ...
```

Blocks `..` and NUL bytes in path-shaped arguments. See **[Middleware](../concepts/middleware.md#pathsafetymiddleware)**.

### `ResponseLimitMiddleware`

```python
class ResponseLimitMiddleware(Middleware):
    def __init__(self, max_bytes: int = 256 * 1024): ...
```

Truncates oversized text responses. See **[Middleware](../concepts/middleware.md#responselimitmiddleware)**.

### `validate_tool_annotations`

```python
def validate_tool_annotations(
    mcp: FastMCP, *, strict: bool = True
) -> list[str]
```

Walk every registered tool and check it exposes `readOnlyHint` or `destructiveHint`. Returns a list of warning strings; if `strict=True` and there's any violation, raises `MissingAnnotationsError` instead of returning.

Synchronous; safe to call from any context. `create_server` calls this internally when `validate_annotations=True`.

### `MissingAnnotationsError`

```python
class MissingAnnotationsError(RuntimeError): ...
```

Raised by `validate_tool_annotations(strict=True)` and by `create_server` when validation fails.

## Helpers

### `run_safe`

```python
def run_safe(
    cmd: list[str],
    *,
    cwd: str | Path,
    timeout: float,
    env: dict[str, str] | None = None,
    max_output_bytes: int = 1_000_000,
) -> SubprocessResult
```

Run `cmd` in `cwd` with a hard timeout, capturing bounded output. Enforces:

- `cmd` must be a list of strings — passing a string raises `TypeError`.
- `shell=True` is unreachable.
- A timeout is mandatory.
- `cwd` is validated to exist.
- Output is truncated to `max_output_bytes` per stream.

Raises:

- `TypeError` — if `cmd` is not `list[str]`.
- `FileNotFoundError` — if `cwd` does not exist.
- `subprocess.TimeoutExpired` — if the process exceeds `timeout`.

### `SubprocessResult`

```python
@dataclass(frozen=True)
class SubprocessResult:
    returncode: int
    stdout: str
    stderr: str
    truncated: bool
```

Frozen dataclass returned by `run_safe`. `truncated=True` iff stdout or stderr was clipped at `max_output_bytes`.

### `fence_untrusted`

```python
def fence_untrusted(content: str, label: str = "untrusted file content") -> str
```

Wrap `content` in a marked block:

```text
<!-- BEGIN <label> -->
<content>
<!-- END <label> -->
```

Use when returning raw file contents into the LLM context to flag the data as data, not instruction.

## Read next

- **[CLI reference](cli.md)** — the matching command-line surface
- **[Architecture](../concepts/architecture.md)** — how these pieces fit together
