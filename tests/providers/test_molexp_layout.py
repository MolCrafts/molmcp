"""Tests for the molexp layout contract (``providers.molexp.layout``).

Two concerns live here:

* Pure-spec sanity of the frozen OKF layout contract — no molexp required.
* A *drift detector*: when the real ``molexp`` package is installed, build a
  workspace through its public API and assert the vetted constants still match
  the directory shape molexp actually produces (entity files, the ``run-``
  prefix, and the eager OKF ``meta.yaml`` markers + their concept types). This
  is the safety net that lets us mirror molexp's frozen layout invariant as a
  constant instead of probing internals at runtime.

The curation planner (``check_layout``) is exercised in ``test_molexp_curate``.

Note: unlike ``test_molexp.py`` this module does **not** stub ``molexp``,
so ``import molexp`` resolves to the real package (or skips).
"""

from __future__ import annotations

import pytest

from molmcp.providers.molexp import curate, layout


class TestLayoutSpec:
    def test_levels_cover_the_four_tiers_with_concept_types(self):
        spec = layout.layout_spec()
        assert [lvl["kind"] for lvl in spec["levels"]] == [
            "workspace",
            "project",
            "experiment",
            "run",
        ]
        assert [lvl["concept_type"] for lvl in spec["levels"]] == [
            "workspace.root",
            "workspace.project",
            "workspace.experiment",
            "workspace.run",
        ]

    def test_okf_concept_model_is_present(self):
        spec = layout.layout_spec()
        markers = {m["path"] for m in spec["concept_markers"]}
        assert "<concept>/meta.yaml" in markers
        assert "<concept>/index.md" in markers
        knowledge = {c["concept_type"] for c in spec["knowledge_concepts"]}
        assert knowledge == {"note.note", "reference.reference"}

    def test_rules_reflect_okf_not_legacy_library(self):
        spec = layout.layout_spec()
        blob = " ".join(spec["rules"]).lower()
        assert "meta.yaml" in blob
        assert "_ops/run.json" in blob
        assert "library/ subsystem was removed" in blob
        # The removed library/ paths must not reappear in the file classification.
        files = spec["authoritative_files"] + spec["derived_files"]
        assert not any("library/" in f["path"] for f in files)

    def test_authoritative_vs_derived_split(self):
        spec = layout.layout_spec()
        auth = {f["path"] for f in spec["authoritative_files"]}
        derived = {f["path"] for f in spec["derived_files"]}
        assert "<concept>/meta.yaml" in auth
        assert "runs/run-<run_id>/_ops/run.json" in auth
        assert "catalog/index.sqlite" in derived
        assert "<knowledge_bundle>/index.json" in derived

    def test_render_tree_shows_run_prefix_and_okf_markers(self):
        tree = layout.render_tree()
        assert "runs/run-<run_id>/" in tree
        assert "meta.yaml" in tree
        assert "_ops/run.json" in tree
        assert "library/" not in tree


class TestDriftAgainstLiveMolexp:
    """The constants must match the tree molexp's API actually materializes."""

    def test_materialized_workspace_matches_spec(self, tmp_path):
        pytest.importorskip("molexp", reason="molcrafts-molexp not installed")
        from molexp.workspace import Workspace

        ws = Workspace(root=tmp_path, name="probe")
        proj = ws.add_project("My Project")
        exp = proj.add_experiment("Exp One")
        exp.add_run(params={"x": 1})

        levels = {lvl.kind: lvl for lvl in layout.WORKSPACE_LAYOUT}

        # Workspace root carries the eager OKF meta.yaml marker.
        assert (tmp_path / layout.META_YAML).is_file()

        proj_dir = tmp_path / "projects" / "my-project"
        assert (proj_dir / levels["project"].entity_file).is_file()
        assert (proj_dir / layout.META_YAML).is_file()
        assert levels["project"].container == "projects"
        assert levels["project"].concept_type == "workspace.project"

        exp_dir = proj_dir / "experiments" / "exp-one"
        assert (exp_dir / levels["experiment"].entity_file).is_file()
        assert (exp_dir / layout.META_YAML).is_file()
        assert levels["experiment"].container == "experiments"

        run_dirs = [d for d in (exp_dir / "runs").iterdir() if d.is_dir()]
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]
        assert run_dir.name.startswith("run-"), run_dir.name
        assert levels["run"].dir_template == "run-<run_id>"
        assert (run_dir / levels["run"].entity_file).is_file()
        assert (run_dir / layout.META_YAML).is_file()

        # The concept type the constant claims must match the on-disk meta.yaml.
        meta_text = (run_dir / layout.META_YAML).read_text()
        assert levels["run"].concept_type in meta_text

        # And the planner agrees the real, materialized tree conforms.
        result = curate.check_layout(tmp_path)
        assert result["is_workspace"] is True
        assert result["conforms"] is True, result["violations"]
