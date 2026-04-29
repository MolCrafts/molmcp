"""Tests for ``LammpsProvider``.

The provider is a knowledge navigator: it does not invoke ``lmp``,
does not fetch docs from the network, and does not read the local
filesystem outside its own Python modules. Tests are pure-function
checks against in-memory tables.
"""

from __future__ import annotations

import pytest

pytest.importorskip("molmcp", reason="molcrafts-molmcp not installed")
pytest.importorskip("fastmcp", reason="fastmcp not installed")

from molmcp_lammps import LammpsProvider  # noqa: E402
from molmcp_lammps.lammps_internal import (  # noqa: E402
    explain,
    howto,
    linter,
    parser,
    router,
    urls,
    workflows,
)
from molmcp_lammps.lammps_internal.howto import (  # noqa: E402
    errors as errors_mod,
)

# ---------------------------------------------------------------------------
# Provider integration with molmcp
# ---------------------------------------------------------------------------


def _build_server(provider: LammpsProvider | None = None):
    from molmcp import create_server

    return create_server(
        name="lammps-test",
        providers=[provider or LammpsProvider()],
        discover_entry_points=False,
        import_roots=None,
    )


def _list_tools(server):
    import asyncio

    return asyncio.run(server.list_tools())


def _get_tool(server, name: str):
    import asyncio

    tool = asyncio.run(server.get_tool(name))
    if tool is None:
        raise KeyError(f"tool {name!r} not registered")
    return tool.fn


def test_provider_implements_molmcp_protocol():
    from molmcp import Provider

    provider = LammpsProvider()
    assert isinstance(provider, Provider)
    assert provider.name == "lammps"


def test_all_tools_have_read_only_annotation():
    server = _build_server()
    tools = _list_tools(server)
    assert tools, "no tools registered"
    for tool in tools:
        annotations = getattr(tool, "annotations", None)
        assert annotations is not None, f"Tool {tool.name!r} missing annotations"
        assert getattr(annotations, "readOnlyHint", False) is True, (
            f"Tool {tool.name!r} not marked read-only"
        )
        assert getattr(annotations, "openWorldHint", True) is False, (
            f"Tool {tool.name!r} not marked closed-world"
        )


def test_thirteen_tools_registered():
    server = _build_server()
    tools = _list_tools(server)
    names = {t.name for t in tools}
    expected = {
        "get_doc_index",
        "get_command_doc",
        "get_style_doc",
        "get_howto_doc",
        "plan_task",
        "get_workflow_outline",
        "parse_script",
        "validate_script",
        "explain_command",
        "list_howtos",
        "search_howtos",
        "get_howto",
        "explain_error",
    }
    assert names == expected


# ---------------------------------------------------------------------------
# URL builder + alias map
# ---------------------------------------------------------------------------


def test_doc_map_returns_versioned_root():
    m = urls.doc_map("stable")
    assert m["version"] == "stable"
    assert m["doc_root"] == "https://docs.lammps.org/stable/"
    assert m["manual_toc"] == "https://docs.lammps.org/stable/Manual.html"
    assert "fix" in m["categories"] or "command" in m["categories"]


def test_doc_map_for_release_omits_path_prefix():
    m = urls.doc_map("release")
    assert m["doc_root"] == "https://docs.lammps.org/"
    assert m["manual_toc"] == "https://docs.lammps.org/Manual.html"


def test_doc_map_for_latest_uses_latest_prefix():
    m = urls.doc_map("latest")
    assert m["doc_root"] == "https://docs.lammps.org/latest/"


def test_doc_map_rejects_unknown_version():
    with pytest.raises(ValueError):
        urls.doc_map("nonsense")


def test_command_url_regular_case():
    r = urls.command_url("read_data", "stable")
    assert r["candidates"][0]["url"] == "https://docs.lammps.org/stable/read_data.html"
    assert r["candidates"][0]["confidence"] == "high"


def test_command_url_unknown_falls_back_to_index():
    r = urls.command_url("definitely_not_a_command", "stable")
    assert r["candidates"] == []
    assert "did_you_mean" in r
    assert r["fallback"]["url"].endswith("Commands.html")


