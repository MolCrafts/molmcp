# Harness catalog

Two different things in MolCrafts are shipped by two different mechanisms, and
the whole point of this page is that they do not touch.

The first is **molmcp itself**: a Python distribution on PyPI that speaks the
**Model Context Protocol** (MCP) — the wire protocol an AI client such as
Claude Code or Cursor uses to call tools on a server. Its unit of shipping is a
release. Its registry is a **Python entry point**: a line in a package's
`pyproject.toml` that says "when something looks for the `molmcp.providers`
group, hand it this class." That is how a *provider* — one product's MCP
surface, served as its own *plane* (`molvis`, `molq`, `molexp`) — becomes
visible to `molmcp serve`. [Providers](providers.md) covers that path.

The second is a **harness**: the pile of agent tooling a person or a team
actually works with — instruction files, agent definitions, rules, and
occasionally a plane or a knowledge overlay of their own. A harness is not a
release. It changes several times a week, it belongs to whoever wrote it, and
the interesting question about it is never "which version" but "which exact
commit was I running when that went well?"

That question is what this page answers.

## Identity is a Git SHA

A **Git SHA** is the 40-character lowercase hexadecimal fingerprint Git gives
every commit — `9f1c3b2a7d4e0165c8a9b3d27e5f10486c73ab92`. It is computed from
the commit's content, so it names exactly one tree of files and can never be
made to name a different one. Branch names and tags can: `main` meant something
else last Tuesday, and a tag can be moved.

A harness is therefore identified by a SHA and by nothing else. There is no
harness version number, no `latest`, and no semantic-versioning range. The
loader enforces this: `molmcp.components.SHA_PATTERN` is `^[0-9a-f]{40}$`, and
`HarnessCatalog` refuses to be constructed with an abbreviated SHA, an
uppercase one, or a branch name.

The SHA is **not written in the catalog file**. It is passed in by the caller
that already knows which commit it unpacked:

```python
load_harness_catalog(tree_root, sha, supported_capabilities)
```

A file that stated its own SHA could disagree with the tree it sits in — a copy
edited by hand, a rebase, a bad merge — and there would be no way to tell which
of the two was lying. Keeping identity outside the file makes that
disagreement unrepresentable.

Which SHA an install is running is recorded in an **activation pointer**: a
small JSON file naming three SHAs — `current` (in effect), `staged` (accepted,
waiting), and `previous` (what a rollback would restore).
`molmcp.components.Activation` is the only thing that moves one, and serving
only ever *reads* them.

