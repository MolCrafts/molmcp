"""Adoption core — survey, plan, ledger, transfer, runner.

These are the tools that moved out of the ``molexp`` harness plugin and into
molmcp: a data directory is surveyed, mapped onto ``Project → Experiment →
Run``, and transferred with per-file SHA-256 proof under a resumable ledger.

Everything here runs **without molexp installed**. The orchestration reaches
the science package through two injected seams — a workspace factory and an
ingest function — the same shape as the molvis provider's stage factory, so
the guarantees that matter (nothing overwritten, nothing unverified, a resume
that does not duplicate) are proven rather than assumed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from molmcp.providers.molexp.adopt import (
    ARTIFACTS_DIR,
    COPY,
    LEDGER_NAME,
    MOVE,
    AdoptionBlocked,
    AdoptionPlan,
    Entry,
    IngestOutcome,
    Ledger,
    LedgerMismatch,
    LogHit,
    RunSlot,
    TransferError,
    build_plan,
    ensure_compatible,
    read_ledger,
    resume_or_create,
    run_adoption,
    sha256_file,
    slugify,
    survey_source,
    transfer_file,
    verify_present,
    verify_tree,
    write_ledger,
)

# ----------------------------------------------------------------------
# Fixtures: a legacy tree, and the two molexp seams as fakes
# ----------------------------------------------------------------------


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """``proj/exp/{run-a,run-b}`` plus a stray note and a hidden dir."""
    root = tmp_path / "legacy"
    _write(root / "proj" / "exp" / "run-a" / "log.lammps", "thermo")
    _write(root / "proj" / "exp" / "run-a" / "params.json", '{"temp": 300}')
    _write(root / "proj" / "exp" / "run-b" / "log.lammps", "thermo b")
    _write(root / "proj" / "exp" / "run-b" / "traj.dcd", "frames")
    _write(root / "README.md", "notes about the campaign")
    _write(root / ".git" / "config", "[core]")
    return root


class FakeWorkspace:
    """Stand-in for ``molexp.workspace.Workspace`` (create-or-get only)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.projects: dict[str, str] = {}
        self.experiments: dict[tuple[str, str], str] = {}
        self.runs: list[RunSlot] = []

    def ensure_project(self, name: str) -> str:
        slug = slugify(name)
        self.projects[slug] = name
        (self.root / slug).mkdir(parents=True, exist_ok=True)
        return slug

    def ensure_experiment(self, project_id: str, name: str) -> str:
        slug = slugify(name)
        self.experiments[(project_id, slug)] = name
        (self.root / project_id / slug).mkdir(parents=True, exist_ok=True)
        return slug

    def ensure_run(
        self, project_id: str, experiment_id: str, params: dict[str, Any] | None
    ) -> RunSlot:
        run_id = f"run-{len(self.runs) + 1:03d}"
        run_dir = self.root / project_id / experiment_id / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run.json").write_text(
            json.dumps({"id": run_id, "params": params or {}}), encoding="utf-8"
        )
        slot = RunSlot(project_id, experiment_id, run_id, run_dir)
        self.runs.append(slot)
        return slot


class FakeWorkspaceFactory:
    """One workspace per target path, so a resume sees the same tree."""

    def __init__(self) -> None:
        self.made: dict[Path, FakeWorkspace] = {}
        self.calls = 0

    def __call__(self, target: Path, name: str) -> FakeWorkspace:
        self.calls += 1
        target.mkdir(parents=True, exist_ok=True)
        if target not in self.made:
            self.made[target] = FakeWorkspace(target)
        return self.made[target]


class FakeIngest:
    """Records which run dirs were ingested, so double-ingest is visible."""

    def __init__(self, records: int = 5) -> None:
        self.seen: list[Path] = []
        self.records = records

    def __call__(self, run_dir: Path, formats, csv_mapping) -> IngestOutcome:
        self.seen.append(run_dir)
        return IngestOutcome(ingested={"lammps_log": self.records})


@pytest.fixture
def factory() -> FakeWorkspaceFactory:
    return FakeWorkspaceFactory()


@pytest.fixture
def ingest() -> FakeIngest:
    return FakeIngest()


# ----------------------------------------------------------------------
# Survey
# ----------------------------------------------------------------------


