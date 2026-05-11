"""Error-string → cause hint lookup table.

Each entry is a curated *pointer* to the right doc URL; the
authoritative explanation lives in the docs. Hints are intentionally
short — the LLM should fetch the doc URLs to get full context.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import urls


@dataclass(frozen=True)
class ErrorHint:
    match_pattern: str
    cause_hint: str
    remedy_hints: tuple[str, ...]
    doc_refs: tuple[str, ...]  # slugs
    related_howtos: tuple[tuple[str, str], ...] = ()  # (category, slug)


ERROR_HINTS: tuple[ErrorHint, ...] = (
    ErrorHint(
        match_pattern="Bond atoms missing on proc",
        cause_hint=(
            "A bond extended past the inter-processor communication cutoff — "
            "atoms moved too far in one timestep relative to neighbour-list "
            "settings, or initial geometry placed bonded atoms too far apart."
        ),
        remedy_hints=(
            "Reduce the timestep.",
            "Increase comm_modify cutoff.",
            "Check for bad initial geometry (run a short minimization first).",
        ),
        doc_refs=("comm_modify", "neigh_modify"),
        related_howtos=(("debug", "runtime_crash"), ("debug", "lost_atoms")),
    ),
    ErrorHint(
        match_pattern="Lost atoms",
        cause_hint=(
            "An atom moved past the simulation box boundaries faster than "
            "communication could keep up. Common at high T without a thermostat, "
            "or with a too-large timestep."
        ),
        remedy_hints=(
            "Reduce timestep.",
            "Add or strengthen the thermostat.",
            "Use thermo_modify lost warn to keep running and log losses.",
        ),
        doc_refs=("thermo_modify", "Howto_thermostat"),
        related_howtos=(("debug", "lost_atoms"),),
    ),
    ErrorHint(
        match_pattern="Out of range atoms - cannot compute",
        cause_hint=(
            "Atoms left the simulation domain, often because a fix is "
            "applying impossible constraints or a simulation is unstable."
        ),
        remedy_hints=(
            "Check fix definitions for typos / wrong groups.",
            "Reduce timestep.",
            "Run a short NVE benchmark to check energy conservation.",
        ),
        doc_refs=("fix", "Howto_thermostat"),
        related_howtos=(("debug", "bad_dynamics"),),
    ),
    ErrorHint(
        match_pattern="Unknown pair style",
        cause_hint=(
            "The requested pair_style is documented but not compiled into "
            "your LAMMPS binary. The fix is a build with the relevant package, "
            "not a script change."
        ),
        remedy_hints=(
            "Check the style's package: lookup which_lammps_package_provides.",
            "Verify build: lmp -h | grep <PACKAGE>.",
            "Rebuild with the package: cmake -D PKG_<NAME>=ON ...",
        ),
        doc_refs=("Build_package",),
        related_howtos=(("debug", "unknown_style_error"),),
    ),
    ErrorHint(
        match_pattern="Unknown fix style",
        cause_hint=(
            "The requested fix style is documented but not compiled into "
            "your LAMMPS binary."
        ),
        remedy_hints=(
            "Look up which package the fix belongs to.",
            "Verify build: lmp -h | grep <PACKAGE>.",
            "Rebuild with the package.",
        ),
        doc_refs=("Build_package",),
        related_howtos=(("debug", "unknown_style_error"),),
    ),
    ErrorHint(
        match_pattern="Unknown compute style",
        cause_hint="Compute style not compiled into the binary.",
        remedy_hints=("Same diagnosis as Unknown pair/fix style.",),
        doc_refs=("Build_package",),
        related_howtos=(("debug", "unknown_style_error"),),
    ),
    ErrorHint(
        match_pattern="Unknown dump style",
        cause_hint="Dump style not compiled into the binary.",
        remedy_hints=("Same diagnosis as Unknown pair/fix style.",),
        doc_refs=("Build_package",),
        related_howtos=(("debug", "unknown_style_error"),),
    ),
    ErrorHint(
        match_pattern="Cannot use kspace solver on system with no charge",
        cause_hint=(
            "kspace_style was declared but no atoms carry a non-zero charge."
        ),
        remedy_hints=(
            "Check the data file Charges section.",
            "Confirm atom_style is one that supports charge (charge / full).",
            "Remove kspace_style if Coulomb interactions are not needed.",
        ),
        doc_refs=("kspace_style", "atom_style"),
    ),
    ErrorHint(
        match_pattern="Pair style requires atom attribute q",
        cause_hint=(
            "The chosen pair_style needs atomic charge but atom_style does "
            "not provide it."
        ),
        remedy_hints=(
            "Switch to atom_style charge or atom_style full.",
            "Choose a pair_style without /coul if charge is not needed.",
        ),
        doc_refs=("atom_style", "pair_style"),
    ),
    ErrorHint(
        match_pattern="Bond coeff for type",
        cause_hint=(
            "Bond coefficients are missing or malformed for one or more bond "
            "types in the data file."
        ),
        remedy_hints=(
            "Confirm the data file's Bond Coeffs section covers all # bond types.",
            "Confirm bond_style was declared before read_data.",
            "Check the parameter values match the chosen bond_style.",
        ),
        doc_refs=("read_data", "bond_coeff"),
        related_howtos=(("debug", "data_file_error"),),
    ),
    ErrorHint(
        match_pattern="Angle coeff for type",
        cause_hint="Angle coefficients missing or malformed.",
        remedy_hints=(
            "Same diagnosis as Bond coeff for type, applied to angles.",
        ),
        doc_refs=("read_data", "angle_coeff"),
        related_howtos=(("debug", "data_file_error"),),
    ),
    ErrorHint(
        match_pattern="No fix nvt/npt/nph defined",
        cause_hint=(
            "compute temp/com or related compute references a thermostatting fix "
            "that wasn't created (or was unfixed)."
        ),
        remedy_hints=(
            "Define the fix before the compute that depends on it.",
            "Remove the dependent compute if no thermostat is wanted.",
        ),
        doc_refs=("fix_nh",),
    ),
    ErrorHint(
        match_pattern="Cannot find atom type in data file",
        cause_hint=(
            "An Atoms section row references an atom type beyond the count "
            "declared in the header."
        ),
        remedy_hints=(
            "Match the header `# atom types N` to the maximum type id used.",
            "Validate counts: header `# atoms` == row count of Atoms section.",
        ),
        doc_refs=("read_data",),
        related_howtos=(("debug", "data_file_error"),),
    ),
    ErrorHint(
        match_pattern="Atom IDs must be consecutive",
        cause_hint=(
            "Some commands (e.g. read_dump, certain fixes) require sequential "
            "atom IDs starting from 1."
        ),
        remedy_hints=(
            "Renumber atoms so IDs are 1..N.",
            "Use atom_modify id sort to keep them sorted.",
        ),
        doc_refs=("atom_modify", "read_data"),
    ),
    ErrorHint(
        match_pattern="Numeric atom IDs must be positive",
        cause_hint="Atom IDs must be > 0.",
        remedy_hints=("Renumber atoms starting from 1.",),
        doc_refs=("read_data",),
    ),
    ErrorHint(
        match_pattern="Cutoff for kspace solver",
        cause_hint=(
            "kspace_style requires the pair_style cutoff to be at least as "
            "large as kspace's real-space cutoff."
        ),
        remedy_hints=(
            "Increase the pair_style cutoff.",
            "Lower the kspace accuracy (e.g. 1.0e-4 instead of 1.0e-6) so the "
            "real-space cutoff shrinks.",
        ),
        doc_refs=("kspace_style", "kspace_modify", "pair_style"),
    ),
    ErrorHint(
        match_pattern="Domain too small",
        cause_hint=(
            "Box dimension is smaller than required by the pair_style cutoff "
            "or kspace real-space cutoff times 2."
        ),
        remedy_hints=(
            "Increase box size (replicate, change_box).",
            "Reduce cutoff.",
        ),
        doc_refs=("change_box", "replicate"),
    ),
    ErrorHint(
        match_pattern="Neighbor list overflow",
        cause_hint=(
            "Per-atom neighbor list exceeded the storage allocated; usually "
            "happens at high density or with very long cutoffs."
        ),
        remedy_hints=(
            "Use neigh_modify one and page to enlarge.",
            "Reduce pair_style cutoff if possible.",
        ),
        doc_refs=("neigh_modify",),
    ),
    ErrorHint(
        match_pattern="ERROR on proc",
        cause_hint=(
            "Generic per-processor error. The actual cause is in the rest of "
            "the message — match more of the substring."
        ),
        remedy_hints=("Re-run with -echo screen to see the failing command.",),
        doc_refs=("Run_options",),
        related_howtos=(("debug", "setup_crash"),),
    ),
    ErrorHint(
        match_pattern="Illegal",
        cause_hint=(
            "An `Illegal ... command` error means LAMMPS could not parse the "
            "command's arguments — usually a missing keyword, wrong number of "
            "args, or stray text."
        ),
        remedy_hints=(
            "Re-read the command's Syntax section in the docs.",
            "Run with -sr to localise the line.",
            "Watch for missing trailing arguments after a keyword.",
        ),
        doc_refs=("Run_options",),
        related_howtos=(("debug", "setup_crash"),),
    ),
    ErrorHint(
        match_pattern="Substitution for variable",
        cause_hint=(
            "A `${X}` reference resolved to nothing because X was never "
            "declared, or was declared with the wrong style (equal vs string "
            "vs index)."
        ),
        remedy_hints=(
            "Verify the variable was declared before use.",
            "Check the variable style: `equal` for numeric expressions, "
            "`string` for free text, `index` for sequenced lists.",
        ),
        doc_refs=("variable",),
    ),
)


def lookup(message: str, version: str = urls.DEFAULT_VERSION) -> dict:
    urls._validate_version(version)
    matches: list[dict] = []
    for hint in ERROR_HINTS:
        if hint.match_pattern in message:
            matches.append(
                {
                    "match_pattern": hint.match_pattern,
                    "cause_hint": hint.cause_hint,
                    "remedy_hints": list(hint.remedy_hints),
                    "doc_refs": [
                        urls.build_url(slug, version) for slug in hint.doc_refs
                    ],
                    "related_howtos": [
                        {"category": c, "slug": s}
                        for (c, s) in hint.related_howtos
                    ],
                }
            )
    if not matches:
        return {
            "error_message": message,
            "version": version,
            "matches": [],
            "fallback": {
                "rationale": (
                    "Error string not in our hint table. Common LAMMPS "
                    "errors are usually documented in the relevant command's "
                    "Restrictions section."
                ),
                "next_action": (
                    "Search docs.lammps.org for the exact error text, or "
                    "run with -echo screen to localise the failing line."
                ),
            },
        }
    return {
        "error_message": message,
        "version": version,
        "matches": matches,
    }
