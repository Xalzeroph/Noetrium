from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from tests.test_unified_operator_entrypoint_v1 import (
    workspace,
    git_repository,
    GitRunner,
)
from noetrium_platform.composition.operator.cli_context import (
    Workspace,
    attach,
    freeze_new_run,
    version_summary,
)
from noetrium_platform.composition.operator.wiring import entrypoint as cli


def recorded(tmp_path):
    ws, root, roots = workspace(tmp_path)
    state = tmp_path / "existing-state"
    state.mkdir()
    row = attach(ws, "existing", root, state, roots)
    return Workspace.load(ws.path), root, roots, row


def owned_sources(tmp_path):
    ws, root, roots = workspace(tmp_path)
    for repo in (root, *roots):
        git_repository(repo)
    return ws, root, roots


@pytest.mark.parametrize(
    "tokens",
    [
        ["help", "research", "runs"],
        ["research", "versions"],
        ["help", "research", "versions", "capture"],
        ["help", "research", "checkpoints", "show"],
        ["guide", "--help"],
    ],
)
def test_new_group_help_never_reads_workspace_or_constructs_runtime(
    tokens, monkeypatch, capsys
):
    monkeypatch.setattr(
        cli, "_command_runner", lambda: pytest.fail("help constructed a runtime")
    )
    monkeypatch.setenv("NOETRIUM_WORKSPACE_FILE", "/missing/help-only.json")
    try:
        code = cli.main(tokens)
    except SystemExit as exc:
        code = exc.code
    assert code == 0
    assert "noetrium" in capsys.readouterr().out


def test_history_survives_removing_a_working_project_registration(
    tmp_path, monkeypatch, capsys
):
    ws, root, roots, row = recorded(tmp_path)
    ws.update(lambda data: data.update(projects={}, default_projects=[]))
    monkeypatch.setattr(
        cli, "_command_runner", lambda: pytest.fail("history constructed runtime")
    )
    assert (
        cli.main(["research", "runs", "show", "existing", "--workspace", str(ws.path)])
        == 0
    )
    assert (
        cli.main(
            ["research", "status", "--run", "existing", "--workspace", str(ws.path)]
        )
        == 0
    )
    assert "existing" in capsys.readouterr().out


def test_labels_and_selection_only_change_operational_defaults(
    tmp_path, monkeypatch, capsys
):
    ws, root, roots, row = recorded(tmp_path)
    before = ws.record_path("existing").read_bytes()
    monkeypatch.setattr(
        cli, "_command_runner", lambda: pytest.fail("metadata started an execution")
    )
    for tokens in (
        ["label", "existing", "formal", "投稿"],
        ["select", "existing"],
        ["label", "existing", "--clear"],
    ):
        assert cli.main(["research", "runs", *tokens, "--workspace", str(ws.path)]) == 0
    assert ws.record_path("existing").read_bytes() == before
    assert Workspace.load(ws.path).data["run_labels"]["existing"] == []


def test_capture_preserves_the_current_active_run(tmp_path, monkeypatch):
    ws, root, roots = owned_sources(tmp_path)
    state = tmp_path / "active"
    state.mkdir()
    attach(ws, "active", root, state, roots)

    @contextmanager
    def runner():
        yield GitRunner()

    monkeypatch.setattr(cli, "_command_runner", runner)
    assert (
        cli.main(
            [
                "research",
                "versions",
                "capture",
                "--name",
                "prepared",
                "--workspace",
                str(ws.path),
            ]
        )
        == 0
    )
    current = Workspace.load(ws.path)
    assert current.active_record(["a", "b"])["name"] == "active"
    captured = current.active_record((), "prepared")
    assert captured["launch_phase"] == "prepared"
    assert captured["owner"] is None
    assert version_summary(captured)["sources"][0]["revision"]


def test_explicit_committed_source_excludes_working_edits(tmp_path):
    ws, root, roots = owned_sources(tmp_path)
    (roots[0] / "research.py").write_text("# pending edits")
    names, selected = ws.roots()
    row = freeze_new_run(
        ws, names, selected, GitRunner(), name="committed", committed=True
    )
    assert (
        Path(row["project_roots"][0], "research.py").read_text()
        == "# research source\n"
    )
    assert (roots[0] / "research.py").read_text() == "# pending edits"


def test_explicit_revisions_are_resolved_before_allocating_state(tmp_path):
    ws, root, roots = owned_sources(tmp_path)
    names, selected = ws.roots()
    with pytest.raises(RuntimeError, match="snapshot failed"):
        freeze_new_run(
            ws,
            names,
            selected,
            GitRunner(),
            name="bad-ref",
            revisions=["a=missing-ref"],
        )
    assert not ws.record_path("bad-ref").exists()
    assert not (ws.resolve("state") / "runs/bad-ref").exists()