class TestSurvey:
    def test_run_experiment_project_are_classified_bottom_up(self, legacy: Path):
        survey = survey_source(legacy)

        assert {n.rel for n in survey.by_kind("run")} == {
            "proj/exp/run-a",
            "proj/exp/run-b",
        }
        assert [n.rel for n in survey.by_kind("experiment")] == ["proj/exp"]
        assert [n.rel for n in survey.by_kind("project")] == ["proj"]

    def test_hidden_directories_are_excluded_not_walked(self, legacy: Path):
        survey = survey_source(legacy)

        assert ".git" in survey.excluded
        assert all(not n.rel.startswith(".git") for n in survey.nodes)

    def test_a_directory_of_notes_is_not_a_run(self, tmp_path: Path):
        _write(tmp_path / "docs" / "paper.tex", "\\documentclass")

        survey = survey_source(tmp_path)

        assert survey.node("docs").kind == "loose"

    def test_empty_files_are_reported_as_oddities(self, tmp_path: Path):
        _write(tmp_path / "run" / "log.lammps", "")

        survey = survey_source(tmp_path)

        assert ("empty_file", "run/log.lammps") in [
            (o.kind, o.path) for o in survey.oddities
        ]

    def test_a_symlink_out_of_the_tree_is_flagged_not_followed(self, tmp_path: Path):
        outside = _write(tmp_path / "outside" / "secret.dat", "private")
        root = tmp_path / "data"
        _write(root / "run" / "log.lammps", "thermo")
        (root / "run" / "link.dat").symlink_to(outside)

        survey = survey_source(root)

        assert "escaping_symlink" in {o.kind for o in survey.oddities}

    def test_a_broken_symlink_is_reported(self, tmp_path: Path):
        root = tmp_path / "data"
        (root / "run").mkdir(parents=True)
        _write(root / "run" / "log.lammps", "thermo")
        (root / "run" / "gone.dat").symlink_to(tmp_path / "nowhere")

        survey = survey_source(root)

        assert "broken_symlink" in {o.kind for o in survey.oddities}

    def test_max_depth_truncates_and_says_so(self, tmp_path: Path):
        _write(tmp_path / "a" / "b" / "c" / "log.lammps", "deep")

        survey = survey_source(tmp_path, max_depth=1)

        assert survey.truncated
        assert "depth_limit" in {o.kind for o in survey.oddities}

    def test_log_detection_is_delegated_to_the_injected_detector(self, legacy: Path):
        survey = survey_source(
            legacy, detector=lambda d: [LogHit("lammps_log", "log.lammps", "fake")]
        )

        runs = survey.by_kind("run")
        assert all(run.logs[0].format == "lammps_log" for run in runs)

    def test_a_missing_source_raises(self, tmp_path: Path):
        with pytest.raises(NotADirectoryError):
            survey_source(tmp_path / "nope")


# ----------------------------------------------------------------------
# Plan
# ----------------------------------------------------------------------


