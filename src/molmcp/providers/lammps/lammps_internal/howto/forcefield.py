"""Force-field setup howtos — CHARMM, AMBER, OPLS, water models."""

from __future__ import annotations

from . import Howto

HOWTOS: tuple[Howto, ...] = (
    Howto(
        category="forcefield",
        slug="charmm_setup",
        title="Set up a CHARMM-style force field",
        rationale=(
            "CHARMM in LAMMPS uses pair_style lj/charmm/coul/long (or its "
            "fsw/fsh variants for force/potential switching), bond_style "
            "harmonic, angle_style charmm, dihedral_style charmm. The "
            "force-field cutoff and switching distance are part of the model "
            "and must match the parameter set."
        ),
        user_steps=(
            "Confirm the parameter file (typically PSF + RTF + PAR) is "
            "consistent with the LAMMPS data file you produce (e.g. via "
            "ch2lmp, charmm-gui, or moltemplate).",
            "Use atom_style full (charges + bonds + angles + dihedrals + impropers).",
            "Declare pair_style lj/charmm/coul/long with the canonical 8/10/12 "
            "switching cutoffs (or your parameter set's cutoffs).",
            "Add kspace_style pppm 1.0e-6 for the long-range Coulomb.",
            "Set special_bonds charmm (1-4 LJ + Coulomb scaling).",
        ),
        doc_refs=("Howto_bioFF", "pair_charmm", "special_bonds"),
        related_commands=(
            ("pair_style", "lj/charmm/coul/long"),
            ("command", "kspace_style"),
        ),
        tags=("forcefield", "charmm", "biomolecular"),
    ),
    Howto(
        category="forcefield",
        slug="amber_to_lammps",
        title="Convert an AMBER topology to a LAMMPS data file",
        rationale=(
            "AMBER's prmtop+inpcrd format does not load directly. Howto_amber2lammps "
            "describes the conversion (typically via amber2lmp.py, parmed, or "
            "InterMol)."
        ),
        user_steps=(
            "Use parmed or amber2lmp to convert prmtop+inpcrd into a LAMMPS data file.",
            "Choose a compatible pair_style: lj/charmm/coul/long is closest to "
            "AMBER's force-switching; lj/cut/coul/long with atom-based shift is "
            "an alternative.",
            "Set special_bonds amber (1-4 scale 0.5 LJ, 0.8333 Coul).",
            "Add kspace_style pppm 1.0e-6.",
            "Validate: single-point energy should match the AMBER value to "
            "within ~0.1% after matching cutoffs.",
        ),
        doc_refs=("Howto_amber2lammps", "Howto_bioFF", "special_bonds"),
        tags=("forcefield", "amber", "conversion", "biomolecular"),
    ),
    Howto(
        category="forcefield",
        slug="opls_aa_setup",
        title="Set up an OPLS-AA simulation",
        rationale=(
            "OPLS-AA uses Lennard-Jones + Coulomb with geometric mixing, "
            "harmonic bonds and angles, and OPLS dihedrals (a Fourier series). "
            "Tools like LigParGen or moltemplate produce the LAMMPS data + "
            "parameter blocks."
        ),
        user_steps=(
            "Generate the data file with explicit Pair Coeffs / Bond Coeffs / "
            "Angle Coeffs / Dihedral Coeffs sections.",
            "Declare: pair_style lj/cut/coul/long, bond_style harmonic, "
            "angle_style harmonic, dihedral_style opls.",
            "Use special_bonds lj/coul 0.0 0.0 0.5 (1-4 scale 0.5 for both LJ "
            "and Coul in OPLS-AA).",
            "Use pair_modify mix geometric (OPLS-AA convention).",
            "Add kspace_style pppm 1.0e-6.",
        ),
        doc_refs=("Howto_bioFF", "pair_modify", "special_bonds", "dihedral_opls"),
        related_commands=(
            ("pair_style", "lj/cut/coul/long"),
            ("dihedral_style", "opls"),
            ("command", "special_bonds"),
        ),
        tags=("forcefield", "opls", "opls-aa"),
    ),
    Howto(
        category="forcefield",
        slug="tip3p_water",
        title="Set up TIP3P water",
        rationale=(
            "TIP3P is a 3-site rigid water model. Use SHAKE/RATTLE to keep "
            "bonds and angles fixed; pair_style lj/cut/coul/long for "
            "non-bonded; charges per the model's parameter set."
        ),
        user_steps=(
            "Use atom_style full.",
            "Place atoms with bond/angle topology so SHAKE has constraints to enforce.",
            "Declare pair_style lj/cut/coul/long 10.0 8.0 (or your cutoff).",
            "Set bond_style harmonic, angle_style harmonic.",
            "fix wat all shake 1.0e-4 100 0 b 1 a 1   (where bond type 1 / "
            "angle type 1 are O-H and H-O-H).",
            "Add kspace_style pppm 1.0e-6.",
        ),
        doc_refs=("Howto_tip3p", "fix_shake"),
        related_commands=(("fix", "shake"), ("pair_style", "lj/cut/coul/long")),
        tags=("forcefield", "water", "tip3p", "shake"),
    ),
    Howto(
        category="forcefield",
        slug="tip4p_water",
        title="Set up TIP4P water",
        rationale=(
            "TIP4P uses a virtual M-site for the negative charge. LAMMPS "
            "handles this via the lj/cut/tip4p/long pair_style which inserts "
            "the M-site at runtime — the data file lists 3 atoms per water, "
            "not 4."
        ),
        user_steps=(
            "Use atom_style full.",
            "Use pair_style lj/cut/tip4p/long with explicit O-type, H-type, "
            "bond type, angle type, OM-distance, and cutoff.",
            "Use kspace_style pppm/tip4p 1.0e-6 (the tip4p variant).",
            "fix shake to keep bonds/angles rigid.",
            "Verify: the per-water dipole moment matches the TIP4P value (~2.18 D).",
        ),
        doc_refs=("Howto_tip4p", "pair_lj_cut_tip4p"),
        related_commands=(
            ("pair_style", "lj/cut/tip4p/long"),
            ("fix", "shake"),
        ),
        tags=("forcefield", "water", "tip4p", "shake"),
    ),
)