def test_shared_repository_rejects_conflicting_paper_versions(tmp_path):
    ws, root, roots = owned_sources(tmp_path)
    # Give two aliases for two subdirectories of one committed paper repository.
    repo = roots[0]
    one = repo / "one"
    two = repo / "two"
    one.mkdir()
    two.mkdir()
    for p in (one, two):
        (p / "project.manifest.json").write_text("{}")
    runner = GitRunner()
    runner.run(("git", "-C", str(repo), "add", "."))
    runner.run(("git", "-C", str(repo), "commit", "-m", "papers"))
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    (one / "changed.txt").write_text("next")
    runner.run(("git", "-C", str(repo), "add", "."))
    runner.run(("git", "-C", str(repo), "commit", "-m", "next"))
    ws = ws.update(lambda data: data["projects"].update(a=str(one), b=str(two)))
    names, selected = ws.roots()
    with pytest.raises(ValueError, match="conflicting revisions"):
        freeze_new_run(
            ws,
            names,
            selected,
            runner,
            name="conflicting",
            revisions=["a=" + head, "b=HEAD"],
        )
    assert not ws.record_path("conflicting").exists()


def test_rerun_pins_the_old_version_pair_and_allocates_fresh_state(tmp_path):
    ws, root, roots = owned_sources(tmp_path)
    names, selected = ws.roots()
    first = freeze_new_run(ws, names, selected, GitRunner(), name="original")
    for repo in (root, *roots):
        (repo / "next.txt").write_text("new revision")
        GitRunner().run(("git", "-C", str(repo), "add", "."))
        GitRunner().run(("git", "-C", str(repo), "commit", "-m", "next"))
    second = freeze_new_run(
        Workspace.load(ws.path),
        (),
        (),
        GitRunner(),
        name="reproduction",
        source_record=first,
    )
    assert second["parent_run"] == "original"
    assert second["data_root"] != first["data_root"]
    assert second["selected_roots"] == first["selected_roots"]
    assert [item["revision"] for item in version_summary(second)["sources"]] == [
        item["revision"] for item in version_summary(first)["sources"]
    ]
    assert not Path(second["data_root"]).exists()


def test_start_is_once_only_and_updates_the_launcher_owner(tmp_path, monkeypatch):
    ws, root, roots = owned_sources(tmp_path)
    names, selected = ws.roots()
    freeze_new_run(ws, names, selected, GitRunner(), name="ready")
    calls = []

    class Runner:
        def run(self, argv, **kwargs):
            calls.append(argv)
            claimed = Workspace.load(ws.path).active_record((), "ready")
            assert claimed["owner"] is not None
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    @contextmanager
    def runner():
        yield Runner()

    monkeypatch.setattr(cli, "_command_runner", runner)
    tokens = ["research", "runs", "start", "ready", "--workspace", str(ws.path)]
    assert cli.main(tokens) == 0
    assert cli.main(tokens) == 2
    assert len(calls) == 1
    result = Workspace.load(ws.path).active_record((), "ready")
    assert result["owner"] is None and result["last_exit"] == 0


def test_live_run_resume_does_not_spawn_a_second_driver(tmp_path, monkeypatch):
    ws, root, roots, row = recorded(tmp_path)
    from noetrium_platform.composition.operator.cli_context import owner_identity

    ws.update_record("existing", {"owner": owner_identity()})

    class Runner:
        def run(self, *args, **kwargs):
            pytest.fail("duplicate driver was spawned")

    @contextmanager
    def runner():
        yield Runner()

    monkeypatch.setattr(cli, "_command_runner", runner)
    assert (
        cli.main(
            ["research", "resume", "--run", "existing", "--workspace", str(ws.path)]
        )
        == 2
    )


def test_guide_reports_observations_without_starting_any_execution(
    tmp_path, monkeypatch, capsys
):
    ws, root, roots, row = recorded(tmp_path)
    monkeypatch.setattr(
        cli, "_command_runner", lambda: pytest.fail("guide started services")
    )
    assert cli.main(["guide", "all", "--workspace", str(ws.path)]) == 0
    output = capsys.readouterr().out
    assert all(
        stage + ":" in output
        for stage in (
            "setup",
            "pilot",
            "formal",
            "recover",
            "analyze",
            "write",
            "submit",
            "revise",
            "archive",
        )
    )


def checkpoint_fixture(tmp_path):
    ws, root, roots, row = recorded(tmp_path)
    from noetrium_platform.composition.research_checkpoint import (
        ResearchGraphCheckpoint,
    )
    from noetrium_platform.foundation.kernel.kernel import canonical_bytes

    proof = ResearchGraphCheckpoint(
        execution_cut_id="a" * 64,
        graph_digest="b" * 64,
        research_revision_digest="c" * 64,
        snapshot_generation=1,
        control_generation=1,
        control_phase="paused",
        selected_node_ids=("node",),
        nodes=({"graph_node_id": "node", "state": "succeeded"},),
    )
    path = (
        Path(row["data_root"])
        / "projects/root-sets/set/research/graph-checkpoints/objects"
        / (proof.checkpoint_digest + ".json")
    )
    path.parent.mkdir(parents=True)
    path.write_bytes(canonical_bytes(proof.to_document()))
    return ws, proof, path


