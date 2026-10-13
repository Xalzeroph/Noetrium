from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest

from noetrium_platform.composition.operator.cli_context import (
    initialize_workspace,
    Workspace,
)
from noetrium_platform.composition.operator.cli_context import (
    attach,
    freeze_new_run,
    graph_summary,
    existing_record,
)
from noetrium_platform.composition.operator.wiring import entrypoint as cli


def paper(path, identity):
    path.mkdir(parents=True)
    (path / "project.manifest.json").write_text(json.dumps({"name": identity}))
    (path / "research.py").write_text("# research source\n")
    return path


def platform(path):
    (path / "deploy").mkdir(parents=True)
    backend = path / "deploy/noetrium"
    backend.write_text("#!/bin/sh\nexit 0\n")
    backend.chmod(0o755)
    return path


def workspace(tmp_path):
    root = platform(tmp_path / "platform")
    first = paper(tmp_path / "paper a", "alpha")
    second = paper(tmp_path / "paper b", "beta")
    ws = initialize_workspace(
        tmp_path / "noetrium.workspace.json",
        platform_root=root,
        data_root="state",
        projects=["a=" + str(first), "b=" + str(second)],
    )
    return ws, root, (first, second)


class GitRunner:
    def run(self, argv, **kwargs):
        result = subprocess.run(
            argv,
            cwd=kwargs.get("cwd"),
            env=kwargs.get("environment"),
            text=True,
            capture_output=True,
            check=False,
        )
        return SimpleNamespace(
            returncode=result.returncode, stdout=result.stdout, stderr=result.stderr
        )


def git_repository(root):
    runner = GitRunner()
    for args in [
        ("init",),
        ("config", "user.email", "test@example.invalid"),
        ("config", "user.name", "CLI Test"),
        ("add", "."),
        ("commit", "-m", "initial"),
    ]:
        result = runner.run(("git", "-C", str(root), *args))
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "path",
    [
        [],
        ["help"],
        ["help", "research"],
        ["research", "run", "--help"],
        ["help", "diagnose", "failure", "why"],
        ["help", "infra", "docker", "start"],
        ["dev", "algorithm", "scan", "--help"],
        ["workspace", "init", "--help"],
        ["project", "use", "--help"],
    ],
)
def test_help_never_constructs_runtime(path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "_command_runner", lambda: pytest.fail("help constructed runtime")
    )
    try:
        result = cli.main(path)
    except SystemExit as exc:
        result = exc.code
    assert result == 0
    assert "noetrium" in capsys.readouterr().out


@pytest.mark.parametrize(
    "command", ["doctor", "inspect", "preflight", "manage", "docker", "algorithm"]
)
def test_removed_flat_commands_are_rejected(command):
    with pytest.raises(SystemExit) as raised:
        cli.main([command])
    assert raised.value.code == 2


def test_multi_paper_selection_is_order_and_alias_independent(tmp_path):
    ws, _, roots = workspace(tmp_path)
    assert (
        ws.group_key(["a", "b"])
        == ws.group_key(["b", "a"])
        == ws.group_key([str(p) for p in roots])
    )
    assert ws.roots()[1] == roots
    with pytest.raises(ValueError, match="duplicate"):
        ws.roots(["a", str(roots[0])])


def test_init_does_not_replace_existing_defaults(tmp_path):
    ws, root, roots = workspace(tmp_path)
    before = ws.path.read_bytes()
    with pytest.raises(FileExistsError):
        initialize_workspace(
            ws.path, platform_root=root, data_root="other", projects=[str(roots[0])]
        )
    assert ws.path.read_bytes() == before


def test_attach_rejects_different_paper_identity_without_binding(tmp_path):
    ws, root, roots = workspace(tmp_path)
    wrong = paper(tmp_path / "wrong", "different")
    data = tmp_path / "old-state"
    data.mkdir()
    with pytest.raises(ValueError, match="identities"):
        attach(ws, "existing", root, data, [roots[0], wrong])
    assert Workspace.load(ws.path).data["active_runs"] == {}


def test_active_status_and_run_are_read_only_even_when_owner_exited(
    tmp_path, monkeypatch, capsys
):
    ws, root, roots = workspace(tmp_path)
    data = tmp_path / "existing"
    data.mkdir()
    attach(ws, "existing", root, data, roots)
    monkeypatch.setattr(
        cli,
        "_command_runner",
        lambda: pytest.fail("status or run tried to start a process"),
    )
    for args in (["research", "status"], ["run"]):
        assert cli.main([*args, "--workspace", str(ws.path)]) == 0
    assert "Existing run selected" in capsys.readouterr().out


def test_status_counts_only_the_active_durable_cut(tmp_path):
    db = tmp_path / "projects/root-sets/set/research/graph.v5.sqlite3"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE research_graph_nodes (execution_id TEXT,state TEXT)")
        conn.execute("CREATE TABLE research_graph_active_cuts (cut_id TEXT)")
        conn.executemany(
            "INSERT INTO research_graph_nodes VALUES (?,?)",
            [("old", "FAILED"), ("new", "RUNNING"), ("new", "SUCCEEDED")],
        )
        conn.execute("INSERT INTO research_graph_active_cuts VALUES ('new')")
    assert graph_summary({"data_root": str(tmp_path)}) == {"RUNNING": 1, "SUCCEEDED": 1}


