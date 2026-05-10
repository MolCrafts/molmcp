# Expose a MolCrafts package

Walkthrough: take any MolCrafts package and expose its source via MCP.

## The minimal case

```bash
python -m molmcp
```

That's enough — molmcp auto-detects every installed MolCrafts package and exposes them all through the seven introspection tools. Below we walk through what the agent actually sees, using `molpy` as the running example.

If you want a server scoped to one package only, narrow with `--import-root`:

```bash
python -m molmcp --import-root molpy
```

## The seven tools, by example

### `list_modules`

```python
from molmcp import create_server
import asyncio

server = create_server("molpy", import_roots=["molpy"], discover_entry_points=False)

async def main():
    result = await server.call_tool("list_modules", {})
    print(result.content[0].text)

asyncio.run(main())
```

Output (excerpt):

```json
[
  "molpy",
  "molpy.builder",
  "molpy.compute",
  "molpy.core",
  "molpy.core.atomistic",
  "molpy.core.frame",
  "...",
  "molpy.io.data.lammps",
  "molpy.parser",
  "molpy.typifier"
]
```

The whole package tree, walked once. With `prefix="molpy.core"`, only that subtree.

### `list_symbols`

```python
await server.call_tool("list_symbols", {"symbol": "molpy.core.atomistic"})
# Pass a class instead of a module to discover instance methods, properties, etc.
await server.call_tool("list_symbols", {"symbol": "molpy.core.atomistic.Atomistic"})
```

Output (excerpt):

```json
{
  "Atom": "Atom is an Entity with default fields.",
  "Atomistic": "Struct subclass managing atoms, bonds, angles, dihedrals.",
  "Bond": "Bond connecting two Atoms.",
  ...
}
```

Each value is the first line of the symbol's docstring (or its type name if there's no docstring). Useful as a hub-and-spoke navigation aid: ask `list_symbols` first, then `get_source` on the interesting one.

### `get_source`

```python
await server.call_tool("get_source", {"symbol": "molpy.core.atomistic.Atomistic"})
```

Returns the full source of the `Atomistic` class, including decorators, exactly as `inspect.getsource` would.

`get_source` accepts dotted paths down to methods:

- `"molpy"` — module
- `"molpy.core.atomistic"` — submodule
- `"molpy.core.atomistic.Atomistic"` — class
- `"molpy.core.atomistic.Atomistic.def_atom"` — bound method

### `get_docstring`

```python
await server.call_tool("get_docstring", {"symbol": "molpy.core.atomistic.Atomistic"})
```

Returns the cleaned (dedented, stripped) docstring. If there is none: `"No docstring for: <symbol>"`.

### `get_signature`

```python
await server.call_tool("get_signature", {"symbol": "molpy.parser.parse_molecule"})
```

Output (illustrative):

```
molpy.parser.parse_molecule(smiles: str, /, *, hydrogens: bool = True) -> molpy.core.atomistic.Atomistic
```

### `read_file`

```python
await server.call_tool("read_file", {
    "relative_path": "molpy/core/atomistic.py",
    "start": 1,
    "end": 50,
})
```

Reads a slice of an actual source file. The path is resolved against each import root's parent directory, so `molpy/core/atomistic.py` works because `molpy` is one of the roots.

`..` in the path is rejected. Files outside any import root are rejected. So is reading `/etc/passwd`.

### `search_source`

```python
await server.call_tool("search_source", {
    "query": "class Reacter",
    "module_prefix": "molpy.reacter",
    "max_results": 10,
})
```

Output:

```json
[
  {"file": "molpy/reacter/__init__.py", "line": "42", "text": "class Reacter:"}
]
```

Case-insensitive substring match, with file/line/text dicts. Capped at 50 results regardless of `max_results`. Modified-time-based caching means repeat searches across a session are cheap.

## Multi-package setups

The default already exposes every installed MolCrafts package — `list_modules()` returns the union; `get_source` works for any symbol in any root. Useful when an agent is doing comparative work across the ecosystem — e.g., wiring up a `molexp` experiment that calls into `molpack`.

Pass `--import-root` explicitly only when you need to *narrow* (one package) or *extend beyond MolCrafts* (e.g. add `rdkit` to the introspection set):

```bash
python -m molmcp --import-root molpy --import-root rdkit
```

## When introspection isn't enough

The seven tools tell the agent *what's in the source*. For domain capabilities — "build a polymer in molpy", "pack a box with molpack", "submit a job through molq" — the agent reads the source and runs the upstream API/CLI itself; that's the introspection-first loop molmcp is built around.

A Provider only enters the picture when the question depends on local runtime state introspection genuinely cannot see — a jobs DB, a workspace catalog, an OS-level config. The two first-party providers (`MolqProvider`, `MolexpProvider`) are the canonical examples. Read **[Provider design](../concepts/provider-design.md)** for the four-condition rule, then **[Write a Provider](write-a-provider.md)** for the mechanics.
