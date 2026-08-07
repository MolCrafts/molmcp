# MolVis workbench

You're driving a molecular viewer through a conversation: the user says "make me an aspirin", sees the 3D structure appear in a browser, clicks part of it, and says "change this". This page teaches the **loop** that makes that work — open a session, execute Python inside it, pull the events the browser sends back.

It deliberately documents **no** molvis or molpy method. Every API you call inside `exec` belongs to those packages, and the truth about it lives in their docstrings, one `search` away on the molcrafts plane. Read [Provider design](../concepts/provider-design.md) for why the tool surface is only these few primitives.

## One session, two surfaces, two wills

A viewer session is one live molvis `Stage` — the Python object that controls one viewer — held inside the running `molmcp serve` process, together with a Python namespace bound to it. Four parties share it. The **human** watches and clicks. The **canvas** is the browser page molvis renders: it projects the structure and streams interaction events back. The **code surface** is that in-process namespace, holding `mol` (a molpy structure — the single source of truth) and `stage` (the controller that projects it). The **agent** — you — holds only the MCP primitives and never touches the canvas directly.

Two wills act on one session and neither blocks the other. The human's "change *that* bit" reaches you as an event you poll for; your "apply what we agreed" reaches them as the next redraw. They meet in session state, nowhere else.

## The loop

Connect the **molvis** plane (`molmcp serve molvis`). Tool ids are
`molvis__open`, `molvis__exec`, … (server name + bare tool).

`open` → `exec` (build and draw) → the human looks and clicks → `poll_events` → `exec` (read the selection, edit, redraw) → `close`.

Step one, once `open` has returned and the user has the viewer open in a browser: build the molecule and put it on the canvas. `stage` is already bound in the namespace; nothing else is imported for you.

```python
import molpy as mp
mol = mp.parser.parse_molecule("CC(=O)Oc1ccccc1C(=O)O")   # SMILES string for aspirin
mol, _ = mp.Conformer(seed=42).generate(mol)              # connectivity → 3D coordinates
stage.draw_frame(mol)
```

SMILES — Simplified Molecular-Input Line-Entry System — is a molecule written as a single line of text; parsing it yields connectivity without coordinates, which is why a conformer generator runs before anything can be drawn in 3D.

The user now clicks part of the structure, and `poll_events` hands you a `selection_changed` record. Step two reads that selection back, edits the structure, and redraws. Note what is *not* in the code: no rebuild of `mol`, because the namespace persisted.

```python
sel = stage.get_selected()             # standalone sub-Frame, with its own elements + coordinates
# … edit mol with molpy …
stage.clear(); stage.draw_frame(mol)   # refresh = clear first, then draw
```

That is the whole pattern. Longer work is more turns of the same wheel, never a bigger tool: the molvis plane will not grow a `show_smiles` or a `replace_group`, because the vocabulary for those lives upstream and you already have a channel to it. Use the **molcrafts** plane to discover APIs; never invent MCP science tools.

## Three facts the loop depends on

Each of these is a contract you must respect, and each has exactly one authoritative source — a docstring you can pull into context with `molcrafts_search("<name>")` followed by `molcrafts_open(<ref>)`. Read them; do not take this page's word for them.

- **`draw_frame` has stamp semantics** — it places a structure onto the canvas and never wipes what is already there, so a refresh is `clear()` and *then* `draw_frame(...)` (molvis drawing mixin docstring; `clear` is the only full wipe).
- **`get_selected` returns a standalone sub-Frame** — a molpy `Frame`, meaning a table of atoms with their own elements and coordinates and bonds renumbered into the subset, not a list of indices into your `mol` (molvis selection mixin docstring).
- **The namespace persists across `exec` calls until `close`** — every binding you make, `mol` included, is still there on the next `exec` and is released only by `close` (molmcp's own contract, on the `exec` tool docstring).

## Connection etiquette

`open` returns a `connection_url`, and the viewer does not exist until a human opens that URL in a browser. Put the link in your reply and wait to be told the canvas is up.

Before your first drawing call, check `stage.connected` inside `exec`. Drawing into a viewer nobody has opened waits for a frontend response that never comes and fails only on timeout — ten silent seconds spent on a question you could have answered in one line. Guarding turns that into an immediate, explainable answer: *open the link, then tell me when you can see the canvas.*

The same reflex applies after any long pause: the user may have closed the tab. `list_sessions` tells you which sessions exist; `stage.connected` tells you whether anyone is looking.

## Asking the stage what it can do

Call `capabilities` instead of probing with `dir(stage)` and `inspect.signature` inside `exec`. It reads the surface off the live object, so it cannot disagree with the installed molvis, and it answers the question a signature alone does not: `kind` tells you whether to *call* a name or *read* it. Calling a property is a routine and thoroughly confusing mistake — `stage.n_frames()` when `n_frames` is a property fails with `'int' object is not callable`, which names neither the attribute nor the real problem. Pass `pattern` to narrow the list (`"draw"`, `"frame"`, `"select"`).

## After the user edits a package

`refresh` drops edited packages from the server's module cache so your next `exec` imports the current source. Two things it will not do, both of which have bitten before:

**It cannot reload a compiled extension.** `molrs` is mapped into the process once and stays until the server restarts. When `restart_required` comes back true, stop and ask for a reconnect — running the test anyway means reporting a verdict on code that never executed. The same field is on every `capabilities` reply, so you can check it without refreshing anything.

**It does not migrate live objects.** `stage`, `mol`, everything an earlier `exec` bound, keeps pointing at the classes it was built from. Rebuild them after refreshing, or open a new session — otherwise the session straddles two versions of the same package and the results are nobody's.

## Where the end-to-end playbook lives

The full aspirin rehearsal — start the server, open, build, look, click, poll, edit, redraw, close, with a real browser and a real human in the middle — is an **out-of-tree** harness. It belongs in a sibling directory next to your molmcp checkout (`molvis-agent-e2e/`), never under the `molmcp/` or `molvis/` product trees, and specifically not in either project's `examples/` or `tests/`.

The reason is honesty about what the thing is. An interactive dialogue script that needs a person to click a benzene ring is neither a runnable product example nor a CI test, and filing it as one advertises a guarantee no maintainer can keep. In-tree tests pin the workbench mechanics only: session lifecycle, namespace persistence, journal ordering under concurrent writes, and one round trip against real molvis over its in-process transport, no browser involved.

## Read next

- **[Provider design](../concepts/provider-design.md)** — the primitives, the no-invented-API rule, and the local trust model
- **[Discovery engine](../concepts/discovery.md)** — where every API in the loop above is actually documented
- **[Write a Provider](write-a-provider.md)** — the four-condition rule for adding tools of your own
