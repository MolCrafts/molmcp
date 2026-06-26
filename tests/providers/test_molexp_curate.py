"""Tests for the OKF curation planner (``providers.molexp.curate``).

Pure read-only behaviour — no molexp install required. Exercises the two
branches of ``check_layout``: a ``build`` plan for an arbitrary directory and a
``repair`` plan for an existing-but-non-conformant workspace, plus the
knowledge-ingestion scan, the per-scope LLM-summary proposals, the truncation
bound, and the not-exists / not-a-directory short circuits.
"""

from __future__ import annotations

from molmcp.providers.molexp import curate


class TestCheckLayoutBuild:
    def test_non_workspace_proposes_build_plan(self, tmp_path):
        (tmp_path / "proj-a" / "exp-1" / "run-x").mkdir(parents=True)
        out = curate.check_layout(tmp_path)

        assert out["is_workspace"] is False
        assert out["conforms"] is False
        cur = out["proposed_curation"]
        assert cur["kind"] == "build"
        assert cur["mapping"]["concept_type"] == "workspace.root"

        project = cur["mapping"]["projects"][0]
        assert project["concept_type"] == "workspace.project"
        experiment = project["experiments"][0]
        assert experiment["concept_type"] == "workspace.experiment"
        run = experiment["runs"][0]
        assert run["concept_type"] == "workspace.run"
        # A source dir already named 'run-…' must not be double-prefixed.
        assert run["target_dir"] == "run-x"

    def test_run_dir_gets_run_prefix(self, tmp_path):
        (tmp_path / "p" / "e" / "001").mkdir(parents=True)
        cur = curate.check_layout(tmp_path)["proposed_curation"]
        run = cur["mapping"]["projects"][0]["experiments"][0]["runs"][0]
        assert run["source_dir"] == "001"
        assert run["target_dir"] == "run-001"

    def test_scaffold_lists_okf_markers_and_derived_rebuilds(self, tmp_path):
        (tmp_path / "p").mkdir()
        scaffold = curate.check_layout(tmp_path)["proposed_curation"]["scaffold"]
        assert "meta.yaml" in scaffold["concept_markers"]
        assert "index.md" in scaffold["knowledge_graph"]
        paths = {d["path"] for d in scaffold["rebuild_derived"]}
        assert "catalog/index.sqlite" in paths
        assert "<knowledge_bundle>/index.json" in paths


class TestKnowledgeIngest:
    def test_readme_bib_and_pdf_are_proposed_with_scopes(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (tmp_path / "README.md").write_text("# top")
        (proj / "refs.bib").write_text("@article{a,title={x}}")
        (proj / "paper.pdf").write_bytes(b"%PDF-1.4")

        ingest = curate.check_layout(tmp_path)["proposed_curation"]["knowledge"][
            "ingest"
        ]
        kinds = {i["kind"] for i in ingest}
        assert {"markdown", "bibtex", "pdf"} <= kinds

        readme = next(i for i in ingest if i["kind"] == "markdown")
        assert readme["proposed_concept_type"] == "note.note"
        assert readme["scope_kind"] == "workspace"
        assert readme["proposed_name"] == "readme"

        bib = next(i for i in ingest if i["kind"] == "bibtex")
        assert bib["proposed_concept_type"] == "reference.reference"
        assert bib["scope_kind"] == "project"
        assert bib["scope_id"] == "proj"

    def test_zotero_sqlite_detected(self, tmp_path):
        (tmp_path / "zotero.sqlite").write_bytes(b"SQLite format 3\x00")
        ingest = curate.check_layout(tmp_path)["proposed_curation"]["knowledge"][
            "ingest"
        ]
        assert any(i["kind"] == "zotero" for i in ingest)

    def test_llm_summaries_cover_scopes_but_skip_runs(self, tmp_path):
        (tmp_path / "proj" / "exp" / "run-1").mkdir(parents=True)
        summaries = curate.check_layout(tmp_path)["proposed_curation"]["knowledge"][
            "llm_summaries"
        ]
        kinds = {s["scope_kind"] for s in summaries}
        assert {"workspace", "project", "experiment"} <= kinds
        assert "run" not in kinds


class TestCheckLayoutTruncation:
    def test_oversized_arbitrary_dir_sets_truncated(self, tmp_path):
        for i in range(curate.MAX_PROJECTS + 5):
            (tmp_path / f"proj{i:03d}").mkdir()
        out = curate.check_layout(tmp_path)
        assert out["is_workspace"] is False
        assert out["truncated"] is True
        projects = out["proposed_curation"]["mapping"]["projects"]
        assert len(projects) == curate.MAX_PROJECTS


class TestCheckLayoutRepair:
    def test_workspace_missing_meta_yaml_proposes_repair(self, tmp_path):
        (tmp_path / "workspace.json").write_text("{}")
        proj = tmp_path / "projects" / "p"
        proj.mkdir(parents=True)
        (proj / "project.json").write_text("{}")

        out = curate.check_layout(tmp_path)
        assert out["is_workspace"] is True
        assert out["conforms"] is False
        assert "missing_meta_yaml" in {v["rule"] for v in out["violations"]}

        cur = out["proposed_curation"]
        assert cur["kind"] == "repair"
        assert cur["mapping"] is None
        markers = {m["marker"] for m in cur["scaffold"]["missing_markers"]}
        assert markers == {"meta.yaml"}

    def test_conformant_minimal_workspace_proposes_nothing(self, tmp_path):
        (tmp_path / "workspace.json").write_text("{}")
        (tmp_path / "meta.yaml").write_text("type: workspace.root\nid: ws\n")
        out = curate.check_layout(tmp_path)
        assert out["is_workspace"] is True
        assert out["conforms"] is True
        assert out["proposed_curation"] is None


class TestCheckLayoutEdge:
    def test_missing_path(self, tmp_path):
        out = curate.check_layout(tmp_path / "nope")
        assert out["exists"] is False
        assert out["proposed_curation"] is None

    def test_file_is_not_a_workspace(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("x")
        out = curate.check_layout(f)
        assert out["exists"] is True
        assert out["is_workspace"] is False
        assert out["proposed_curation"] is None