class TestPlan:
    def test_directory_names_become_project_experiment_run(self, legacy: Path):
        plan = build_plan(survey_source(legacy), target=legacy.parent / "ws")

        assert [p.name for p in plan.projects] == ["proj"]
        assert [e.name for e in plan.projects[0].experiments] == ["exp"]
        assert [r.run_id for r in plan.projects[0].experiments[0].runs] == [
            "run-a",
            "run-b",
        ]

    def test_flat_runs_borrow_the_source_name_for_their_project(self, tmp_path: Path):
        root = tmp_path / "flat"
        _write(root / "r1" / "log.lammps", "a")
        _write(root / "r2" / "log.lammps", "b")

        plan = build_plan(survey_source(root), target=tmp_path / "ws")

        assert [p.name for p in plan.projects] == ["flat"]
        assert [e.name for e in plan.projects[0].experiments] == ["default"]

    def test_params_json_seeds_run_parameters(self, legacy: Path):
        plan = build_plan(survey_source(legacy), target=legacy.parent / "ws")

        run_a = plan.projects[0].experiments[0].runs[0]
        assert run_a.parameters == {"temp": 300}

    def test_files_outside_a_run_are_listed_as_skipped(self, legacy: Path):
        plan = build_plan(survey_source(legacy), target=legacy.parent / "ws")

        assert "README.md" in {s.path for s in plan.skipped}

    def test_excluded_directories_are_listed_as_skipped(self, legacy: Path):
        plan = build_plan(survey_source(legacy), target=legacy.parent / "ws")

        assert ".git" in {s.path for s in plan.skipped}

    def test_a_run_owns_the_files_in_its_subdirectories(self, tmp_path: Path):
        root = tmp_path / "d"
        _write(root / "run" / "log.lammps", "thermo")
        _write(root / "run" / "tb" / "events.out.tfevents.1", "tb")

        plan = build_plan(survey_source(root), target=tmp_path / "ws")

        run = plan.projects[0].experiments[0].runs[0]
        assert "run/tb/events.out.tfevents.1" in run.files

    def test_default_target_is_a_sibling_never_inside_the_source(self, legacy: Path):
        plan = build_plan(survey_source(legacy))

        assert Path(plan.target).parent == legacy.parent
        assert legacy not in Path(plan.target).parents

    def test_colliding_run_slugs_are_reported_as_conflicts(self, tmp_path: Path):
        root = tmp_path / "d"
        _write(root / "exp" / "Run A" / "log.lammps", "a")
        _write(root / "exp" / "run.a" / "log.lammps", "b")

        plan = build_plan(survey_source(root), target=tmp_path / "ws")

        assert any("run id 'run-a'" in c for c in plan.conflicts)

    def test_an_edited_plan_round_trips_through_dicts(self, legacy: Path):
        plan = build_plan(survey_source(legacy), target=legacy.parent / "ws")

        restored = AdoptionPlan.from_dict(plan.to_dict())

        assert restored.projects == plan.projects
        assert restored.total_files == plan.total_files

    def test_slugify_falls_back_rather_than_producing_an_empty_id(self):
        assert slugify("  ??  ") == "default"


# ----------------------------------------------------------------------
# Ledger
# ----------------------------------------------------------------------


class TestLedger:
    def test_a_written_ledger_reads_back_identically(self, tmp_path: Path):
        ledger = Ledger(
            str(tmp_path / "src"),
            str(tmp_path / "dst"),
            COPY,
            (Entry("file", "a.log", str(tmp_path / "dst" / "a.log")),),
        )
        write_ledger(ledger)

        assert read_ledger(tmp_path / "dst") == ledger

    def test_writing_leaves_no_partial_file_behind(self, tmp_path: Path):
        write_ledger(Ledger(str(tmp_path / "s"), str(tmp_path / "d"), COPY))

        assert list((tmp_path / "d").glob("*.partial")) == []

    def test_no_ledger_reads_as_none(self, tmp_path: Path):
        assert read_ledger(tmp_path) is None

    def test_resume_keeps_finished_entries_and_replans_the_rest(self, tmp_path: Path):
        target = tmp_path / "dst"
        done = Entry("file", "a.log", str(target / "a.log"), status="verified")
        write_ledger(Ledger(str(tmp_path / "src"), str(target), COPY, (done,)))

        merged = resume_or_create(
            Ledger(
                str(tmp_path / "src"),
                str(target),
                COPY,
                (
                    Entry("file", "a.log", str(target / "a.log")),
                    Entry("file", "b.log", str(target / "b.log")),
                ),
            )
        )

        assert [e.status for e in merged.entries] == ["verified", "pending"]

    def test_a_ledger_for_another_mode_refuses_to_resume(self, tmp_path: Path):
        target = tmp_path / "dst"
        write_ledger(Ledger(str(tmp_path / "src"), str(target), COPY))

        with pytest.raises(LedgerMismatch):
            ensure_compatible(
                read_ledger(target),
                source=str(tmp_path / "src"),
                target=str(target),
                mode=MOVE,
            )

    def test_a_ledger_for_another_source_refuses_to_resume(self, tmp_path: Path):
        target = tmp_path / "dst"
        write_ledger(Ledger(str(tmp_path / "one"), str(target), COPY))

        with pytest.raises(LedgerMismatch):
            ensure_compatible(
                read_ledger(target),
                source=str(tmp_path / "two"),
                target=str(target),
                mode=COPY,
            )

    def test_a_future_ledger_version_refuses_to_resume(self, tmp_path: Path):
        target = tmp_path / "dst"
        write_ledger(Ledger(str(tmp_path / "s"), str(target), COPY, (), version=99))

        with pytest.raises(LedgerMismatch):
            ensure_compatible(
                read_ledger(target),
                source=str(tmp_path / "s"),
                target=str(target),
                mode=COPY,
            )


# ----------------------------------------------------------------------
# Transfer
# ----------------------------------------------------------------------