def test_style_url_shared_page_fix_npt_to_fix_nh():
    r = urls.style_url("fix", "npt", "stable")
    assert r["candidates"][0]["url"] == "https://docs.lammps.org/stable/fix_nh.html"
    shared = {(s["kind"], s["name"]) for s in r["candidates"][0]["shared_with"]}
    assert ("fix", "nvt") in shared
    assert ("fix", "nph") in shared


def test_style_url_shared_page_pair_lj_cut_to_pair_lj():
    r = urls.style_url("pair_style", "lj/cut", "stable")
    assert r["candidates"][0]["url"] == "https://docs.lammps.org/stable/pair_lj.html"


def test_style_url_shared_page_pair_lj_cut_coul_long():
    r = urls.style_url("pair_style", "lj/cut/coul/long", "stable")
    assert (
        r["candidates"][0]["url"]
        == "https://docs.lammps.org/stable/pair_lj_cut_coul.html"
    )
    shared_names = {s["name"] for s in r["candidates"][0]["shared_with"]}
    assert "lj/cut/coul/cut" in shared_names


def test_style_url_unknown_falls_back_to_category_index():
    r = urls.style_url("fix", "totally_unknown_fix", "stable")
    assert r["candidates"] == []
    assert r["fallback"]["url"].endswith("Commands_fix.html")


def test_style_url_rejects_unknown_category():
    r = urls.style_url("not_a_category", "anything", "stable")
    assert "error" in r
    assert "valid_categories" in r


def test_style_url_versions_propagate():
    for v, prefix in (
        ("stable", "https://docs.lammps.org/stable/"),
        ("latest", "https://docs.lammps.org/latest/"),
        ("release", "https://docs.lammps.org/"),
    ):
        r = urls.style_url("fix", "npt", v)
        assert r["candidates"][0]["url"] == f"{prefix}fix_nh.html"


def test_howto_url_known_topic():
    r = urls.howto_url("thermostat", "stable")
    assert r["url"] == "https://docs.lammps.org/stable/Howto_thermostat.html"


def test_howto_url_unknown_topic_did_you_mean():
    r = urls.howto_url("thermo_stat", "stable")
    assert r["url"] is None
    assert "did_you_mean" in r
    assert "thermostat" in r["did_you_mean"]
    assert r["fallback"]["url"].endswith("Howto.html")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parser_basic_commands():
    text = "units real\natom_style full\nread_data sys.data\n"
    p = parser.tokenize(text)
    assert [c["command"] for c in p["commands"]] == [
        "units",
        "atom_style",
        "read_data",
    ]
    assert p["commands"][0]["line"] == 1


def test_parser_strips_comments_outside_quotes():
    text = "fix 1 all npt # set up NPT\n"
    p = parser.tokenize(text)
    assert p["commands"][0]["command"] == "fix"
    assert p["commands"][0]["args"] == ["1", "all", "npt"]
    assert p["commands"][0]["comment"] == "set up NPT"


def test_parser_continuation_lines_joined():
    text = (
        "fix av all ave/time 100 5 1000 &\n"
        "  c_thermo_press[1] &\n"
        "  c_thermo_press[2]\n"
    )
    p = parser.tokenize(text)
    assert len(p["commands"]) == 1
    cmd = p["commands"][0]
    assert cmd["command"] == "fix"
    assert "c_thermo_press[1]" in cmd["args"]
    assert "c_thermo_press[2]" in cmd["args"]
    # The line number of the continuation block is the first physical line.
    assert cmd["line"] == 1


def test_parser_collects_variables():
    text = 'variable T equal 300.0\nvariable name string "my_run"\n'
    p = parser.tokenize(text)
    assert p["variables"]["T"] == "equal 300.0".split(maxsplit=1)[1]
    assert "my_run" in p["variables"]["name"]


