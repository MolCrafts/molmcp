"""Rerun howtos — analyse a saved trajectory without re-running dynamics."""

from __future__ import annotations

from . import Howto

HOWTOS: tuple[Howto, ...] = (
    Howto(
        category="rerun",
        slug="analyze_trajectory",
        title="Analyse a trajectory via the rerun command",
        rationale=(
            "`rerun` re-evaluates a saved dump file: it reads frames, "
            "rebuilds neighbour lists, recomputes forces / energies / fixes / "
            "computes you declare. Useful for adding analysis after the fact "
            "without redoing dynamics."
        ),
        user_steps=(
            "Build a script with the same units / atom_style / pair_style / "
            "force-field as the original run.",
            "Skip the `velocity` / `fix nvt` / `run` parts; replace with "
            "`rerun dump.lammpstrj dump x y z`.",
            "Add the new computes / fixes you want, e.g. compute rdf, "
            "compute msd, fix ave/time.",
            "Output via thermo or dump as in a normal run.",
            "Verify: rerun's logged total energy should match the original "
            "run's logged energy at each frame.",
        ),
        doc_refs=("rerun", "read_dump"),
        related_commands=(("command", "rerun"), ("command", "read_dump")),
        tags=("rerun", "trajectory", "post-hoc", "analysis"),
    ),
    Howto(
        category="rerun",
        slug="recompute_quantities",
        title="Recompute thermodynamic quantities from a trajectory",
        rationale=(
            "When a production run forgot to log something (per-atom stresses, "
            "RDF, MSD, custom thermo), rerun recovers it without redoing MD."
        ),
        user_steps=(
            "Confirm the dump file contains what you need (id type x y z, plus "
            "any extra fields).",
            "If forces are missing in the dump, rerun re-evaluates them from "
            "x,y,z plus the force-field — make sure the FF matches.",
            "Use `rerun dump.lammpstrj first 0 last 1000 every 10 dump x y z` "
            "to subsample.",
            "Note: per-step quantities depend on the force field being a pure "
            "function of x,y,z (no history). Anything depending on velocities "
            "(KE, T) requires `dump ... vx vy vz` in the original run.",
        ),
        doc_refs=("rerun", "thermo_style"),
        related_commands=(("command", "rerun"),),
        tags=("rerun", "post-hoc", "recompute"),
    ),
)
