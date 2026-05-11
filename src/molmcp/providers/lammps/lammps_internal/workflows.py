"""Canonical LAMMPS workflow outlines.

Each outline is a list of sections; each section is a list of commands
that typically appear in that section of an input script. Commands
carry only their *name* and (optionally) ``shared_with`` markers; URLs
are built at lookup time using the requested version.

Outlines are skeletons, not finished scripts. They tell the LLM the
*order* of concerns. Argument-level decisions come from the live docs.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import urls


@dataclass(frozen=True)
class CommandRef:
    name: str  # human-readable: "fix npt", "pair_style", etc.
    kind: str = "command"  # "command" | "fix" | "compute" | etc.
    base: str | None = None  # for styles, the base name (e.g. "npt")

    def to_dict(self, version: str) -> dict:
        out: dict[str, object] = {"name": self.name}
        slug: str | None = None
        if self.kind == "command":
            key = ("command", self.base or self.name)
            if key in urls.PAGE_SLUGS:
                slug = urls.PAGE_SLUGS[key]
        elif self.base is not None:
            key = (self.kind, self.base)
            if key in urls.PAGE_SLUGS:
                slug = urls.PAGE_SLUGS[key]
                shared = [
                    {"kind": k, "name": n}
                    for (k, n) in urls.SHARED_WITH.get(slug, ())
                    if (k, n) != (self.kind, self.base)
                ]
                if shared:
                    out["shared_with"] = [
                        f"{e['kind']} {e['name']}" for e in shared
                    ]
        if slug is not None:
            out["url"] = urls.build_url(slug, version)
        return out


@dataclass(frozen=True)
class Decision:
    description: str
    add_command: str
    add_command_kind: str = "command"
    add_command_base: str | None = None

    def to_dict(self, version: str) -> dict:
        ref = CommandRef(
            name=self.add_command,
            kind=self.add_command_kind,
            base=self.add_command_base or self.add_command,
        ).to_dict(version)
        return {"if": self.description, **ref}


@dataclass(frozen=True)
class Section:
    name: str
    commands: tuple[CommandRef, ...]
    decisions: tuple[Decision, ...] = ()

    def to_dict(self, version: str) -> dict:
        out: dict[str, object] = {
            "section": self.name,
            "commands": [c.to_dict(version) for c in self.commands],
        }
        if self.decisions:
            out["decisions"] = [d.to_dict(version) for d in self.decisions]
        return out


@dataclass(frozen=True)
class Workflow:
    kind: str
    description: str
    sections: tuple[Section, ...]
    related_recipes: tuple[tuple[str, str], ...] = ()

    def to_dict(self, version: str) -> dict:
        return {
            "kind": self.kind,
            "version": version,
            "description": self.description,
            "outline": [s.to_dict(version) for s in self.sections],
            "related_recipes": [
                {"category": c, "slug": s} for (c, s) in self.related_recipes
            ],
            "next_action": (
                "Use this outline as a skeleton. Fetch each command's URL "
                "only as needed to fill in arguments."
            ),
        }


_INIT_SECTION = Section(
    name="initialization",
    commands=(
        CommandRef("units"),
        CommandRef("atom_style"),
        CommandRef("boundary"),
    ),
)

_SYSTEM_SECTION_DATA = Section(
    name="system_definition",
    commands=(CommandRef("read_data"),),
)

_INTERACTIONS_SECTION = Section(
    name="interactions",
    commands=(
        CommandRef("pair_style"),
        CommandRef("pair_coeff"),
    ),
    decisions=(
        Decision(
            description="long-range Coulomb required",
            add_command="kspace_style",
        ),
        Decision(
            description="molecular system with bonds",
            add_command="bond_style",
        ),
        Decision(
            description="molecular system with angles",
            add_command="angle_style",
        ),
        Decision(
            description="molecular system with dihedrals",
            add_command="dihedral_style",
        ),
    ),
)

_OUTPUT_SECTION = Section(
    name="output",
    commands=(
        CommandRef("thermo"),
        CommandRef("thermo_style"),
        CommandRef("dump"),
        CommandRef("dump_modify"),
    ),
)

_FINALIZATION_SECTION = Section(
    name="finalization",
    commands=(
        CommandRef("write_data"),
        CommandRef("write_restart"),
    ),
)


WORKFLOWS: dict[str, Workflow] = {
    "minimize": Workflow(
        kind="minimize",
        description="Energy minimization to a local-minimum geometry.",
        sections=(
            _INIT_SECTION,
            _SYSTEM_SECTION_DATA,
            _INTERACTIONS_SECTION,
            _OUTPUT_SECTION,
            Section(
                name="protocol",
                commands=(
                    CommandRef("min_style"),
                    CommandRef("min_modify"),
                    CommandRef("minimize"),
                ),
            ),
            _FINALIZATION_SECTION,
        ),
        related_recipes=(("equilibration", "minimize_then_md"),),
    ),
    "nve": Workflow(
        kind="nve",
        description="Constant-NVE microcanonical integration.",
        sections=(
            _INIT_SECTION,
            _SYSTEM_SECTION_DATA,
            _INTERACTIONS_SECTION,
            _OUTPUT_SECTION,
            Section(
                name="protocol",
                commands=(
                    CommandRef("velocity"),
                    CommandRef("fix nve", kind="fix", base="nve"),
                    CommandRef("timestep"),
                    CommandRef("run"),
                    CommandRef("unfix"),
                ),
            ),
            _FINALIZATION_SECTION,
        ),
    ),
    "nvt": Workflow(
        kind="nvt",
        description="NVT (constant-T) equilibration via Nose-Hoover.",
        sections=(
            _INIT_SECTION,
            _SYSTEM_SECTION_DATA,
            _INTERACTIONS_SECTION,
            _OUTPUT_SECTION,
            Section(
                name="protocol",
                commands=(
                    CommandRef("velocity"),
                    CommandRef("fix nvt", kind="fix", base="nvt"),
                    CommandRef("timestep"),
                    CommandRef("run"),
                    CommandRef("unfix"),
                ),
            ),
            _FINALIZATION_SECTION,
        ),
        related_recipes=(("equilibration", "minimize_then_md"),),
    ),
    "npt": Workflow(
        kind="npt",
        description="NPT (constant-T, constant-P) equilibration via Nose-Hoover.",
        sections=(
            _INIT_SECTION,
            _SYSTEM_SECTION_DATA,
            _INTERACTIONS_SECTION,
            _OUTPUT_SECTION,
            Section(
                name="protocol",
                commands=(
                    CommandRef("velocity"),
                    CommandRef("fix npt", kind="fix", base="npt"),
                    CommandRef("timestep"),
                    CommandRef("run"),
                    CommandRef("unfix"),
                ),
            ),
            _FINALIZATION_SECTION,
        ),
        related_recipes=(
            ("equilibration", "minimize_then_md"),
            ("equilibration", "npt_to_nvt_handoff"),
        ),
    ),
    "deform": Workflow(
        kind="deform",
        description="Apply imposed deformation (strain) at constant T.",
        sections=(
            _INIT_SECTION,
            _SYSTEM_SECTION_DATA,
            _INTERACTIONS_SECTION,
            _OUTPUT_SECTION,
            Section(
                name="protocol",
                commands=(
                    CommandRef("fix nvt", kind="fix", base="nvt"),
                    CommandRef("fix deform", kind="fix", base="deform"),
                    CommandRef(
                        "compute pressure", kind="compute", base="pressure"
                    ),
                    CommandRef(
                        "compute stress/atom",
                        kind="compute",
                        base="stress/atom",
                    ),
                    CommandRef("run"),
                    CommandRef("unfix"),
                ),
            ),
            _FINALIZATION_SECTION,
        ),
        related_recipes=(
            ("mechanics", "elastic_constants"),
            ("mechanics", "stress_strain_curve"),
        ),
    ),
    "rerun": Workflow(
        kind="rerun",
        description="Post-hoc analysis of a saved trajectory via rerun.",
        sections=(
            _INIT_SECTION,
            Section(
                name="system_definition",
                commands=(CommandRef("read_data"),),
            ),
            _INTERACTIONS_SECTION,
            _OUTPUT_SECTION,
            Section(
                name="protocol",
                commands=(
                    CommandRef("rerun"),
                ),
            ),
        ),
        related_recipes=(("rerun", "analyze_trajectory"),),
    ),
}


def list_kinds() -> tuple[str, ...]:
    return tuple(WORKFLOWS)


def get(kind: str, version: str = urls.DEFAULT_VERSION) -> dict:
    urls._validate_version(version)
    if kind not in WORKFLOWS:
        return {
            "error": f"unknown workflow kind {kind!r}",
            "available_kinds": list(WORKFLOWS),
        }
    return WORKFLOWS[kind].to_dict(version)
