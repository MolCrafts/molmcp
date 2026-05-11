"""LAMMPS MCP provider — knowledge navigator over docs.lammps.org.

Does not invoke ``lmp``, does not fetch over the network, does not
read the local filesystem outside its own Python modules. All tools
are pure functions over small in-memory alias / howto / workflow
tables; they return URLs and structural pointers for the LLM to read.
"""

from .provider import LammpsProvider

__all__ = ["LammpsProvider"]
