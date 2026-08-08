"""The shape a provider plane shares: declare tools, let the base register them.

Each provider used to spend most of its class on one ``register()`` method —
349, 402 and 191 lines — holding every tool as a nested function, plus its
own copy of the availability probe, the missing-package guard, and a set of
hand-rolled annotations. The duplication drifted: three probes with three
signatures, three guard messages (one of which never said how to install
anything), and annotation values that disagreed between planes.

Here a tool is a method carrying a :func:`tool` declaration. The base
collects them, checks the upstream package once, and registers. Providers
are left holding only what is theirs: what the tools do.

Nothing here imports a science package. ``probe`` asks the import system
whether one *could* be imported, which is what a catalog listing needs —
importing it to find out would drag a whole scientific stack into a process
that only wanted to print a list.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp import FastMCP

#: Attribute a declared tool carries. Private by convention; read only here.
_MARKER = "__molmcp_tool__"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One tool a provider offers.

    Attributes:
        name: The wire name a client sees after the server prefix. Bare by
            contract — the plane id is already the server name.
        annotations: From :mod:`molmcp.providers.annotations`.
        attribute: Name of the method implementing it.
    """

    name: str
    annotations: ToolAnnotations
    attribute: str


def tool(
    annotations: ToolAnnotations, *, name: str | None = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare a method as one of this plane's MCP tools.

    Args:
        annotations: What a client needs to decide whether to confirm first.
            Use a constant from :mod:`molmcp.providers.annotations`.
        name: Wire name, when the method cannot carry it. ``open`` shadows a
            builtin and ``exec`` is a keyword, so both are declared this way.
            Defaults to the method name.
    """

    def declare(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, _MARKER, (name or fn.__name__, annotations))
        return fn

    return declare


class ProviderBase:
    """Base for a plane's provider.

    Subclasses set :attr:`name`, optionally :attr:`upstream` /
    :attr:`import_name`, and declare tools with :func:`tool`.

    Attributes:
        name: Plane id and MCP server name. Clients see ``<name>__<tool>``.
        upstream: Distribution to install when the plane is unavailable, as
            it would be typed after ``pip install``. ``None`` means the plane
            needs nothing beyond molmcp.
        import_name: Module :meth:`probe` looks for. Defaults to *upstream*
            with dashes folded, which is wrong often enough to be worth
            setting explicitly.
    """

    name: ClassVar[str]
    upstream: ClassVar[str | None] = None
    import_name: ClassVar[str | None] = None

    # -- availability -------------------------------------------------

    def probe(self) -> bool:
        """Whether this plane can be served here.

        A plane whose science package is missing is a normal state, not an
        error: catalogs and generated client configs omit it silently. Only
        an explicit ``molmcp serve <plane>`` fails, and then loudly.

        Override when availability is not just "the package is present" —
        molvis is available whenever a stage factory has been injected,
        browser or no browser.
        """
        module = self.import_name or (
            self.upstream.replace("-", "_") if self.upstream else None
        )
        if module is None:
            return True
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            # A package present but broken is not one we can serve.
            return False

    def require_upstream(self) -> None:
        """Raise unless this plane's package is installed.

        Raises:
            RuntimeError: naming the distribution and how to install it.
        """
        if self.probe():
            return
        target = self.upstream or self.name
        raise RuntimeError(
            f"the {self.name!r} plane requires the {target!r} package. "
            f"Install with: pip install {target}"
        )

    # -- registration --------------------------------------------------

    def tool_specs(self) -> Iterator[ToolSpec]:
        """Every declared tool, base classes first, in declaration order."""
        found: dict[str, ToolSpec] = {}
        for klass in reversed(type(self).__mro__):
            for attribute, value in vars(klass).items():
                marker = getattr(value, _MARKER, None)
                if marker is None:
                    continue
                wire_name, annotations = marker
                found[attribute] = ToolSpec(
                    name=wire_name, annotations=annotations, attribute=attribute
                )
        return iter(found.values())

    def register(self, mcp: FastMCP) -> None:
        """Attach this plane's tools to its server.

        Bound methods are handed to FastMCP directly: ``self`` is already
        applied, so it never reaches the tool schema, and the docstring the
        agent reads is the one on the method.

        Raises:
            RuntimeError: the upstream package is missing.
        """
        self.require_upstream()
        for spec in self.tool_specs():
            mcp.tool(name=spec.name, annotations=spec.annotations)(
                getattr(self, spec.attribute)
            )


__all__ = ["ProviderBase", "ToolSpec", "tool"]