class TestTransfer:
    def test_a_copy_lands_byte_identical_and_reports_its_hash(self, tmp_path: Path):
        src = _write(tmp_path / "a.log", "thermo data")
        dst = tmp_path / "out" / "a.log"

        result = transfer_file(src, dst)

        assert dst.read_text() == "thermo data"
        assert result.sha256 == sha256_file(src)

    def test_copy_leaves_the_source_in_place(self, tmp_path: Path):
        src = _write(tmp_path / "a.log", "keep me")

        transfer_file(src, tmp_path / "out" / "a.log")

        assert src.is_file()

    def test_move_unlinks_the_source_only_after_the_copy_verified(self, tmp_path: Path):
        src = _write(tmp_path / "a.log", "move me")
        dst = tmp_path / "out" / "a.log"

        result = transfer_file(src, dst, mode=MOVE)

        assert not src.exists()
        assert dst.read_text() == "move me"
        assert result.moved

    def test_an_identical_destination_is_reused_not_rewritten(self, tmp_path: Path):
        src = _write(tmp_path / "a.log", "same")
        dst = _write(tmp_path / "out" / "a.log", "same")

        result = transfer_file(src, dst)

        assert result.reused

    def test_a_different_destination_is_refused_never_overwritten(self, tmp_path: Path):
        src = _write(tmp_path / "a.log", "new")
        dst = _write(tmp_path / "out" / "a.log", "precious")

        with pytest.raises(TransferError):
            transfer_file(src, dst)

        assert dst.read_text() == "precious"

    def test_a_symlink_is_recreated_as_a_link_not_dereferenced(self, tmp_path: Path):
        target = _write(tmp_path / "real.dat", "payload")
        link = tmp_path / "link.dat"
        link.symlink_to(target)

        transfer_file(link, tmp_path / "out" / "link.dat")

        assert (tmp_path / "out" / "link.dat").is_symlink()

    def test_an_unknown_mode_is_rejected(self, tmp_path: Path):
        src = _write(tmp_path / "a.log", "x")

        with pytest.raises(ValueError):
            transfer_file(src, tmp_path / "out" / "a.log", mode="teleport")

    def test_a_truncated_destination_fails_the_presence_check(self, tmp_path: Path):
        path = _write(tmp_path / "a.log", "12345")

        assert verify_present([(path, 99)]) != []

    def test_a_rewritten_destination_fails_the_hash_audit(self, tmp_path: Path):
        path = _write(tmp_path / "a.log", "original")
        digest = sha256_file(path)
        path.write_text("tampered", encoding="utf-8")

        assert verify_tree([(path, digest)]) != []

    def test_an_intact_destination_passes_the_hash_audit(self, tmp_path: Path):
        path = _write(tmp_path / "a.log", "original")

        assert verify_tree([(path, sha256_file(path))]) == []


# ----------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------


def _adopt(legacy: Path, target: Path, factory, ingest, **kwargs):
    plan = build_plan(survey_source(legacy), target=target)
    return run_adoption(plan, workspace_factory=factory, ingest=ingest, **kwargs)