def test_checkpoint_show_uses_the_canonical_reader_without_a_writer(
    tmp_path, monkeypatch, capsys
):
    ws, proof, path = checkpoint_fixture(tmp_path)
    from noetrium_platform.composition.research_checkpoint_store import (
        DirectoryResearchGraphCheckpointStore,
    )

    monkeypatch.setattr(
        DirectoryResearchGraphCheckpointStore,
        "__init__",
        lambda *a, **k: pytest.fail("created writer store"),
    )
    before = path.read_bytes()
    assert (
        cli.main(
            [
                "research",
                "checkpoints",
                "show",
                proof.checkpoint_digest,
                "--run",
                "existing",
                "--workspace",
                str(ws.path),
            ]
        )
        == 0
    )
    assert (
        json.loads(capsys.readouterr().out)[0]["checkpoint_digest"]
        == proof.checkpoint_digest
    )
    assert path.read_bytes() == before


def test_checkpoint_tamper_cannot_be_reported_as_a_valid_checkpoint(tmp_path, capsys):
    ws, proof, path = checkpoint_fixture(tmp_path)
    data = json.loads(path.read_text())
    data["control_phase"] = "active"
    path.write_text(json.dumps(data))
    assert (
        cli.main(
            [
                "research",
                "checkpoints",
                "list",
                "--run",
                "existing",
                "--workspace",
                str(ws.path),
            ]
        )
        == 2
    )
    assert "checkpoint" in capsys.readouterr().err.lower()


def test_immutable_source_binding_fields_cannot_be_edited(tmp_path):
    ws, root, roots, row = recorded(tmp_path)
    with pytest.raises(ValueError, match="immutable"):
        ws.update_record("existing", {"platform_root": "/other"})


@pytest.mark.parametrize("action", ["resume", "retry"])
def test_recovery_driver_keeps_ownership_through_teardown_and_streams_to_disk(
    tmp_path, monkeypatch, action
):
    ws, root, roots, row = recorded(tmp_path)
    observed = []

    class Runner:
        def run(self, argv, **kwargs):
            assert argv[:2] == ("sh", "-c")
            assert '>>"$NOETRIUM_LAUNCH_LOG" 2>&1' in argv[2]
            assert kwargs["environment"]["NOETRIUM_LAUNCH_LOG"].endswith("launch.log")
            observed.append(action)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    @contextmanager
    def runner():
        yield Runner()
        current = Workspace.load(ws.path).active_record((), "existing")
        assert current["owner"] is not None
        with pytest.raises((BlockingIOError, RuntimeError)):
            with ws.execution_guard("existing"):
                pytest.fail("ownership lock released before supervisor teardown")

    monkeypatch.setattr(cli, "_command_runner", runner)
    assert (
        cli.main(["research", action, "--run", "existing", "--workspace", str(ws.path)])
        == 0
    )
    assert observed == [action]
    assert Workspace.load(ws.path).active_record((), "existing")["owner"] is None


def test_live_owner_rejection_constructs_no_runtime(tmp_path, monkeypatch):
    ws, root, roots, row = recorded(tmp_path)
    from noetrium_platform.composition.operator.cli_context import owner_identity

    ws.update_record("existing", {"owner": owner_identity()})
    monkeypatch.setattr(
        cli,
        "_command_runner",
        lambda: pytest.fail("live-owner rejection opened a runtime"),
    )
    assert (
        cli.main(
            ["research", "resume", "--run", "existing", "--workspace", str(ws.path)]
        )
        == 2
    )


def test_paper_set_allocation_lock_is_released_before_execution(tmp_path, monkeypatch):
    ws, root, roots = owned_sources(tmp_path)

    @contextmanager
    def runner():
        yield GitRunner()

    def backend(row, command, arguments, runner, *, launch=False):
        assert launch
        with ws.launch_guard(ws.roots()[0]):
            pass
        return 0

    monkeypatch.setattr(cli, "_command_runner", runner)
    monkeypatch.setattr(cli, "_backend", backend)
    assert (
        cli.main(["run", "--new", "--name", "independent", "--workspace", str(ws.path)])
        == 0
    )


def test_supervisor_teardown_failure_records_interrupted_owner(tmp_path, monkeypatch):
    ws, root, roots, row = recorded(tmp_path)

    @contextmanager
    def runner():
        yield object()
        raise RuntimeError("teardown failed")

    monkeypatch.setattr(cli, "_command_runner", runner)
    monkeypatch.setattr(cli, "_backend", lambda *args, **kwargs: 0)
    with pytest.raises(RuntimeError, match="teardown failed"):
        cli._execute_record(ws, row, "resume", [])
    result = Workspace.load(ws.path).active_record((), "existing")
    assert result["owner"] is not None
    assert result["launch_phase"] == "interrupted"
