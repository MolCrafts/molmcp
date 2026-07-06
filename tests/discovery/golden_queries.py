"""Golden capability-retrieval cases + the fixture package they run against.

Zero-dependency (plain Python, no YAML) so the deterministic pytest
regression (``test_golden_ranking.py``) and the optional lightweight-model
judge (``scripts/eval_relevance.py``) import a single source of truth.

The fixture reproduces the shape that poisoned capability ranking: several
classes each expose a ``read`` method, and thin ``read_*`` functions each
instantiate one of them and call ``reader.read()``. With no receiver-type
inference, every ``reader.read()`` used to be blindly attributed to the
alphabetically-first ``read`` method (``readers.ac.AcReader.read``), inflating
its caller count into a fake hub that won capability queries it had nothing to
do with.
"""

from __future__ import annotations

from pathlib import Path

FIXTURE_FILES: dict[str, str] = {
    "readers/__init__.py": '"""Toy reader package."""\n',
    "readers/ac.py": '''"""Amber .ac reader."""


class AcReader:
    """Read an Amber .ac file and populate a Frame with atoms and bonds."""

    def __init__(self, path):
        self.path = path

    def read(self, frame=None):
        """Read the .ac file into a Frame with atoms and bonds."""
        return frame
''',
    "readers/lammps.py": '''"""LAMMPS data reader."""


class LammpsDataReader:
    """Read a LAMMPS data file and populate a Frame."""

    def __init__(self, path, atom_style):
        self.path = path
        self.atom_style = atom_style

    def read(self, frame=None):
        """Read the LAMMPS data file into a Frame."""
        return frame
''',
    "readers/top.py": '''"""GROMACS topology reader."""


class GromacsTopReader:
    """Read a GROMACS topology file and populate a Frame."""

    def __init__(self, path):
        self.path = path

    def read(self, frame=None):
        """Read the GROMACS topology file into a Frame."""
        return frame
''',
    "readers/api.py": '''"""Free functions that delegate to reader classes."""


def read_lammps_data(path, atom_style, frame=None):
    """Read a LAMMPS data file and return a Frame."""
    from .lammps import LammpsDataReader

    reader = LammpsDataReader(path, atom_style)
    return reader.read(frame=frame)


def read_amber_ac(path, frame=None):
    """Read an Amber ac file and return a Frame."""
    from .ac import AcReader

    reader = AcReader(path)
    return reader.read(frame=frame)


def read_gromacs_top(path, frame=None):
    """Read a GROMACS topology file and return a Frame."""
    from .top import GromacsTopReader

    reader = GromacsTopReader(path)
    return reader.read(frame=frame)
''',
}

# Each case: a natural-language task, the qualname suffixes that are an
# acceptable rank-1 answer, and suffixes that must NOT appear near the top.
GOLDEN: list[dict] = [
    {
        "task": "read a lammps data file into a frame",
        "expect_top1_suffixes": ["read_lammps_data", "LammpsDataReader"],
        "forbid_top3_suffixes": ["ac.AcReader.read", "top.GromacsTopReader.read"],
    },
    {
        "task": "read a gromacs topology file",
        "expect_top1_suffixes": ["read_gromacs_top", "GromacsTopReader"],
        "forbid_top3_suffixes": ["ac.AcReader.read", "lammps.LammpsDataReader.read"],
    },
    {
        "task": "read an amber ac file",
        "expect_top1_suffixes": ["read_amber_ac", "AcReader"],
        "forbid_top3_suffixes": ["lammps.LammpsDataReader.read"],
    },
]


def materialize_fixture(root: Path) -> Path:
    """Write ``FIXTURE_FILES`` under ``root`` and return the repo dir."""
    for rel, text in FIXTURE_FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root
