"""GitHub source resolution.

Implemented in Stage 5 (ref->SHA resolve + tarball download). Until then
this module raises a clear error so the spec form is reserved and
``SourceResolver`` stays uniform.
"""

from __future__ import annotations

from ..config import DiscoveryConfig
from .resolver import Snapshot, SourceError


def resolve_github(spec: str, config: DiscoveryConfig) -> Snapshot:
    raise SourceError(
        "GitHub sources are not available yet (planned for Stage 5); "
        "use a local path or 'pkg:<name>' spec"
    )
