"""Mechanics howtos — stress, strain, elastic constants, deformation."""

from __future__ import annotations

from . import Howto

_ELASTIC_SNIPPET = """\
# Skeleton — see Howto_elastic.html and examples/ELASTIC for the full protocol.
variable strain equal 0.001
fix avg all ave/time 100 5 1000 &
    c_thermo_press[1] c_thermo_press[2] c_thermo_press[3] &
    c_thermo_press[4] c_thermo_press[5] c_thermo_press[6]
fix def all deform 1 x delta 0 ${strain} units box remap x
run 5000
unfix def
unfix avg
# repeat for y, z, xy, xz, yz strain modes; assemble C_ij from stress responses
"""

_STRESS_STRAIN_SNIPPET = """\
# Skeleton — adapt to your system and strain rate.
variable srate equal 1.0e-5    # 1/timeunit
fix int all nvt temp 300.0 300.0 100.0
fix def all deform 1 x erate ${srate} units box remap x
fix avg all ave/time 100 1 100 c_thermo_press[1] c_thermo_temp &
    file stress_strain.out
thermo_style custom step temp lx ly lz pxx pyy pzz pe
run 100000
unfix def
unfix int
"""


HOWTOS: tuple[Howto, ...] = (
    Howto(
        category="mechanics",
        slug="elastic_constants",
        title="Compute elastic constants",
        rationale=(
            "Elastic constants are obtained by applying small finite strains "
            "(~0.001) along each of the six independent strain modes and "
            "reading the stress-tensor response. The canonical procedure is "
            "in Howto_elastic and the in.elastic example."
        ),
        user_steps=(
            "Equilibrate the system at the target T,P with fix npt.",
            "For each of 6 strain modes (xx, yy, zz, xy, xz, yz), apply a "
            "small finite strain via fix deform.",
            "Re-equilibrate briefly under fix nvt and average the stress tensor.",
            "Compute the C_ij matrix from the stress responses.",
            "Validate against literature: for cubic crystals C11, C12, C44 "
            "should reproduce known values within a few percent.",
        ),
        snippet=_ELASTIC_SNIPPET,
        snippet_caveat=(
            "Skeleton only. Howto_elastic.html and examples/ELASTIC/in.elastic "
            "are authoritative."
        ),
        doc_refs=("Howto_elastic", "fix_deform", "compute_pressure"),
        related_commands=(("fix", "deform"), ("compute", "pressure")),
        related_howtos=(("mechanics", "stress_strain_curve"),),
        tags=("elastic", "stress", "strain", "mechanical", "Cij"),
    ),
    Howto(
        category="mechanics",
        slug="stress_strain_curve",
        title="Generate a stress-strain curve",
        rationale=(
            "Tensile or compressive loading uses fix deform with a constant "
            "engineering strain rate while a thermostat removes the work done. "
            "Stress is read from the diagonal of the pressure tensor, sign-flipped."
        ),
        user_steps=(
            "Equilibrate under fix npt at the target T (no applied strain).",
            "Switch to fix nvt for the loading run.",
            "Apply fix deform with `erate` along the loading direction.",
            "Log the pressure tensor; convert to stress (sigma = -P).",
            "Plot stress vs engineering strain (Δl/l0) at the chosen rate.",
        ),
        snippet=_STRESS_STRAIN_SNIPPET,
        snippet_caveat=(
            "Strain rate must be small enough that thermostat coupling is "
            "physical; see fix_deform doc Restrictions section."
        ),
        doc_refs=("fix_deform", "compute_pressure", "thermo_style"),
        related_commands=(("fix", "deform"), ("compute", "pressure")),
        related_howtos=(("mechanics", "elastic_constants"),),
        tags=("stress", "strain", "tensile", "compression", "loading"),
    ),
    Howto(
        category="mechanics",
        slug="deformation_setup",
        title="Set up an imposed deformation",
        rationale=(
            "fix deform can apply uniform strain rates (`erate`), constant box "
            "edges (`vel`), engineering strain (`final`), and trapezoidal "
            "profiles. Choose based on what the experiment specifies."
        ),
        user_steps=(
            "Decide: constant strain rate (erate), or fixed final dimension (final)?",
            "Decide: remap atoms with the box (`remap x`) or not?",
            "If running with periodic boundaries, the deformed direction must "
            "remain periodic; non-periodic edges need walls or fixed ends.",
            "Verify by running a short test and confirming volume / shape "
            "evolution matches the intent.",
        ),
        doc_refs=("fix_deform", "boundary"),
        related_commands=(("fix", "deform"),),
        tags=("deform", "strain", "setup"),
    ),
    Howto(
        category="mechanics",
        slug="virial_pressure",
        title="Compute and decompose virial pressure",
        rationale=(
            "Total pressure has kinetic + virial contributions. To diagnose "
            "stress sources in a heterogeneous system, decompose by group, "
            "interaction class (pair/bond/angle/...), or per-atom."
        ),
        user_steps=(
            "Use `compute pressure ID temp_id` for system-wide pressure.",
            "Use `compute stress/atom` then `compute reduce` for group-level stress.",
            "For per-interaction breakdown, use `compute pair/local` and "
            "`compute bond/local` (and analogues) plus group filters.",
        ),
        doc_refs=(
            "compute_pressure", "compute_stress_atom",
        ),
        related_commands=(
            ("compute", "pressure"),
            ("compute", "stress/atom"),
        ),
        tags=("pressure", "virial", "stress", "decomposition"),
    ),
)
