# Open questions

Recorded during `/mol:bootstrap` (2026-06-10). Resolve and prune over time.

- No type checker is configured (no `ty`/`mypy` in dev deps or CI).
  Intentional, or should `check` grow a type-check step?
- `ruff format --check` is not part of CI — formatting is unenforced.
  Adopt it (and add to both CI and `.pre-commit-config.yaml`)?
- No coverage tooling (`pytest-cov` absent), so `mol_project.build.coverage`
  is unset. Add if coverage gating is wanted.