def test_parser_warns_on_unbalanced_quotes():
    text = 'print "hello\n'
    p = parser.tokenize(text)
    assert any("unbalanced quote" in w for w in p["warnings"])


# ---------------------------------------------------------------------------
# Linter
# ---------------------------------------------------------------------------


def _diag_kinds(diags):
    return {(d["level"], d["source"], d["line"]) for d in diags}


def test_linter_flags_pair_coeff_without_pair_style():
    text = "units real\natom_style atomic\nread_data sys.data\npair_coeff * * 0.1 3.5\n"
    result = linter.lint(text)
    errs = [d for d in result["diagnostics"] if d["level"] == "error"]
    assert any("pair_coeff" in d["message"] for d in errs)


def test_linter_flags_long_range_without_kspace():
    text = (
        "units real\n"
        "atom_style full\n"
        "read_data sys.data\n"
        "pair_style lj/cut/coul/long 10.0\n"
        "pair_coeff * * 0.1 3.5\n"
    )
    result = linter.lint(text)
    errs = [d for d in result["diagnostics"] if d["level"] == "error"]
    assert any("kspace_style" in d["message"] for d in errs)


def test_linter_accepts_long_range_with_kspace():
    text = (
        "units real\n"
        "atom_style full\n"
        "read_data sys.data\n"
        "pair_style lj/cut/coul/long 10.0\n"
        "pair_coeff * * 0.1 3.5\n"
        "kspace_style pppm 1.0e-4\n"
    )
    result = linter.lint(text)
    errs = [d for d in result["diagnostics"] if d["level"] == "error"]
    assert not any("kspace_style" in d["message"] for d in errs)


def test_linter_flags_unfix_unknown_id():
    text = "fix eq all nvt temp 300 300 100\nunfix bogus\n"
    result = linter.lint(text)
    errs = [d for d in result["diagnostics"] if d["level"] == "error"]
    assert any("bogus" in d["message"] for d in errs)


def test_linter_flags_duplicate_fix_id_without_unfix():
    text = (
        "fix eq all nvt temp 300 300 100\n"
        "fix eq all npt temp 300 300 100 iso 1 1 1000\n"
    )
    result = linter.lint(text)
    errs = [d for d in result["diagnostics"] if d["level"] == "error"]
    assert any("eq" in d["message"] and "redefining" in d["message"] for d in errs)


def test_linter_emits_content_check_pointers_with_correct_url():
    text = (
        "units real\n"
        "atom_style full\n"
        "read_data sys.data\n"
        "pair_style lj/cut 10.0\n"
        "pair_coeff * * 0.1 3.5\n"
        "fix eq all npt temp 300 300 100 iso 1 1 1000\n"
    )
    result = linter.lint(text, version="stable")
    info_diags = [
        d for d in result["diagnostics"]
        if d["source"] == "content_check_required"
    ]
    urls_seen = {d["doc_url"] for d in info_diags}
    # pair_style lj/cut → pair_lj.html, fix npt → fix_nh.html
    assert "https://docs.lammps.org/stable/pair_lj.html" in urls_seen
    assert "https://docs.lammps.org/stable/fix_nh.html" in urls_seen


def test_linter_flags_undeclared_variable_reference():
    text = "variable T equal 300\nfix eq all nvt temp ${UNKNOWN} 300 100\n"
    result = linter.lint(text)
    warns = [d for d in result["diagnostics"] if d["source"] == "reference"]
    assert any("UNKNOWN" in d["message"] for d in warns)


def test_linter_summary_counts():
    text = "pair_coeff * * 0.1 3.5\n"
    result = linter.lint(text)
    summary = result["summary"]
    assert summary["errors"] >= 1


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def test_router_npt_keyword_matches_workflow():
    plan = router.plan("polymer NPT equilibration with long-range Coulomb")
    assert plan["matched_workflow"] == "npt"
    queries = plan["doc_queries"]
    # at least one query should resolve to fix_nh.html
    urls_seen = {q.get("url") for q in queries if "url" in q}
    assert any(u and u.endswith("fix_nh.html") for u in urls_seen)
    assert any(u and u.endswith("kspace_style.html") for u in urls_seen)


