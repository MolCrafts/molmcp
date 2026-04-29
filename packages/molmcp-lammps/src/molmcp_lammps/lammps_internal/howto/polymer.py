"""Polymer howtos — bead-spring setup, bond breaking, collapse checks."""

from __future__ import annotations

from . import Howto

HOWTOS: tuple[Howto, ...] = (
    Howto(
        category="polymer",
        slug="polymer_setup",
        title="Set up a Kremer-Grest polymer melt",
        rationale=(
            "The standard bead-spring polymer model uses pair_style lj/cut "
            "(WCA at sigma * 2^(1/6) for a purely repulsive variant), "
            "bond_style fene, and atom_style bond or molecular. Length is in "
            "sigma units; mass is in 1.0 units; time in tau."
        ),
        user_steps=(
            "Use units lj.",
            "Use atom_style bond (chains without angles) or molecular (with angles).",
            "Declare pair_style lj/cut 1.122462 (= 2^(1/6) for WCA).",
            "Declare bond_style fene with K=30, R0=1.5, epsilon=1.0, sigma=1.0.",
            "Use pair_modify shift yes for purely repulsive WCA.",
            "Use special_bonds fene (excludes 1-2 LJ).",
        ),
        doc_refs=("Howto_bpm", "pair_lj", "bond_fene", "special_bonds"),
        related_commands=(
            ("pair_style", "lj/cut"),
            ("bond_style", "fene"),
            ("command", "special_bonds"),
        ),
        tags=("polymer", "bead-spring", "kremer-grest", "fene", "wca"),
    ),
    Howto(
        category="polymer",
        slug="bond_break_protocol",
        title="Allow bonds to break under load",
        rationale=(
            "fix bond/break removes bonds whose length exceeds a threshold. "
            "Combine with a stretching protocol (fix deform) to model failure. "
            "Note: bond/break does not apply to bond_style fene's divergent "
            "potential — use bond_style harmonic or quartic for breakable bonds."
        ),
        user_steps=(
            "Switch from bond_style fene to bond_style harmonic or quartic.",
            "Add fix break all bond/break N btype Rmax (every N steps, type btype, "
            "max length Rmax).",
            "Optionally use special_bonds extra so the neighbor list keeps "
            "track of newly-non-bonded pairs.",
            "Apply load via fix deform.",
            "Sanity-check: log the number of broken bonds via fix's output.",
        ),
        doc_refs=("fix_bond_break", "bond_style", "special_bonds"),
        related_commands=(
            ("fix", "bond/break"),
            ("bond_style", "harmonic"),
        ),
        tags=("polymer", "bond_break", "failure", "load"),
    ),
    Howto(
        category="polymer",
        slug="polymer_collapse_check",
        title="Verify a polymer chain has equilibrated",
        rationale=(
            "Single-chain or melt equilibration is slow. Track the radius of "
            "gyration (Rg), end-to-end distance, and bond-bond correlations to "
            "decide when the chain has decorrelated from its initial structure."
        ),
        user_steps=(
            "Use compute gyration to log Rg per chain (or per molecule with chunk).",
            "Use compute property/atom + compute reduce for end-to-end vectors.",
            "Run long enough that <Rg^2> plateaus AND its autocorrelation time "
            "is short compared to total run length.",
            "For melts, also check that the topological constraints (bond "
            "vector autocorrelation) decay.",
        ),
        doc_refs=(
            "compute_gyration", "compute_chunk_atom",
        ),
        related_commands=(
            ("compute", "gyration"),
            ("compute", "chunk/atom"),
        ),
        tags=("polymer", "equilibration", "rg", "gyration"),
    ),
)
