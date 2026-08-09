# Open questions

- No type checker is configured (no `ty`/`mypy` in dev deps or CI).
  Intentional, or should `check` grow a type-check step?
- No coverage tooling (`pytest-cov` absent), so `mol_project.build.coverage`
  is unset. Add if coverage gating is wanted.