def test_router_unmatched_keywords_reported():
    plan = router.plan("xyz nonsense_token rare_thing")
    assert plan["matched_workflow"] is None
    assert plan["unmatched_keywords"]


def test_router_elastic_routes_to_howto_elastic():
    plan = router.plan("compute elastic constants for fcc copper")
    queries = plan["doc_queries"]
    urls_seen = {q.get("url") for q in queries if "url" in q}
    assert any(u and u.endswith("Howto_elastic.html") for u in urls_seen)


def test_router_versioning_propagates():
    plan = router.plan("npt equilibration", version="latest")
    for q in plan["doc_queries"]:
        if "url" in q:
            assert "/latest/" in q["url"]


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


def test_workflow_npt_outline_includes_protocol_section():
    w = workflows.get("npt")
    section_names = [s["section"] for s in w["outline"]]
    assert "protocol" in section_names
    assert "interactions" in section_names


def test_workflow_npt_protocol_includes_fix_npt_url():
    w = workflows.get("npt", version="stable")
    protocol = next(s for s in w["outline"] if s["section"] == "protocol")
    npt_cmd = next(c for c in protocol["commands"] if c["name"] == "fix npt")
    assert npt_cmd["url"] == "https://docs.lammps.org/stable/fix_nh.html"
    assert "shared_with" in npt_cmd


def test_workflow_unknown_kind_returns_error():
    w = workflows.get("not_a_workflow_kind")
    assert "error" in w


def test_workflow_kinds_seeded():
    assert {"minimize", "nve", "nvt", "npt", "deform", "rerun"}.issubset(
        set(workflows.list_kinds())
    )


# ---------------------------------------------------------------------------
# Howtos
# ---------------------------------------------------------------------------


def test_howto_categories_seeded():
    out = howto.list_categories()
    names = {c["name"] for c in out["categories"]}
    expected = {
        "debug", "mechanics", "transport", "equilibration",
        "rerun", "forcefield", "polymer", "output",
    }
    assert names == expected


def test_howtos_no_duplicate_keys():
    seen: set[tuple[str, str]] = set()
    for r in howto.all_howtos():
        key = (r.category, r.slug)
        assert key not in seen
        seen.add(key)


def test_howto_find_by_query_no_filter():
    out = howto.find("elastic")
    slugs = {(m["category"], m["slug"]) for m in out["matches"]}
    assert ("mechanics", "elastic_constants") in slugs


def test_howto_find_with_category_filter():
    out = howto.find("crash", category="debug")
    assert out["matches"]
    assert all(m["category"] == "debug" for m in out["matches"])


def test_howto_get_returns_full_content_with_versioned_doc_refs():
    out = howto.get("mechanics", "elastic_constants", version="stable")
    assert out["category"] == "mechanics"
    assert out["doc_refs"]
    for url in out["doc_refs"]:
        assert "https://docs.lammps.org/stable/" in url


def test_howto_get_unknown_returns_error_with_available_list():
    out = howto.get("debug", "nonexistent")
    assert "error" in out
    assert "available_in_category" in out


def test_howto_with_snippet_has_caveat():
    for r in howto.all_howtos():
        if r.snippet is not None:
            assert r.snippet_caveat, f"{r.category}/{r.slug} snippet without caveat"


def test_howto_snippets_under_30_lines():
    for r in howto.all_howtos():
        if r.snippet is not None:
            assert len(r.snippet.splitlines()) <= 30, (
                f"{r.category}/{r.slug} snippet exceeds 30 lines"
            )