def test_resume_routes_all_papers_to_the_recorded_backend_and_environment(
    tmp_path, monkeypatch
):
    ws, working, roots = workspace(tmp_path)
    frozen = platform(tmp_path / "frozen-platform")
    frozen_roots = (
        paper(tmp_path / "frozen-a", "alpha"),
        paper(tmp_path / "frozen-b", "beta"),
    )
    state = tmp_path / "active-state"
    state.mkdir()
    env = tmp_path / "frozen.env"
    env.write_text("SECRET=value\n")
    attach(ws, "active", frozen, state, frozen_roots, env)
    calls = []

    class Runner:
        def run(self, argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    @contextmanager
    def runner():
        yield Runner()

    monkeypatch.setattr(cli, "_command_runner", runner)
    assert cli.main(["research", "resume", "--workspace", str(ws.path)]) == 0
    argv, kwargs = calls[0]
    assert argv[:2] == ("sh", "-c")
    assert argv[4:] == (
        str(frozen / "deploy/noetrium"),
        "resume",
        "--project",
        str(frozen_roots[0]),
        "--project",
        str(frozen_roots[1]),
    )
    assert kwargs["environment"]["NOETRIUM_DATA_ROOT"] == str(state)
    assert kwargs["environment"]["NOETRIUM_CONTROL_ENV_FILE"] == str(env)
    assert str(working) not in argv


def test_recorded_environment_override_cannot_retarget_execution(tmp_path, monkeypatch):
    ws, root, roots = workspace(tmp_path)
    data = tmp_path / "old"
    data.mkdir()
    attach(ws, "old", root, data, roots)
    monkeypatch.setattr(
        cli, "_command_runner", lambda: pytest.fail("override spawned a process")
    )
    assert (
        cli.main(
            [
                "research",
                "resume",
                "--workspace",
                str(ws.path),
                "--data-root",
                str(tmp_path / "other"),
            ]
        )
        == 2
    )


def test_logs_tail_is_read_only(tmp_path, monkeypatch, capsys):
    ws, root, roots = workspace(tmp_path)
    data = tmp_path / "old"
    data.mkdir()
    (data / "launch.log").write_text("one\ntwo\nthree\n")
    attach(ws, "old", root, data, roots)
    monkeypatch.setattr(
        cli, "_command_runner", lambda: pytest.fail("logs constructed runtime")
    )
    assert (
        cli.main(["research", "logs", "--workspace", str(ws.path), "--lines", "2"]) == 0
    )
    assert capsys.readouterr().out == "two\nthree\n"


def test_git_snapshot_freezes_two_papers_and_private_environment(tmp_path):
    ws, root, roots = workspace(tmp_path)
    for repo in (root, *roots):
        git_repository(repo)
    env = tmp_path / "control.env"
    env.write_text("SECRET=private\n")
    names, selected = ws.roots()
    row = freeze_new_run(
        ws, names, selected, GitRunner(), name="frozen", env_file=str(env)
    )
    assert len(row["source_commits"]) == 3
    assert len(row["project_roots"]) == 2
    assert Path(row["env_file"]).read_text() == "SECRET=private\n"
    assert Path(row["env_file"]).stat().st_mode & 0o777 == 0o600
    for frozen, original in zip(row["project_roots"], roots):
        (original / "research.py").write_text("# changed later\n")
        assert Path(frozen, "research.py").read_text() == "# research source\n"
    reloaded = Workspace.load(ws.path)
    assert existing_record(reloaded, ["b", "a"])["name"] == "frozen"
    assert existing_record(reloaded, [str(p) for p in roots])["name"] == "frozen"


def test_dirty_source_does_not_publish_a_run(tmp_path):
    ws, root, roots = workspace(tmp_path)
    for repo in (root, *roots):
        git_repository(repo)
    (roots[1] / "research.py").write_text("# dirty\n")
    names, selected = ws.roots()
    with pytest.raises(ValueError, match="commit"):
        freeze_new_run(ws, names, selected, GitRunner(), name="bad")
    assert not ws.record_path("bad").exists()
    assert not (ws.resolve("state") / "runs/bad").exists()


def test_new_name_collision_preserves_existing_run(tmp_path):
    ws, root, roots = workspace(tmp_path)
    for repo in (root, *roots):
        git_repository(repo)
    names, selected = ws.roots()
    first = freeze_new_run(ws, names, selected, GitRunner(), name="first")
    before = ws.record_path("first").read_bytes()
    with pytest.raises(FileExistsError):
        freeze_new_run(
            Workspace.load(ws.path), names, selected, GitRunner(), name="first"
        )
    assert ws.record_path("first").read_bytes() == before
    assert existing_record(Workspace.load(ws.path), names) == first


def test_untracked_source_cannot_silently_disappear_from_snapshot(tmp_path):
    ws, root, roots = workspace(tmp_path)
    for repo in (root, *roots):
        git_repository(repo)
    (roots[0] / "helper.py").write_text("# not committed")
    names, selected = ws.roots()
    with pytest.raises(ValueError, match="untracked source"):
        freeze_new_run(ws, names, selected, GitRunner(), name="untracked")
    assert not ws.record_path("untracked").exists()


def test_two_papers_in_one_repository_share_a_single_frozen_worktree(tmp_path):
    root = platform(tmp_path / "monorepo")
    roots = (paper(root / "papers/alpha", "alpha"), paper(root / "papers/beta", "beta"))
    git_repository(root)
    ws = initialize_workspace(
        tmp_path / "noetrium.workspace.json",
        platform_root=root,
        data_root="state",
        projects=["a=" + str(roots[0]), "b=" + str(roots[1])],
    )
    names, selected = ws.roots()
    row = freeze_new_run(ws, names, selected, GitRunner(), name="shared")
    assert len(row["source_commits"]) == 1
    assert row["project_roots"] == [
        str(Path(row["platform_root"]) / "papers/alpha"),
        str(Path(row["platform_root"]) / "papers/beta"),
    ]
    assert all(Path(p, "research.py").is_file() for p in row["project_roots"])


def test_duplicate_run_selection_does_not_contend_with_its_live_launch_lock(
    tmp_path, monkeypatch
):
    ws, root, roots = workspace(tmp_path)
    data = tmp_path / "live"
    data.mkdir()
    attach(ws, "live", root, data, roots)
    monkeypatch.setattr(
        cli, "_command_runner", lambda: pytest.fail("selected run was relaunched")
    )
    with ws.launch_guard(ws.roots()[0]):
        assert cli.main(["run", "--workspace", str(ws.path)]) == 0


def test_operator_json_projects_scope_sets_deterministically():
    from noetrium_platform.product.operator.api.json_rendering import render_json

    assert json.loads(render_json({"scopes": frozenset(["z", "a"])})) == {
        "scopes": ["a", "z"]
    }
    with pytest.raises((TypeError, ValueError)):
        render_json({"scopes": frozenset([float("nan")])})


def test_log_tail_handles_unicode_and_unterminated_final_line(tmp_path):
    from noetrium_platform.composition.operator.cli_context import read_log_tail

    path = tmp_path / "large.log"
    path.write_text(("earlier record\n" * 20000) + "中文记录\nlast")
    assert read_log_tail(path, 2) == ["中文记录\n", "last"]


def test_published_provenance_retains_frozen_sources_if_default_update_fails(
    tmp_path, monkeypatch
):
    ws, root, roots = workspace(tmp_path)
    for repo in (root, *roots):
        git_repository(repo)
    names, selected = ws.roots()

    def fail_update(self, operation):
        raise OSError("simulated workspace publication failure")

    monkeypatch.setattr(Workspace, "update", fail_update)
    with pytest.raises(OSError, match="publication failure"):
        freeze_new_run(ws, names, selected, GitRunner(), name="retained")
    record = json.loads(ws.record_path("retained").read_text())
    assert all(Path(p).is_dir() for p in record["project_roots"])
    assert Path(record["platform_root"]).is_dir()


@pytest.mark.parametrize(
    "command",
    [
        ["infra", "build", "--", "--profiles", "minecraft"],
        ["infra", "plan"],
        ["infra", "requirements"],
        ["infra", "audit-finalization"],
        ["infra", "docker", "status"],
        ["project", "create", "new-paper"],
    ],
)
def test_non_research_commands_do_not_receive_the_default_paper_set(
    command, tmp_path, monkeypatch
):
    ws, root, roots = workspace(tmp_path)
    calls = []

    class Runner:
        def run(self, argv, **kwargs):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    @contextmanager
    def runner():
        yield Runner()

    monkeypatch.setattr(cli, "_command_runner", runner)
    tokens = (
        [*command[:3], "--workspace", str(ws.path), *command[3:]]
        if command[:2] == ["infra", "docker"]
        else [*command[:2], "--workspace", str(ws.path), *command[2:]]
    )
    assert cli.main(tokens) == 0
    assert "--project" not in calls[0]
    if "minecraft" in command:
        assert calls[0][-2:] == ("--profiles", "minecraft")


def test_infrastructure_is_available_before_any_paper_is_registered(
    tmp_path, monkeypatch
):
    root = platform(tmp_path / "platform")
    ws = initialize_workspace(
        tmp_path / "noetrium.workspace.json",
        platform_root=root,
        data_root="state",
        projects=[],
    )

    class Runner:
        def run(self, argv, **kwargs):
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    @contextmanager
    def runner():
        yield Runner()

    monkeypatch.setattr(cli, "_command_runner", runner)
    assert cli.main(["infra", "docker", "status", "--workspace", str(ws.path)]) == 0
