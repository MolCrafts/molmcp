# Spec INDEX

One line per live spec. Added by `/mol:spec`, pruned by `/mol:impl`.

- [retrieval-first-discovery](retrieval-first-discovery.md) — make capability retrieval the spine; demote the call graph to an optional provenance-labeled evidence feature out of the ranking path [approved]
- [env-auto-discovery-01-discover](env-auto-discovery-01-discover.md) — app-layer environment.py policy module: enumerate a Python env without importing it, identify MolCrafts-family dists (entry-point / keyword / editable / override signals), emit pkg:/local: source specs + diagnostics [approved]
- [env-auto-discovery-02-wire](env-auto-discovery-02-wire.md) — wire discover_sources into the no-molcrafts.json default (workspace + discovered sources), add --env/MOLMCP_ENV locator selection, surface EnvironmentReport diagnostics via molmcp info [approved]
