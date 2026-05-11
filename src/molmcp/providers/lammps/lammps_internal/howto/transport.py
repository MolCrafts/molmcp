"""Transport howtos — thermal conductivity, viscosity, diffusion."""

from __future__ import annotations

from . import Howto

HOWTOS: tuple[Howto, ...] = (
    Howto(
        category="transport",
        slug="thermal_conductivity",
        title="Compute thermal conductivity (Green-Kubo or NEMD)",
        rationale=(
            "Two canonical routes: Green-Kubo (equilibrium, integrate the "
            "heat-flux autocorrelation) and NEMD (Müller-Plathe reverse-NEMD "
            "or imposed gradient). Howto_kappa describes both with examples."
        ),
        user_steps=(
            "Choose a route. Green-Kubo: better for liquids, needs long runs.",
            "NEMD (Müller-Plathe): use fix thermal/conductivity; faster but "
            "applies a non-trivial perturbation.",
            "For Green-Kubo, sample compute heat/flux every step and integrate "
            "with fix ave/correlate to get the autocorrelation.",
            "For NEMD, set up the reverse-NEMD fix and read the resulting "
            "temperature gradient + power.",
            "Compare against literature for the chosen force field.",
        ),
        doc_refs=("Howto_kappa", "compute_heat_flux", "fix_ave_correlate"),
        related_commands=(("compute", "heat/flux"),),
        tags=("transport", "thermal", "conductivity", "kappa", "green-kubo", "nemd"),
    ),
    Howto(
        category="transport",
        slug="viscosity",
        title="Compute shear viscosity",
        rationale=(
            "Three routes: Green-Kubo (stress-tensor autocorrelation), NEMD "
            "(imposed shear rate), or SLLOD (uniform shear without walls). "
            "Howto_viscosity covers all three with examples."
        ),
        user_steps=(
            "Equilibrate at the target T (and density for liquids).",
            "Green-Kubo: log off-diagonal pressure tensor (Pxy, Pxz, Pyz) every "
            "step; integrate the autocorrelation.",
            "SLLOD: use fix nvt/sllod with fix deform applying shear strain rate.",
            "Müller-Plathe NEMD: use fix viscosity to swap velocities between slabs.",
            "Average over multiple independent runs; viscosity is sensitive to "
            "system size and run length.",
        ),
        doc_refs=("Howto_viscosity", "fix_nvt_sllod", "fix_deform"),
        related_commands=(
            ("fix", "nvt/sllod"),
            ("fix", "deform"),
        ),
        tags=("transport", "viscosity", "green-kubo", "sllod", "shear"),
    ),
    Howto(
        category="transport",
        slug="diffusion_coefficient",
        title="Compute self-diffusion via MSD or VACF",
        rationale=(
            "Two equivalent routes: mean-squared displacement (Einstein "
            "relation) or velocity autocorrelation (Green-Kubo). MSD is "
            "simpler; VACF gives more information per ps but needs careful "
            "integration."
        ),
        user_steps=(
            "Equilibrate the system (avoid drift; use fix nve after equilibration).",
            "Compute MSD: `compute msd all msd com yes` then plot vs time.",
            "Linear-fit the long-time slope; D = slope / (2 * dim).",
            "VACF route: `compute vacf` + `fix ave/correlate`; integrate and "
            "use D = (1/dim) * integral.",
            "Run long enough that MSD is clearly linear (typically > 10x mean "
            "free time).",
        ),
        doc_refs=("Howto_diffusion", "compute_msd", "compute_vacf"),
        related_commands=(("compute", "msd"), ("compute", "vacf")),
        tags=("transport", "diffusion", "msd", "vacf", "self-diffusion"),
    ),
)