def test_howto_doc_refs_resolve_to_real_slugs():
    """Every howto doc_ref slug should be a valid alias-map page."""
    valid_slugs = set(urls.PAGE_SLUGS.values()) | {
        f"Howto_{t}" for t in urls.HOWTO_TOPICS
    }
    valid_slugs |= {
        # extra non-command pages we cite by slug
        "Build_package", "Run_options", "Howto_bonded", "atom_style",
        "kspace_style", "comm_modify", "thermo_modify", "neigh_modify",
    }
    for r in howto.all_howtos():
        for slug in r.doc_refs:
            assert (
                slug in valid_slugs
                or slug.startswith("Howto_")
                or slug.startswith("Commands_")
                or slug in {"Build_package", "Run_options"}
            ), f"{r.category}/{r.slug}: dangling doc_ref slug {slug!r}"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_error_lookup_known_substring():
    out = errors_mod.lookup("ERROR: Bond atoms missing on proc 0")
    assert out["matches"]
    m = out["matches"][0]
    assert "comm_modify" in " ".join(m["doc_refs"])


def test_error_lookup_unknown_returns_fallback():
    out = errors_mod.lookup("ERROR: this is a totally novel never-seen error")
    assert out["matches"] == []
    assert "fallback" in out


def test_error_lookup_propagates_version():
    out = errors_mod.lookup("Lost atoms", version="latest")
    for m in out["matches"]:
        for url in m["doc_refs"]:
            assert "/latest/" in url


# ---------------------------------------------------------------------------
# Explain
# ---------------------------------------------------------------------------


def test_explain_resolves_fix_npt_to_fix_nh():
    out = explain.explain("fix 1 all npt temp 300 300 100 iso 1 1 1000")
    assert out["command"] == "fix"
    assert out["style"] == "npt"
    assert out["url"] == "https://docs.lammps.org/stable/fix_nh.html"
    shared = {(s["kind"], s["name"]) for s in out["shared_with"]}
    assert ("fix", "nvt") in shared


def test_explain_resolves_top_level_command():
    out = explain.explain("read_data system.data")
    assert out["command"] == "read_data"
    assert out["url"] == "https://docs.lammps.org/stable/read_data.html"


def test_explain_falls_back_to_command_index_on_unknown():
    out = explain.explain("zzzunknownzzz arg1 arg2")
    assert out["url"].endswith("Commands.html")


# ---------------------------------------------------------------------------
# Tool surface (call through fastmcp)
# ---------------------------------------------------------------------------


def test_tool_get_doc_index_callable():
    server = _build_server()
    fn = _get_tool(server, "get_doc_index")
    out = fn()
    assert "doc_root" in out


def test_tool_get_command_doc():
    server = _build_server()
    fn = _get_tool(server, "get_command_doc")
    out = fn(name="read_data")
    assert out["candidates"][0]["url"].endswith("read_data.html")


def test_tool_validate_script_returns_diagnostics():
    server = _build_server()
    fn = _get_tool(server, "validate_script")
    out = fn(content="pair_coeff * * 0.1 3.5\n")
    assert "diagnostics" in out
    assert out["summary"]["errors"] >= 1


def test_tool_get_howto_full_content():
    server = _build_server()
    fn = _get_tool(server, "get_howto")
    out = fn(category="debug", slug="setup_crash")
    assert out["slug"] == "setup_crash"
    assert "user_steps" in out
    assert out["user_steps"]


def test_tool_explain_error():
    server = _build_server()
    fn = _get_tool(server, "explain_error")
    out = fn(message="Lost atoms during run")
    assert out["matches"]


# ---------------------------------------------------------------------------
# Default version configuration
# ---------------------------------------------------------------------------


def test_default_version_argument_propagates():
    provider = LammpsProvider(default_version="latest")
    assert provider._resolve_default_version() == "latest"


def test_default_version_env_var_used(monkeypatch):
    monkeypatch.setenv("LAMMPS_MCP_DEFAULT_VERSION", "release")
    provider = LammpsProvider()
    assert provider._resolve_default_version() == "release"


def test_default_version_invalid_raises():
    with pytest.raises(ValueError):
        LammpsProvider(default_version="bogus")._resolve_default_version()


def test_default_version_falls_back_to_stable(monkeypatch):
    monkeypatch.delenv("LAMMPS_MCP_DEFAULT_VERSION", raising=False)
    provider = LammpsProvider()
    assert provider._resolve_default_version() == "stable"
