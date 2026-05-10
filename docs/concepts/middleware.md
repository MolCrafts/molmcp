# Middleware

molmcp ships three default middlewares. They're all mounted automatically by `create_server(...)`. You can opt out per-middleware via factory parameters.

## Default stack

```
incoming MCP request
        │
        ▼
┌───────────────────────┐
│ PathSafetyMiddleware  │   blocks ../ in path-shaped args
└──────────┬────────────┘
           ▼
┌───────────────────────┐
│ ResponseLimitMiddleware│  truncates oversized text payloads
└──────────┬────────────┘
           ▼
       (provider tool)
           │
           ▼
       response
```

Plus a one-shot validator that runs at server-build time — not a middleware in the request-pipeline sense, but worth knowing about.

## `PathSafetyMiddleware`

**What it does:** rejects tool calls whose path-shaped arguments contain `..` (path traversal) or NUL bytes.

**Which arguments it inspects:** a fixed set of common parameter names — `path`, `filepath`, `file_path`, `filename`, `relative_path`, `rel_path`, `src`, `dst`, `input_file`, `output_file`. Tools using non-standard names are unaffected; if a MolCrafts Provider declares a path arg called `target`, this middleware won't help (use the [`run_safe`](../guides/security.md) helper for subprocess args, or do your own validation, or rename to a recognized key).

**On rejection:** raises `fastmcp.exceptions.ToolError` with a message like `"Refusing path-traversal in argument 'file_path': '../etc/passwd'"`. The MCP client sees a clean error, the tool body never runs.

**Disable:**

```python
create_server(..., enable_path_safety=False)
```

## `ResponseLimitMiddleware`

**What it does:** caps tool responses at a configurable byte limit (default 256 KB). Text content over the limit is truncated and a marker message appended; structured content over the limit is replaced with a placeholder.

**Why:** an unbounded `read_file` or `search_source` call against a large MolCrafts package can dump megabytes of source into the LLM context, blowing past token windows and inflating costs. The truncation marker tells the LLM *and* the user what happened so they can re-call with narrower arguments.

**Configure:**

```python
create_server(..., response_limit_bytes=512 * 1024)  # 512 KB
```

**Disable:**

```python
create_server(..., enable_response_limit=False)
```

The middleware operates on text content only — binary blocks (images, audio) are passed through untouched, since truncating those would corrupt them.

## Annotations validator

**Not a request-time middleware.** It runs once, synchronously, at the end of `create_server(...)`, after every Provider has registered its tools.

**What it does:** walks every registered tool and checks that `ToolAnnotations.readOnlyHint` or `ToolAnnotations.destructiveHint` is set. If any tool is missing both, raises `MissingAnnotationsError` and the server build fails.

**Why so strict:** MCP clients use these hints to decide *auto-approve vs. prompt user*. A read-only tool can be auto-approved; a destructive one must prompt. A tool with no hint forces the client into a defensive choice — usually "prompt every time," which destroys the agent UX. Forcing every MolCrafts Provider to declare intent at build time is the only mechanism that scales across the whole ecosystem.

**Disable (you shouldn't):**

```python
create_server(..., validate_annotations=False)
```

If you're prototyping a new tool and don't want the failure, this is the escape hatch. Don't ship without annotations.

## Why these three?

Each addresses a documented class of MCP-server vulnerability:

| Middleware | Vulnerability class | Source |
|------------|---------------------|--------|
| `PathSafetyMiddleware` | Path traversal — Endor Labs found 82% of audited MCP servers vulnerable | [Endor Labs MCP audit](https://www.endorlabs.com/learn/mcp-servers-security-audit) |
| `ResponseLimitMiddleware` | Token budget exhaustion / cost amplification | [BigData Boutique #2](https://bigdataboutique.com/blog/building-mcp-servers-with-fastmcp-7-mistakes-to-avoid) |
| Annotations validator | Auto-approve confusion → unintended state mutation | [BigData Boutique #1](https://bigdataboutique.com/blog/building-mcp-servers-with-fastmcp-7-mistakes-to-avoid) |

## Adding your own middleware

After `create_server(...)`, you can add any additional middleware your MolCrafts Provider needs:

```python
from molmcp import create_server

server = create_server("molpy", import_roots=["molpy"])
server.add_middleware(MyCustomMiddleware())
server.run()
```

## Read next

- **[Security guide](../guides/security.md)** — how the helpers work alongside the middleware
- **[Provider contract](providers.md)** — the annotation requirement explained