class TestRunAdoption:
    def test_every_run_file_lands_under_the_run_artifacts_directory(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        outcome = _adopt(legacy, tmp_path / "ws", factory, ingest)

        run_dir = Path(outcome.runs[0]["run_dir"])
        assert (run_dir / ARTIFACTS_DIR / "log.lammps").read_text() == "thermo"

    def test_a_clean_adoption_reports_ok_with_no_problems(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        outcome = _adopt(legacy, tmp_path / "ws", factory, ingest)

        assert outcome.ok
        assert outcome.problems == ()

    def test_the_ledger_records_every_transferred_file(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        _adopt(legacy, tmp_path / "ws", factory, ingest)

        ledger = read_ledger(tmp_path / "ws")
        assert [e.status for e in ledger.of_kind("file")] == ["verified"] * 4

    def test_the_ledger_lands_inside_the_target_workspace(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        _adopt(legacy, tmp_path / "ws", factory, ingest)

        assert (tmp_path / "ws" / LEDGER_NAME).is_file()

    def test_copy_mode_leaves_the_whole_source_intact(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        _adopt(legacy, tmp_path / "ws", factory, ingest)

        assert (legacy / "proj" / "exp" / "run-a" / "log.lammps").is_file()

    def test_move_mode_drains_the_source_files(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        _adopt(legacy, tmp_path / "ws", factory, ingest, mode=MOVE)

        assert not (legacy / "proj" / "exp" / "run-a" / "log.lammps").exists()

    def test_re_running_does_not_create_a_second_set_of_runs(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        _adopt(legacy, tmp_path / "ws", factory, ingest)
        _adopt(legacy, tmp_path / "ws", factory, ingest)

        assert len(factory.made[tmp_path / "ws"].runs) == 2

    def test_re_running_reuses_verified_files_instead_of_recopying(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        _adopt(legacy, tmp_path / "ws", factory, ingest)
        second = _adopt(legacy, tmp_path / "ws", factory, ingest)

        assert second.files_transferred == 0

    def test_nothing_is_ingested_unless_asked(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        _adopt(legacy, tmp_path / "ws", factory, ingest)

        assert ingest.seen == []

    def test_requested_formats_are_ingested_once_per_run(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        outcome = _adopt(
            legacy,
            tmp_path / "ws",
            factory,
            ingest,
            ingest_formats=frozenset({"lammps_log"}),
        )

        assert len(ingest.seen) == 2
        assert all(report["ok"] for report in outcome.ingest.values())

    def test_a_resumed_adoption_never_ingests_a_run_twice(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        formats = frozenset({"lammps_log"})
        _adopt(legacy, tmp_path / "ws", factory, ingest, ingest_formats=formats)
        _adopt(legacy, tmp_path / "ws", factory, ingest, ingest_formats=formats)

        assert len(ingest.seen) == 2

    def test_a_failing_ingest_does_not_fail_the_adoption(
        self, legacy: Path, tmp_path: Path, factory
    ):
        def boom(run_dir, formats, csv_mapping):
            raise RuntimeError("tensorboard is not installed")

        outcome = _adopt(
            legacy,
            tmp_path / "ws",
            factory,
            boom,
            ingest_formats=frozenset({"tensorboard"}),
        )

        assert outcome.ok
        assert all(not report["ok"] for report in outcome.ingest.values())

    def test_an_unknown_ingest_format_is_refused_before_anything_moves(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        with pytest.raises(AdoptionBlocked):
            _adopt(
                legacy,
                tmp_path / "ws",
                factory,
                ingest,
                ingest_formats=frozenset({"wandb"}),
            )

        assert not (tmp_path / "ws").exists()

    def test_a_target_inside_the_source_is_refused(self, legacy: Path, factory, ingest):
        with pytest.raises(AdoptionBlocked):
            _adopt(legacy, legacy / "inner", factory, ingest)

    def test_a_source_that_is_already_a_workspace_is_refused(
        self, tmp_path: Path, factory, ingest
    ):
        source = tmp_path / "ws-src"
        _write(source / "workspace.json", "{}")

        with pytest.raises(AdoptionBlocked):
            _adopt(source, tmp_path / "out", factory, ingest)

    def test_an_unknown_mode_is_refused(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        with pytest.raises(AdoptionBlocked):
            _adopt(legacy, tmp_path / "ws", factory, ingest, mode="rsync")

    def test_a_plan_with_conflicts_is_refused(self, tmp_path: Path, factory, ingest):
        root = tmp_path / "d"
        _write(root / "exp" / "Run A" / "log.lammps", "a")
        _write(root / "exp" / "run.a" / "log.lammps", "b")

        with pytest.raises(AdoptionBlocked):
            _adopt(root, tmp_path / "ws", factory, ingest)

    def test_skipped_source_files_are_reported_in_the_outcome(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        outcome = _adopt(legacy, tmp_path / "ws", factory, ingest)

        assert "README.md" in {entry["path"] for entry in outcome.skipped}

    def test_copy_mode_says_the_source_is_still_there(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        outcome = _adopt(legacy, tmp_path / "ws", factory, ingest)

        assert outcome.to_dict()["source_intact"] is True

    def test_a_vanished_source_file_is_reported_not_silently_dropped(
        self, legacy: Path, tmp_path: Path, factory, ingest
    ):
        plan = build_plan(survey_source(legacy), target=tmp_path / "ws")
        (legacy / "proj" / "exp" / "run-b" / "traj.dcd").unlink()

        outcome = run_adoption(plan, workspace_factory=factory, ingest=ingest)

        assert not outcome.ok
        assert any("traj.dcd" in problem for problem in outcome.problems)
