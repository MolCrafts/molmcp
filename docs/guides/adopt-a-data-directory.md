# Adopt a data directory

You have a folder of results — whatever shape it grew into over a year of
running simulations. molexp wants it as `Workspace → Project → Experiment →
Run`. Four tools on the `molexp` plane get it there without you writing a
migration script, and without either of us guessing about your bytes.

```
plan_adoption   →  read-only survey + proposed mapping
run_adoption    →  materialize · transfer (SHA-256) · ingest · verify
adoption_status →  what the ledger says, optionally re-hashed
ingest_metrics  →  logs → metrics buffer, standalone
```

## 1. Look before you move

```
plan_adoption(source="~/results/2026-electrolyte")
```

Nothing is written. You get back two things.

The **survey**: how many run / experiment / project candidates the walk found,
total bytes, which directories were excluded (`.git`, `.venv`, `__pycache__`,
…), and the oddities that a migration usually discovers too late — zero-byte
files, broken symlinks, symlinks pointing *out* of the tree, directories below
the depth limit.

The **plan**: the proposed mapping. A directory holding run-shaped files is a
run; a directory whose every child is a run is an experiment; a directory whose
every child is an experiment is a project. Anything else is loose, and loose
files are listed under `skipped` rather than swept in.

Two things deserve a look before you go on:

- `plan.conflicts` — two source names that slugify to the same id. A non-empty
  list blocks `run_adoption`; edit the plan and hand it back.
- `plan.skipped` — every file that will *not* move, with its reason. If
  something important is in there, the mapping is wrong, not the file.

The plan is a plain dict. Edit it — rename a project, move a run under a
different experiment, drop one entirely — and pass it as `plan=` in step 2.
What you approved is what runs; nothing is re-derived behind you.

## 2. Move the bytes

```
run_adoption(source="~/results/2026-electrolyte", plan=<edited>, mode="copy")
```

Every file is streamed, hashed while it is written to a `.partial` sibling,
renamed into place, then **re-read and compared**. There is no `skip_verify`
option; a copy nobody proved is not a copy. Files land under
`<run>/artifacts/`, so nothing you brought can collide with the run's own
`run.json`.

`mode="copy"` leaves your source completely untouched. `mode="move"` is
implemented as *copy → verify → unlink*, per file — never `os.rename` — so an
interrupted move leaves the source partially intact and the ledger says
exactly which files were already unlinked.

A destination that already exists is **never overwritten**. If its hash
matches, the copy is reused (that is how resume works). If it differs, the
transfer stops and tells you to move the file aside yourself.

### Resume

`<target>/.molexp-migration.json` is the journal, and the only source of truth
for what is done. Re-run the same call after a crash and it picks up where it
stopped. A journal that disagrees with the current invocation about source,
target, or mode is a hard stop, not a silent re-plan.

## 3. Make the logs legible

Organised is not the same as readable. A folder of `log.lammps` and
`events.out.tfevents.*` is in the right place with its curves still locked in
per-engine text.

```
run_adoption(..., ingest=["lammps_log", "tensorboard"])
```

Omit `ingest` and nothing is converted — `metrics/metrics.jsonl` is
append-only, so ingestion is never implied by silence. The converters are
molexp's own (`molexp.plugins.metrics_ingest`): LAMMPS thermo through molpy's
log reader, tfevents through molexp's TensorBoard plugin, CSV through stdlib
with a column mapping you supply. A format with no converter — `wandb/`,
`mlruns/`, an unrecognised dump — is transferred as a plain artifact and
reported as not ingested. It is never approximated.

CSV needs `csv_step_column` and `csv_series_columns`. Without them CSV files
are skipped with a reason, because a table of coordinates and a table of
training curves look identical to a heuristic.

Ingestion is additive: your log is never deleted, rewritten, moved, or
truncated. An unwanted ingest is undone by removing `<run>/metrics/`. A
failed ingest never fails the adoption — the bytes are already safe — and it
is not retried automatically, because the buffer is append-only. Fix the cause
and call `ingest_metrics` on that run.

## 4. Audit, then decide about the original

```
adoption_status(target="~/results/2026-electrolyte.molexp", verify=true)
```

`verify=true` re-hashes every transferred file against the ledger. It is off
by default because it re-reads the whole workspace; turn it on for the one
audit that matters.

**There is no delete-the-source tool.** Every other step here is provable and
resumable. Removing your original data is neither, so it stays a decision you
make yourself, with the ledger in front of you.

## Already have a workspace?

`ingest_metrics` works standalone. Point it at a run directory, or at a
workspace root to fan out over every run beneath it:

```
ingest_metrics(path="~/results/2026-electrolyte.molexp")
```
