"""Output howtos — thermo, dump, multi-replica patterns."""

from __future__ import annotations

from . import Howto

HOWTOS: tuple[Howto, ...] = (
    Howto(
        category="output",
        slug="thermo_for_long_runs",
        title="Configure thermo for a long production run",
        rationale=(
            "Thermo output goes to log.lammps; setting it too frequent bloats "
            "the log and can become a bottleneck via I/O. Common practice: "
            "log every 1000 steps for production, every 1 step only when "
            "debugging."
        ),
        user_steps=(
            "Set thermo to a reasonable interval: `thermo 1000` for a 1M-step run.",
            "Customize columns with thermo_style custom step temp etotal press lx.",
            "Use thermo_modify flush yes if monitoring the run live.",
            "For checkpoints, also set `restart 100000 restart.*.bin`.",
        ),
        doc_refs=("thermo", "thermo_style", "thermo_modify", "restart"),
        related_commands=(
            ("command", "thermo"),
            ("command", "thermo_style"),
        ),
        tags=("output", "thermo", "production"),
    ),
    Howto(
        category="output",
        slug="dump_every_n",
        title="Configure dump output (frequency, fields, format)",
        rationale=(
            "Dump frequency × number of fields × number of atoms determines "
            "trajectory file size. Pick the right format (atom / custom / "
            "yaml / netcdf) and field set for your downstream analysis tool."
        ),
        user_steps=(
            "For VMD/OVITO: dump custom with id type x y z (+ vx vy vz if needed).",
            "For YAML / structured analysis: dump yaml.",
            "For compact binary: dump netcdf or h5md.",
            "Set frequency: 100-1000 steps for production, 10 steps for fine analysis.",
            "Use dump_modify sort id to make trajectories diff-friendly.",
        ),
        doc_refs=("dump", "dump_modify"),
        related_commands=(("command", "dump"), ("command", "dump_modify")),
        tags=("output", "dump", "trajectory"),
    ),
    Howto(
        category="output",
        slug="multi_replica_output",
        title="Output from multi-replica runs",
        rationale=(
            "Replica-exchange (temper) and partition runs use placeholders "
            "like %p and %t in dump filenames so each replica writes its "
            "own file. The variable command supports `world` and `universe` "
            "modes to select per-replica values."
        ),
        user_steps=(
            "Launch with -partition NxM and -in in.lammps.",
            "Use dump 1 all atom 1000 dump.%w.lammpstrj for per-world dumps.",
            "Use variable T world 300 320 340 360 to set per-world temperatures.",
            "Use thermo_modify flush yes to keep per-world logs readable.",
        ),
        doc_refs=("Howto_replica", "dump", "variable"),
        related_commands=(("command", "variable"), ("command", "dump")),
        tags=("output", "replica", "multi-replica", "temper"),
    ),
)
