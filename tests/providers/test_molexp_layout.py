"""Tests for the molexp layout contract + linter (``providers.molexp.layout``).

Two concerns live here:

* Pure-spec sanity and the read-only linter — no molexp required.
* A *drift detector*: when the real ``molexp`` package is installed, build
  a workspace through its public API and assert the vetted constant still
  matches the directory shape molexp actually produces. This is the safety
  net that lets us mirror molexp's frozen layout invariant as a constant
  instead of probing internals at runtime.

Note: unlike ``test_molexp.py`` this module does **not** stub ``molexp``,
so ``import molexp`` resolves to the real package (or skips).
"""

from __future__ import annotations

import pytest

from molmcp.providers.molexp import layout


class TestLayoutSpec:
    def test_levels_cover_the_four_tiers(self):
        spec = layout.layout_spec()
        assert [lvl["kind"] for lvl in spec["levels"]] == [
            "workspace",
            "project",
            "experiment",
            "run",
        ]

    def test_rules_and_files_are_present(self):
        spec = layout.layout_spec()
        assert spec["rules"], "rules must be non-empty"
        assert any("run-" in r for r in spec["rules"])
        assert spec["authoritative_files"]
        assert spec["derived_files"]

    def test_render_tree_shows_run_prefix(self):
        assert "runs/run-<run_id>/" in layout.render_tree()


class TestCheckLayoutTruncation:
    def test_oversized_arbitrary_dir_sets_truncated(self, tmp_path):
        for i in range(layout._MAX_PROJECTS + 5):
            (tmp_path / f"proj{i:03d}").mkdir()
        out = layout.check_layout(tmp_path)
        assert out["is_workspace"] is False
        assert out["truncated"] is True
        assert len(out["proposed_mapping"]["projects"]) == layout._MAX_PROJECTS


class TestDriftAgainstLiveMolexp:
    """The constant must match the tree molexp's API actually materializes."""

    def test_materialized_workspace_matches_spec(self, tmp_path):
        pytest.importorskip("molexp", reason="molcrafts-molexp not installed")
        from molexp.workspace import Workspace

        ws = Workspace(root=tmp_path, name="probe")
        proj = ws.add_project("My Project")
        exp = proj.add_experiment("Exp One")
        exp.add_run(params={"x": 1})

        levels = {lvl.kind: lvl for lvl in layout.WORKSPACE_LAYOUT}

        proj_dir = tmp_path / "projects" / "my-project"
        assert (proj_dir / levels["project"].entity_file).is_file()
        assert levels["project"].container == "projects"

        exp_dir = proj_dir / "experiments" / "exp-one"
        assert (exp_dir / levels["experiment"].entity_file).is_file()
        assert levels["experiment"].container == "experiments"

        run_dirs = [d for d in (exp_dir / "runs").iterdir() if d.is_dir()]
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]
        assert run_dir.name.startswith("run-"), run_dir.name
        assert levels["run"].dir_template == "run-<run_id>"
        assert (run_dir / levels["run"].entity_file).is_file()

        # And the linter agrees the real, materialized tree conforms.
        result = layout.check_layout(tmp_path)
        assert result["is_workspace"] is True
        assert result["conforms"] is True, result["violations"]
