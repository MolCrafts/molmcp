"""Application-layer assembly of the source collection."""

from __future__ import annotations

import json

from .collection import CollectionIndex, SourceBinding
from .config import AppConfig
from .discovery import DiscoveryConfig, DiscoveryEngine
from .discovery.config import DEFAULT_EXCLUDES


def build_collection(
    config: AppConfig, registry: object | None = None
) -> CollectionIndex:
    """Build one collection over every named source in ``config``.

    ``registry`` is the duck-typed extension point :class:`CollectionIndex`
    documents — anything exposing ``search`` / ``get`` / ``info`` joins the
    search as one more channel. molmcp ships no implementation: the capability
    manifest it used to carry had no producer anywhere in the ecosystem, so
    the shape was guesswork. The seam stays; the guess does not.
    """
    discovery = DiscoveryConfig(
        cache_dir=config.cache_dir or DiscoveryConfig().cache_dir,
        excludes=tuple(dict.fromkeys((*DEFAULT_EXCLUDES, *config.excludes))),
        watch=config.watch,
    )
    engine = DiscoveryEngine(discovery)
    bindings = [
        SourceBinding(
            name=name,
            spec=spec,
            engine=engine,
            namespace=name,
            metadata={"configured": True},
        )
        for name, spec in sorted(config.sources.items())
    ]
    return CollectionIndex(
        bindings,
        registry,
        metadata={
            "workspace_root": str(config.workspace_root),
            "watch": config.watch,
            "discovery": config.discovery,
        },
    )


def config_summary(config: AppConfig) -> str:
    """Stable, secret-free configuration text for diagnostics."""
    return json.dumps(
        {
            "workspace_root": str(config.workspace_root),
            "sources": config.sources,
            "watch": config.watch,
            "transport": config.server.transport,
            "discovery": config.discovery,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
