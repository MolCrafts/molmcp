"""Debug howtos — what to do when a script crashes or misbehaves.

Howtos here describe *flags and procedures* that the user runs against
their own ``lmp`` binary. The provider never invokes ``lmp`` itself;
``user_steps`` are commands the LLM relays to the user.
"""

from __future__ import annotations

from . import Howto

HOWTOS: tuple[Howto, ...] = (
    Howto(
        category="debug",
        slug="setup_crash",
        title="Validate parsing without running",
        rationale=(
            "When LAMMPS errors during setup, the failure may be a parse "
            "error or a runtime error. Running with -sr (skip run) parses "
            "every command but does not execute the run, isolating parse "
            "issues."
        ),
        user_steps=(
            "Run: lmp -sr -in in.lammps",
            "Add `-echo screen` to see each command as LAMMPS reads it.",
            "Read the log; the failing command is the last one before the error.",
            "If parsing succeeds with -sr, the issue is a runtime/setup error; "
            "see runtime_crash recipe.",
        ),
        doc_refs=("Run_options",),
        tags=("debug", "parse", "setup", "crash", "skip-run"),
    ),
    Howto(
        category="debug",
        slug="runtime_crash",
        title="Narrow down a runtime crash",
        rationale=(
            "Runtime errors (lost atoms, bond-extending, neighbor-list "
            "issues) often come from too-large displacements or a bad "
            "neighbor-list configuration. Reduce the timestep, log more "
            "often, and inspect what changes immediately before the crash."
        ),
        user_steps=(
            "Set `thermo 1` for the suspect run.",
            "Reduce `timestep` by 5-10x.",
            "Increase neighbor skin: `neigh_modify every 1 delay 0 check yes`.",
            "Add `dump 1 all custom 100 dump.crash id type x y z fx fy fz`.",
            "Re-run; share the last 30 lines of log.lammps and dump.crash.",
        ),
        doc_refs=("neigh_modify", "thermo", "dump"),
        related_howtos=(("debug", "lost_atoms"),),
        tags=("debug", "runtime", "crash", "neighbor", "timestep"),
    ),
    Howto(
        category="debug",
        slug="lost_atoms",
        title="Diagnose lost atoms",
        rationale=(
            "`Lost atoms` means atoms moved past the simulation box "
            "boundaries faster than communication could keep up. Common "
            "causes: timestep too large, bad initial geometry, or a "
            "missing thermostat at high T."
        ),
        user_steps=(
            "Set `thermo_modify lost warn flush yes` to keep running and log losses.",
            "Reduce `timestep` to 1/4 or 1/10 of current.",
            "Check initial geometry: dump 0 all custom 1 init.dump id type x y z.",
            "If running NVE without thermostat, add a Langevin or "
            "temp/csvr thermostat for a short equilibration first.",
        ),
        doc_refs=("thermo_modify", "Howto_thermostat"),
        related_howtos=(
            ("debug", "runtime_crash"),
            ("equilibration", "minimize_then_md"),
        ),
        tags=("debug", "lost", "atoms", "timestep"),
    ),
    Howto(
        category="debug",
        slug="slow_run",
        title="Speed up a slow simulation",
        rationale=(
            "Slow throughput in LAMMPS usually comes from neighbor-list "
            "rebuilds, communication, or kspace. Inspect the timing breakdown "
            "first; tune the dominant cost."
        ),
        user_steps=(
            "Run a short benchmark; read the breakdown at the end of log.lammps "
            "(Pair / Bond / Kspace / Neigh / Comm / Output / Modify / Other).",
            "If `Neigh` dominates: try `neigh_modify every 5 delay 0 check yes`.",
            "If `Comm` dominates: try `processors * * *` with explicit topology, "
            "or `comm_modify mode single`.",
            "If `Kspace` dominates: relax accuracy (`kspace_style pppm 1.0e-4` "
            "instead of 1.0e-6) or use msm.",
            "If `Pair` dominates and a GPU/KOKKOS package is built in, switch "
            "with `package gpu 1` and matching pair_style suffix.",
        ),
        doc_refs=("neigh_modify", "processors", "comm_modify", "kspace_modify"),
        tags=("debug", "performance", "slow", "tuning"),
    ),
    Howto(
        category="debug",
        slug="unknown_style_error",
        title="Resolve an `Unknown ... style` error",
        rationale=(
            "LAMMPS errors like `Unknown pair style: lj/cut/coul/long` mean "
            "the style is documented but not compiled into your binary. "
            "The fix is a build with the relevant package, not a script change."
        ),
        user_steps=(
            "Look up the style's package: use which_lammps_package_provides "
            "(MCP) or check the Restrictions section of the style's doc page.",
            "Verify your build: lmp -h | grep <PACKAGE>",
            "If the package is missing, rebuild LAMMPS with it: "
            "`cmake -D PKG_<NAME>=ON ...` (CMake) or `make yes-<name>` (legacy make).",
            "Do NOT silently switch to another style; physics may differ.",
        ),
        doc_refs=("Build_package",),
        tags=("debug", "build", "package", "unknown_style"),
    ),
    Howto(
        category="debug",
        slug="data_file_error",
        title="Diagnose a data-file read error",
        rationale=(
            "`read_data` is strict about header counts vs. body sections, "
            "atom_style consistency, and coefficient compatibility. Most "
            "errors trace to a header line that disagrees with the actual "
            "section content."
        ),
        user_steps=(
            "Confirm the data file's atom_style matches the script's atom_style.",
            "Check the header counts: # atoms, # bonds, # angles, # dihedrals, "
            "# impropers, # atom types, etc., match each section's row count.",
            "If the data file contains coefficient sections (Pair Coeffs, Bond "
            "Coeffs, ...), make sure the script's `pair_style`, `bond_style`, "
            "etc. were declared *before* `read_data`.",
            "Use `info system` after read_data to confirm what LAMMPS parsed.",
        ),
        doc_refs=("read_data", "atom_style"),
        tags=("debug", "data", "read_data", "atom_style"),
    ),
    Howto(
        category="debug",
        slug="bad_dynamics",
        title="Diagnose energy drift / unphysical dynamics",
        rationale=(
            "Unexpected dynamics (energy drift, exploding pressure, frozen "
            "system) usually mean wrong units, wrong timestep, missing "
            "thermostat coupling, or a force-field with mis-set coefficients."
        ),
        user_steps=(
            "Confirm `units` matches the force-field source (real / metal / lj / si).",
            "Run a short NVE benchmark with `thermo_style custom step temp etotal "
            "press`; energy should be conserved to within ~10^-4 over 1000 steps.",
            "Check timestep: 1 fs for real, 0.5-1 fs for fast-bond systems "
            "(use SHAKE/RATTLE if doing 2 fs).",
            "If using a thermostat: verify damping constant (~100*timestep "
            "for Nose-Hoover, ~100 for langevin in real units).",
        ),
        doc_refs=("units", "fix_nh", "fix_langevin"),
        tags=("debug", "dynamics", "drift", "units", "timestep"),
    ),
)
