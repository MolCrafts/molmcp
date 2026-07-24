"""Collection-wide registry, source search, and context packing."""

from .browse import (
    compose_context,
    open_ref,
    outline_source,
    packages_catalog,
    search_scoped,
)
from .index import DEFAULT_CONTEXT_BUDGET, MAX_CONTEXT_BUDGET, CollectionIndex
from .models import ContextPack, SearchHit, SourceBinding

__all__ = [
    "DEFAULT_CONTEXT_BUDGET",
    "MAX_CONTEXT_BUDGET",
    "CollectionIndex",
    "ContextPack",
    "SearchHit",
    "SourceBinding",
    "compose_context",
    "open_ref",
    "outline_source",
    "packages_catalog",
    "search_scoped",
]