There is one such file per **harness source** — one repository this install has
been told it may take a harness from, named in its settings file and described
under [Where a harness comes from](#where-a-harness-comes-from) below. A source
named `official` owns `harness.official.pointer`; a source named `private` owns
`harness.private.pointer` beside it. Both sit in the directory the `cacheDir`
setting names, next to one shared store — `cacheDir/harness` — which is where
the unpacked commit trees themselves live, whichever source activated them. So
each source is activated, and rolled back, on its own, and "which SHA is this
install running?" has one answer per source rather than a single answer for the
install.

## `official`, `gate`, `canary` are labels on a SHA

Once identity is a SHA, everything else people want to say about a harness is a
note kept beside one:

| Label | What it asserts about that SHA |
|-------|--------------------------------|
| `official` | The commit MolCrafts publishes as the default. It is the one the required pull-request check passed on. |
| `gate` | A commit currently under evaluation — accepted for staging, not yet promoted to `current` anywhere but the machine testing it. |
| `canary` | A commit a small number of installs run ahead of everyone else, on purpose, to find out what it breaks. |

Three properties of these words matter more than their definitions.

**They are not settings.** `molmcp config set …` has no key for them, and it is
not going to get one. A setting would let two installs disagree about which SHA
is `official` while both believe they are correct; the label belongs to the
commit, not to the reader.

**They are not environment variables.** molmcp reads no `MOLMCP_*` variable for
anything, and `tests/test_no_env_switches.py` fails the build if a module
starts reading one. Configuration that lives in a single shell cannot be
reported by `molmcp config list`, and two plane servers launched by two clients
would silently disagree about it.

**They are not keys in the catalog file.** The grammar in
`molmcp.components.catalog` rejects any key it does not recognise, so adding
`label = "official"` to `harness.toml` does not add a label — it stops the file
loading. A label is metadata *about* a commit and a catalog is the contents
*of* one; the loader never sees the label at all.

No module in `src/` looks any of these three up. They exist so that humans and
CI jobs describing the same commit reach for the same word.

## Two registries, and they are disjoint

This is the sentence most likely to be undone by a well-meaning future change,
so here it is with its reasons.

| | MCP planes | Harness plugins |
|---|---|---|
| Authoritative list | the `molmcp.providers` entry-point group | one commit's `harness.toml` |
| Unit | an installed Python distribution | a Git SHA |
| Changes when | somebody releases to PyPI | somebody pushes a commit |
| Discovered by | `importlib.metadata` entry points | reading each activated commit's tree |

Concretely: none of the following three exists today, and none of them may be
added later without abandoning the split above.

- **There is no `harness` plane id.** Plane ids are product names (`molcrafts`,
  `molvis`, `molq`, `molexp`). "Harness" is a distribution mechanism, not a
  product with tools.
- **There is no `molmcp serve harness`.** `molmcp serve` starts the composed
  stack; `molmcp serve <plane>` starts one plane for debugging. Neither takes
  `harness`, because there is nothing to serve under that name.
- **There is no `molmcp.providers` entry point for a harness.** A harness is
  not installed with pip, so it has no `pyproject.toml` for molmcp to read, so
  there is nothing for an entry point to point at.

A harness *may* contribute a plane — that is what a `provider` component is —
but the plane is named by the component's own `name`, and it is mounted for
this process out of the activated tree that declared it. It never becomes an
entry point, and
the catalog id (`provider.bench`) is not the plane id (`bench`); mounting under
the id would namespace its tools as `provider.bench_open`.

The reason to keep the two lists apart is that they fail differently. An
entry-point plane that breaks was shipped to everyone by a release you can
yank. A harness plane that breaks was a commit one person pushed an hour ago,
and the fix is to move a pointer back. Merging the registries would mean one
recovery procedure for two unrelated failures.

## What a catalog file says

A **catalog** is the inventory of one commit: the list of pieces that commit
offers. The tree is never globbed — a file nobody declared in the catalog is
not a component, which is what keeps a stray editor backup out of an agent's
instruction set.

A catalog holds two kinds of row, and confusingly both are written as
`[[component]]`. The first kind is a component.

A **component** is one installable piece. There are five kinds of component,
and each one reserves a directory:

| `kind` | What it is | `path` must start with | `entrypoint` |
|--------|------------|------------------------|--------------|
| `skill` | Instruction file an agent reads | `skills/` | must be absent |
| `agent` | Definition of one specialised worker | `agents/` | must be absent |
| `rule` | A constraint that holds across tasks | `rules/` | must be absent |
| `provider` | An MCP plane this commit contributes | `providers/` | **required** |
| `overlay` | Domain knowledge layered onto the code graph | `overlays/` | **required** |

An **entrypoint** is a `module:object` string such as
`bench_provider:BenchProvider`. The loader stores it and never imports it —
reading a catalog must not be able to run someone's code.

The second kind of row is a bundle. A **bundle** is a named group of component
ids, written as a row whose `kind` is the literal string `"bundle"` — which is
why `ComponentKind("bundle")` raises. It is not a sixth component kind, and a
bundle may not contain another bundle. Bundle names are the author's; a
catalog may define none, in which case every component is one implicit
package. `sci` and `dev` are ordinary names, not reserved slots.

The keys, in full — there are no others, and an unknown one is an error rather
than an ignored line:

| Where | Keys |
|-------|------|
| top level | `requires` |
| a component row | `kind`, `name`, `path`, `entrypoint` |
| a bundle row | `kind`, `name`, `members`, `requires` |
| derived, never written | `id` — always `"<kind>.<name>"` |

`requires` lists **capability tokens**: machinery a piece needs from whatever
process loads it. Two exist today, `provider-sdk` and `harness-catalog`. They
are checked twice, and the two checks are not the same thing. The *language
gate* asks whether the token is even spellable (`ALLOWED_REQUIRES`); an unknown
token is a malformed file. *Eligibility* asks whether this particular process
can honour a spellable token; a token this build does not implement is a
refusal to load, not a malformed file. Keeping them apart is what lets a future
token be added to the grammar without every existing install claiming to
support it.

## The example file and the file that is read

This repository publishes exactly one catalog, and it is not a live one:

| | Published here | Read at run time |
|---|---|---|
| Name | `harness.example.toml` | `harness.toml` |
| Location | `docs/concepts/` | the root of one published commit tree, under `cacheDir` |
| Who reads it | a person, and one test | `Activation.stage` and `create_stack` |

[`harness.example.toml`](harness.example.toml) is documentation. It is under
`docs/` and never at the repository root, and `tests/test_harness_catalog_fixture.py`
loads it through the real `molmcp.components.load_harness_catalog` so that the
example cannot quietly drift away from the grammar it is illustrating.

**`harness.toml` is never auto-loaded from the working directory.** The
filename is joined onto a root the caller passes —
`Path(root) / "harness.toml"` in `molmcp/components/catalog.py`, the one place
in `src/` where that name is resolved at all. The only roots molmcp itself ever
passes are the trees of the commits its activation pointers name — one root per
activated source, read in the order the settings file names them. `molmcp serve`
does not look beside itself for a catalog, and neither does `molmcp init`.

This is the same rule the rest of molmcp follows for `molcrafts.json` and for
the workspace source: a tool that picks up whatever file happens to be next to
the directory you started it in behaves differently for two people running the
same command.

## Where a harness comes from

An install names the repositories it may take a harness from in its settings
file, under the key `harness`. The value is an **ordered list of named
sources** rather than a single repository, because one person's tooling is
routinely several: the one MolCrafts publishes, one a team keeps privately, one
that belongs to a particular project.

```json
{
  "harness": [
    {"name": "official", "locator": "MolCrafts/harness"}
  ]
}
```

That is a complete `~/.molmcp/settings.json` — the install-wide settings file
described under [Installation](../get-started/installation.md#settings) — with
one source named in it.

An entry has four keys and no others. `name` is a label you choose; it is how
you refer to the entry, and it is the one key an entry may not leave out.
`owner` and `repo` are the two halves of a GitHub repository path, kept as
separate keys instead of a single `owner/repo` string so that nothing on this
path has to parse one. `ref` is the branch or tag a commit is *resolved from* —
it is not the commit being served, which is the one that entry's own activation
pointer names.

The three coordinates may be left out while an entry is still being written. An
entry carrying only a `name` loads and is stored exactly as written; what it
cannot do is serve. At serve time an entry that sets some coordinates but not
all of them — setting none of them included — is a configuration error naming
the entry and each field it is missing, rather than a guess. Filling one in
from a default would mean fetching code from a repository nobody asked for.

**Order is file order, and it is a contract rather than an accident.** Entries
are read first to last as the file writes them, and the first entry that offers
something is the one that answers for it. That is not a promise about some
later release: it is how a piece two sources both ship is settled today, and
[What serving does with the list](#what-serving-does-with-the-list) below is
the whole of the rule. Writing the order down as a contract is what keeps the
answer from coming to depend on the order some dictionary happened to iterate
in.

**Across settings files, the most specific list replaces the others; it does
not merge.** A project's `.molmcp/settings.json` outranks the user file and
`.molmcp/settings.local.json` outranks both, and the winner's list is the whole
list. That is worth saying out loud, because it is the *opposite* of `excludes`,
`knowledgeScope`, `discoverInclude` and `discoverExclude`, which accumulate
across those same three files. The asymmetry is deliberate: appending a
first-wins list would put the user file's entries at the front and so let the
least specific file outrank the most specific one, which is the inverse of what
every other setting does.

**There is no built-in default source.** molmcp ships no coordinates for
`MolCrafts/harness` or for anything else, and the entry in the snippet above is
not a fallback that was already there — it is an operator naming a source, the
same act as naming any other. All sources are peers. `official` there is simply
the name chosen for one of them, and the page could as readily have called it
`mine`; the word does mean something, but as a label on a commit, per the table
earlier on this page, and never as a privilege of an entry. (That repository is
also still being stood up: naming a source configures an address, and until the
commit at the far end of it carries a `harness.toml`, there is nothing there to
load.)

An install whose `harness` key is absent, or is an empty list, simply has no
harness, and serves exactly as it did before any of this existed. That is a
normal configuration, not a degraded one.

### What serving does with the list

`molmcp serve` reads the list whole and gives every entry its own turn. A source
that has nothing to contribute costs its neighbours nothing.

**Each source is activated on its own.** For every entry, in file order, serving
reads that entry's activation pointer — `harness.<name>.pointer` under
`cacheDir`, the per-source file introduced [near the top of this
page](#identity-is-a-git-sha) — and serves the commit its `current` names. A
source whose pointer file does not exist yet, or whose pointer activates
nothing, contributes nothing and is **skipped**; the entries around it still
serve. Nothing is fetched and no pointer is written while serving, because
moving a pointer belongs to the commands that were asked to change what is
activated. The one thing that is *not* shrugged off is a pointer naming a
commit whose tree was never unpacked into the store: that stops the serve with
a message naming the source, the SHA and the pointer file, rather than
re-fetching something nobody asked for at start-up.

**One store, shared by every source.** The unpacked trees all live in the single
`cacheDir/harness` directory; only the pointers multiply. That is a correctness
rule and not a disk-space saving. The store keeps each tree under its SHA alone
and records beside it which repository published that SHA, so a SHA a second
repository lays claim to is refused rather than quietly overwritten: two
repositories cannot both own one commit in one store. Give each source a store
root of its own instead and every tree already published becomes unreachable to
the next source that could have shared it.

**Two entries may not share a name, compared without regard to case.**
`official` and `Official` look like two entries to a person, but on macOS and
Windows they name one `harness.official.pointer` file, so the second would
silently serve whatever the first activated. Serving stops with a message
naming both spellings. For the same reason a name that cannot be a filename —
one holding a `/` or a `\`, or one shaped like an absolute path — is refused,
naming the entry. Nothing else about a name is prescribed: it is yours to
choose, exactly as an index source's name is.

**A component two sources both declare is kept once, and the earlier entry
keeps it.** Every activated commit's catalog is read, the components of the kind
being served are collected in source order, and the first source to claim a
given component id — `provider.bench`, `overlay.molpy` — is the one that keeps
it. That collecting-with-a-winner step is a **fold**: several lists become one,
and the rule for a contested key is fixed in advance rather than settled by
whichever list happened to be read last. The displaced declaration is not
served, and it is not silently dropped either: molmcp logs a warning naming the
winning source, the losing source and the contested id, so an operator who did
not intend the overlap learns it from the log rather than from behaviour they
cannot account for. Reordering the list, or dropping the component from one of
the two catalogs, is the whole of the fix — file order is the only priority
control there is, and there is no per-source override.

For a `provider` component that rule is doing more than tidying up. A component
id is `provider.<name>` and the plane is mounted under the `<name>` half, so two
sources both shipping `provider.demo` are two planes claiming one namespace, and
one of them would be mounted over the other. Keeping the id once is what stops
the pair from mounting twice.

Bundles are **not** folded across sources. A bundle is a group of ids inside one
catalog, every catalog carries its own `daily` and `dev`, and nothing on the
serving path reads one — what gets served is selected by component kind. Three
activated sources are three catalogs each with its own `daily`, not one merged
`daily`.

**A pointer file left over from before sources were activated by name is named,
never read.** Such an install has a single `harness.pointer` under `cacheDir`
with no source name in it. molmcp does not read it, and does not migrate it:
when that file is present and no named source has a pointer of its own, molmcp
logs one warning naming the file and serves with no harness at all.
Migration would be machinery for a population that is very nearly empty —
molmcp has no verb that activates a commit yet, so nothing in the product ever
wrote that file, and it can only exist where someone wrote it by hand. Deleting
it, and activating the sources you want under their own names, is the whole
recovery.

### Authoring an entry, and what to do if you mistype one

One verb writes the list, and it addresses one origin at a time with a locator:

```bash
molmcp config harness set MolCrafts/harness --alias official
molmcp config harness set MolCrafts/harness --alias official --enable sci --disable all
molmcp config harness set ~/src/harness --alias local
molmcp config harness remove official
```

The locator is a GitHub `owner/repo[@ref]`, a GitHub URL, or a `~/` / absolute
path. `--alias` names the entry (default `origin` on first insert). `--enable`
and `--disable` select catalog bundles on that source; they are not plane
toggles. `molmcp init <host> --enable/--disable` still only mounts provider
planes. A locator already in the list is updated in place; a new origin is
appended **last**. Both subcommands take the same `--project` and `--local`
scope flags as every other `config` write, and with neither they write the
user file.

They exist because the ordinary write verbs cannot reach this key. `harness` is
a list whose elements are objects, while `config set` and `config add` each take
one string, so both refuse the key outright and answer with the shape of an
entry and the verb that authors one. Reading is unchanged: `molmcp config list`
and `molmcp config get harness` each print the list whole. There is no dotted
path into an individual entry — a dotted read into this key addresses nothing,
and it exits 2 saying so rather than answering `null`, which would have claimed
a coordinate was merely unset.

Two things this verb deliberately does not do, and you will meet both.

**A locator that cannot be parsed is refused at set time.** Relative paths,
`http://`, and the `github:` prefix are errors. A GitHub origin without a
reachable checkout is complete enough to store; whether it can fetch is
decided at `harness sync` / `serve`.

**It cannot repair a settings file that no longer loads.** A settings file is
validated on every *read*, and this verb reads the file before it writes it,
exactly like every other one. An old entry still carrying `owner` / `repo` /
`path` keys is a hard cut: re-run `molmcp config harness set <locator>`.
`molmcp config list`, `get`, `set`, `add`, `remove` and `harness`, and
`molmcp serve` itself, all stop with exit status 2 until it is corrected, and
the message names the file and the entry by position, as `harness[0].onwer`.
**The repair is to open that file in an editor.** Nothing is lost and nothing
needs reinstalling — the file is plain JSON and the fix is a text edit.

## Two repositories, and the older one is leaving

`MolCrafts/molcrafts-harness` is the **plugin marketplace** MolCrafts used
before this design — a "marketplace" being a repository an agent host is told
about once, from which it then installs plugins by name. It is on its way out.
Nothing in this documentation set offers its URL as a current install address,
and nothing should: an install line for a repository that is being retired is a
promise the maintainers are about to break.

`MolCrafts/harness` is its replacement in role only. **It is a new, empty
repository — not `molcrafts-harness` renamed.** That distinction is the whole
decision, so it is worth being blunt about why a rename was rejected:

- A rename carries the old history, and with it the old marketplace layout, the
  old plugin manifests, and every stale install instruction anyone ever wrote
  down. The new repository's contract is a `harness.toml` at the root of every
  commit. Starting from an empty tree makes the first commit that satisfies
  that contract also the first commit that exists.
- A rename leaves a redirect. GitHub forwards the old path, so a host still
  configured against `molcrafts-harness` keeps working and nobody finds out
  they are on the old address until the redirect is removed.
- A rename carries the old licence into the new repository by default, which is
  a licensing decision made by accident. See the table below.

The new repository holds **agent tooling only**: skills, agents, rules, and the
occasional provider or overlay. It is not a monorepo. molq, molexp, molvis and
molpy stay in their own repositories, and moving one into the harness would
make a commit of the harness mean "some agent instructions changed *and* a
science package changed", which is exactly the coupling the SHA-identity model
exists to avoid.

The old repository is retired only **after** cutover, and retiring it is a
deliberate, separately authorised act. The runbook is
[Retiring the old harness marketplace](../guides/harness-migration.md).

## Licences

Three repositories, three separate grants. This table describes them; it does
not change any of them.

| Repository | Licence | What this page may change |
|------------|---------|---------------------------|
| `MolCrafts/molmcp` — this repository | **BSD-3-Clause**, in [`LICENSE`](https://github.com/MolCrafts/molmcp/blob/master/LICENSE) at the repository root | Nothing. That file is the grant; this row is a description of it. molmcp is not being relicensed. |
| `MolCrafts/molcrafts-harness` — the old marketplace | MIT | Nothing. It keeps the grant it shipped under for as long as it exists. |
| `MolCrafts/harness` — the new catalog repository | Not yet granted; it does not exist yet | Nothing. Its licence is chosen when the repository first exists. |

Two things follow that are easy to get wrong.

**A licence is granted once, in the repository it applies to.** Copying
BSD-3-Clause text into `MolCrafts/harness` because molmcp uses it would be a
licensing decision taken as a formatting step. If the new repository ends up
BSD-3-Clause, that must be because someone chose it.

**A harness commit is not molmcp.** A user's own harness carries whatever
licence its author chose, or none. molmcp loads it; molmcp does not
sub-license it, and nothing in the catalog format asserts anything about the
rights in the tree it describes.

## Two shapes that were considered and refused

**A `WikiSkill` as an `init` channel.** `molmcp init <host>` installs one
managed instruction file — the usage skill in `src/molmcp/skill/SKILL.md` — and
one MCP entry. A proposal to add a second, wiki-shaped skill installed the same
way was rejected. A skill that wraps `packages`, `molvis_open`, `molq_*` or
`molexp_*` in prose is a second copy of the truth about those tools: upstream
renames a tool and the wiki keeps confidently describing the old one. The same
objection retires the chain-of-thought wrapper variant, where the skill narrates
reasoning steps around a call the client can already make directly.
`molmcp init` has exactly one skill channel, and the catalog's `skill`
components are materialised from a checkout, not installed as a second managed
file.

**A harness plane.** Rehearsed above: no plane id, no `molmcp serve harness`,
no entry point. A harness is where tools come from, not a tool.

## Read next

- [Iterate on a harness from a checkout](../guides/iterate-on-a-harness.md) — the three-command loop, starting from a repository on your own disk
- [Retiring the old harness marketplace](../guides/harness-migration.md) — the exit runbook
- [Providers](providers.md) — the other registry, the entry-point one
- [Provider design](provider-design.md) — what earns a tool slot on any plane
- [Installation](../get-started/installation.md#settings) — the settings files the `harness` list is written in, and the other keys beside it
