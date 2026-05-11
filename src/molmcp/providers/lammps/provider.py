"""LAMMPS MCP provider — a knowledge-navigator over docs.lammps.org.

The provider does **not** invoke ``lmp``, **not** fetch docs over the
network, and **not** read the local filesystem outside its own Python
modules. Every tool is a pure function over small in-memory tables
plus the user's input. Tools return URLs and structural pointers; the
LLM does the actual reading via its own WebFetch (or asks the user).

See ``.claude/specs/lammps-mcp-spec.md`` for the full spec.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


_VERSION_ENV_VAR = "LAMMPS_MCP_DEFAULT_VERSION"


class LammpsProvider:
    """Provider for LAMMPS doc-navigation tools.

    Args:
        default_version: Default LAMMPS doc version branch when a tool
            call omits the ``version`` argument. One of ``stable``,
            ``latest``, ``release``. If ``None``, falls back to the
            ``LAMMPS_MCP_DEFAULT_VERSION`` env var, then to
            :data:`lammps_internal.urls.DEFAULT_VERSION`.
    """

    name = "lammps"

    def __init__(self, default_version: str | None = None) -> None:
        self._default_version_arg = default_version

    def _resolve_default_version(self) -> str:
        from .lammps_internal import urls

        if self._default_version_arg is not None:
            urls._validate_version(self._default_version_arg)
            return self._default_version_arg
        env = os.environ.get(_VERSION_ENV_VAR)
        if env:
            urls._validate_version(env)
            return env
        return urls.DEFAULT_VERSION

    def register(self, mcp: "FastMCP") -> None:
        from mcp.types import ToolAnnotations

        from .lammps_internal import (
            explain as explain_mod,
        )
        from .lammps_internal import (
            howto,
            linter,
            parser,
            router,
            urls,
            workflows,
        )
        from .lammps_internal.howto import errors as errors_mod

        ro = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
        default_version = self._resolve_default_version()

        @mcp.tool(annotations=ro)
        def get_doc_index(version: str = default_version) -> dict:
            """Return the structural map of docs.lammps.org for the requested version.

            Args:
                version: LAMMPS doc version branch. One of ``stable``
                    (most recent stable release), ``latest`` (develop
                    branch), or ``release`` (current feature release,
                    no path prefix).

            Returns:
                Doc map with version prefix, top-level URLs, command-index
                URLs, howto-index URL, known categories, and section
                conventions. Use this to plan navigation before resolving
                specific names.
            """
            return urls.doc_map(version)

        @mcp.tool(annotations=ro)
        def get_command_doc(
            name: str, version: str = default_version
        ) -> dict:
            """Resolve a top-level LAMMPS command to its doc URL + sections to read.

            Args:
                name: Command name (e.g. ``read_data``, ``units``,
                    ``minimize``, ``run``, ``kspace_style``).
                version: Doc version branch.

            Returns:
                Dict with ``candidates`` (each carries ``url``,
                ``shared_with``, ``confidence``) plus ``sections``. On
                miss returns ``did_you_mean`` + a ``fallback`` URL
                pointing at ``Commands.html``.
            """
            return urls.command_url(name, version)

        @mcp.tool(annotations=ro)
        def get_style_doc(
            category: str, name: str, version: str = default_version
        ) -> dict:
            """Resolve a LAMMPS style (fix npt, pair_style lj/cut, ...) to its doc URL.

            Args:
                category: One of ``pair_style``, ``bond_style``,
                    ``angle_style``, ``dihedral_style``, ``improper_style``,
                    ``fix``, ``compute``, ``dump``, ``kspace_style``,
                    ``atom_style``, ``region``.
                name: Style name (e.g. ``lj/cut``, ``npt``, ``temp``).
                version: Doc version branch.

            Returns:
                Dict with ``candidates`` (URL + ``shared_with``). LAMMPS
                groups related styles on shared pages — for example
                ``fix npt``, ``fix nvt`` and ``fix nph`` all live on
                ``fix_nh.html``; the ``shared_with`` field surfaces this.
            """
            return urls.style_url(category, name, version)

        @mcp.tool(annotations=ro)
        def get_howto_doc(
            topic: str, version: str = default_version
        ) -> dict:
            """Resolve a LAMMPS howto topic to its ``Howto_<topic>.html`` doc URL.

            Args:
                topic: Howto topic (e.g. ``thermostat``, ``barostat``,
                    ``elastic``, ``kappa``, ``viscosity``, ``tip3p``).
                version: Doc version branch.

            Returns:
                URL + sections-to-read. On miss returns ``did_you_mean``
                + a fallback to the howto index page.
            """
            return urls.howto_url(topic, version)

        @mcp.tool(annotations=ro)
        def plan_task(
            description: str, version: str = default_version
        ) -> dict:
            """Plan a free-text LAMMPS task into doc URLs + workflow tag.

            Args:
                description: Free-text task description (e.g.
                    "polymer NPT equilibration with long-range Coulomb").
                version: Doc version branch.

            Returns:
                Dict with ``doc_queries`` (ordered URLs to fetch),
                ``matched_workflow`` (one of the canonical kinds, if
                detected), and ``unmatched_keywords`` so the LLM knows
                when the heuristic router didn't fully cover the task.
            """
            return router.plan(description, version)

        @mcp.tool(annotations=ro)
        def get_workflow_outline(
            kind: str, version: str = default_version
        ) -> dict:
            """Return a canonical command-sequence outline for a workflow kind.

            Args:
                kind: One of ``minimize``, ``nve``, ``nvt``, ``npt``,
                    ``deform``, ``rerun``.
                version: Doc version branch.

            Returns:
                A skeleton outline of sections × commands with URL
                pointers and decision points (e.g. "if long-range Coulomb,
                add kspace_style"). The outline does not list arguments —
                fetch each command's URL for those.
            """
            return workflows.get(kind, version)

        @mcp.tool(annotations=ro)
        def parse_script(content: str) -> dict:
            """Tokenise a LAMMPS input script into structured commands.

            Args:
                content: Full input-script text.

            Returns:
                Dict with ``commands`` (each entry has ``line``, ``raw``,
                ``command``, ``args``, ``comment``), ``variables``
                (declared via ``variable``), and ``warnings`` (parser-level
                only; e.g. unbalanced quotes).
            """
            return parser.tokenize(content)

        @mcp.tool(annotations=ro)
        def validate_script(
            content: str, version: str = default_version
        ) -> dict:
            """Lint a LAMMPS input script for structural issues.

            Args:
                content: Full input-script text.
                version: Doc version branch (used for diagnostic ``doc_url``).

            Returns:
                Dict with ``diagnostics`` (each carries ``level``, ``line``,
                ``message``, ``source``, ``doc_url`` pointing at the right
                docs.lammps.org page when applicable) and a ``summary`` of
                error/warning/info counts.

                The linter is *structural only*: it does not validate
                per-command argument syntax. For those it emits
                ``info``-level diagnostics with ``source`` =
                ``content_check_required`` and a ``next_action`` instructing
                the LLM to fetch the doc URL and check the Syntax section.
            """
            return linter.lint(content, version)

        @mcp.tool(annotations=ro)
        def explain_command(
            line: str, version: str = default_version
        ) -> dict:
            """Explain one LAMMPS command line by parsing + linking the docs.

            Args:
                line: A single LAMMPS command line.
                version: Doc version branch.

            Returns:
                Dict with parsed ``tokens``, the resolved doc ``url``,
                ``shared_with`` info if multiple styles share the page,
                and a ``next_action`` directing the LLM to fetch and
                interpret. Argument-level interpretation is the LLM's
                job after fetching.
            """
            return explain_mod.explain(line, version)

        @mcp.tool(annotations=ro)
        def list_howtos() -> dict:
            """List howto categories with counts and descriptions.

            Returns:
                Dict with ``categories`` (list of {name, count,
                description}) and ``guidance`` text explaining the
                ``search_howtos`` / ``get_howto`` flow.
            """
            return howto.list_categories()

        @mcp.tool(annotations=ro)
        def search_howtos(
            query: str,
            category: str | None = None,
            limit: int = 25,
        ) -> dict:
            """Search howtos by keyword across one or all categories.

            Args:
                query: Free-text query; matches title / rationale / tags.
                category: Optional category filter (e.g. ``debug``,
                    ``mechanics``, ``transport``, ``equilibration``,
                    ``forcefield``, ``polymer``, ``rerun``, ``output``).
                limit: Maximum hits returned. Capped at 50.

            Returns:
                Dict with short ``matches`` (category, slug, title,
                summary, tags). Use ``get_howto`` for full content.
            """
            return howto.find(query, category, min(limit, 50))

        @mcp.tool(annotations=ro)
        def get_howto(
            category: str, slug: str, version: str = default_version
        ) -> dict:
            """Return one howto in full.

            Args:
                category: Howto category.
                slug: Howto slug within the category.
                version: Doc version branch (applied to ``doc_refs``).

            Returns:
                Full howto with ``rationale``, ``user_steps``, optional
                ``snippet`` + ``snippet_caveat``, ``doc_refs`` (URLs),
                ``related_commands`` (with URLs) and ``related_howtos``.
                On miss returns ``error`` + ``available_in_category``.
            """
            return howto.get(category, slug, version)

        @mcp.tool(annotations=ro)
        def explain_error(
            message: str, version: str = default_version
        ) -> dict:
            """Match a LAMMPS error string against curated cause hints.

            Args:
                message: The exact error text (or a substring) emitted by
                    LAMMPS.
                version: Doc version branch.

            Returns:
                Dict with ``matches`` (each carries ``cause_hint``,
                ``remedy_hints``, ``doc_refs`` URLs, ``related_howtos``).
                On miss returns ``matches=[]`` plus a ``fallback`` block
                advising the LLM how to search the docs.
            """
            return errors_mod.lookup(message, version)
