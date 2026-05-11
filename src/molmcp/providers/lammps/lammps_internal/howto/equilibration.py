"""Equilibration howtos — preparing a system for production runs."""

from __future__ import annotations

from . import Howto

_MIN_THEN_MD_SNIPPET = """\
# Skeleton: minimize, then thermalize, then equilibrate at target P.
minimize 1.0e-4 1.0e-6 1000 10000
reset_timestep 0
velocity all create 300.0 12345 mom yes rot yes dist gaussian
fix eq1 all nvt temp 300.0 300.0 100.0
run 50000
unfix eq1
fix eq2 all npt temp 300.0 300.0 100.0 iso 1.0 1.0 1000.0
run 100000
unfix eq2
"""


HOWTOS: tuple[Howto, ...] = (
    Howto(
        category="equilibration",
        slug="minimize_then_md",
        title="Minimize, then thermalize, then equilibrate",
        rationale=(
            "A typical equilibration starts with energy minimization (to "
            "remove bad contacts), assigns random velocities, runs NVT to "
            "thermalize, then switches to NPT to relax the box at the target "
            "pressure."
        ),
        user_steps=(
            "Step 1: minimize with reasonable tolerances (1e-4 energy, 1e-6 force).",
            "Step 2: reset timestep, assign velocities (`velocity ... create`).",
            "Step 3: NVT for ~50k-100k steps to thermalize.",
            "Step 4: NPT for ~100k-500k steps to relax box at target P.",
            "Verify: temperature, energy, and box dimensions should plateau "
            "before declaring equilibration complete.",
        ),
        snippet=_MIN_THEN_MD_SNIPPET,
        snippet_caveat="Damping constants and run lengths are system-dependent.",
        doc_refs=("minimize", "velocity", "fix_nh"),
        related_commands=(
            ("command", "minimize"),
            ("command", "velocity"),
            ("fix", "nvt"),
            ("fix", "npt"),
        ),
        tags=("equilibration", "minimize", "thermalize", "nvt", "npt"),
    ),
    Howto(
        category="equilibration",
        slug="npt_to_nvt_handoff",
        title="Hand off from NPT to NVT for production",
        rationale=(
            "Many protocols equilibrate the volume under NPT, then run "
            "production under NVT at the equilibrated dimensions. The handoff "
            "must avoid sudden volume change and must release the barostat "
            "cleanly."
        ),
        user_steps=(
            "After NPT equilibration, record the average box dimensions over the "
            "last quarter of the run.",
            "Optionally use `change_box ... final` to set the box exactly to the "
            "average.",
            "`unfix` the NPT fix; install the NVT fix with the same temperature.",
            "Run a short (~20k step) NVT relaxation before production.",
            "If the system is sensitive, repeat NPT→NVT cycles until <Pxx>, <Pyy>, "
            "<Pzz> agree with the target.",
        ),
        doc_refs=("fix_nh", "change_box"),
        related_commands=(("fix", "npt"), ("fix", "nvt"), ("command", "change_box")),
        tags=("equilibration", "npt", "nvt", "handoff"),
    ),
    Howto(
        category="equilibration",
        slug="gradual_thermalization",
        title="Gradual thermalization for fragile systems",
        rationale=(
            "Crystals near melting, glassy systems, and large biomolecules can "
            "shock if velocities are assigned at full target T. Use a gradual "
            "ramp: low T → high T over many steps, optionally with stronger "
            "thermostat coupling at the start."
        ),
        user_steps=(
            "Assign velocities at a low T (e.g. 1 K).",
            "Run NVT with `temp` ramp: `fix th all nvt temp 1.0 ${T_target} ${tau}`.",
            "Use a small damping constant (~10*timestep) initially; relax it "
            "as the system warms.",
            "Once at target T, run a short equal-T NVT before NPT.",
        ),
        doc_refs=("fix_nh", "fix_langevin", "velocity"),
        related_commands=(("fix", "nvt"), ("fix", "langevin")),
        tags=("equilibration", "thermalize", "ramp", "fragile"),
    ),
)
