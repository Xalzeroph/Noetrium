from __future__ import annotations

from pathlib import Path

import scripts.run_project_control as control


def test_project_environment_closure_builds_only_required_profiles(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    work = tmp_path / "work"
    project.mkdir()
    work.mkdir()
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        control,
        "resolve_project_environment_profiles",
        lambda root: calls.append(("resolve", Path(root))) or ("minecraft",),
    )

    def fake_build(**kwargs):
        calls.append(("build", kwargs))
        return {"schema": "test", "images": {"minecraft": {}}}

    monkeypatch.setattr(control, "build_environment_images", fake_build)
    monkeypatch.setenv("PYTHON_RUNTIME_IMAGE", "mirror/python:3.12")
    monkeypatch.setenv(
        "PYTHON_RUNTIME_CANONICAL_IMAGE",
        "python:3.12-slim-bookworm",
    )

    receipt = control.ensure_project_environment_closure(
        project,
        work_root=work,
    )

    assert receipt == {"schema": "test", "images": {"minecraft": {}}}
    assert calls[0] == ("resolve", project.resolve())
    name, kwargs = calls[1]
    assert name == "build"
    assert kwargs["profiles"] == ("minecraft",)
    assert kwargs["work_root"] == work.resolve()
    assert kwargs["output"] == work.resolve() / "environment-image-build.json"
    assert kwargs["python_runtime_image"] == "mirror/python:3.12"
    assert (
        kwargs["python_runtime_canonical_image"]
        == "python:3.12-slim-bookworm"
    )
    assert kwargs["profile_build_input_overrides"] == {}


def test_project_environment_closure_skips_builder_without_profiles(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    work = tmp_path / "work"
    project.mkdir()
    work.mkdir()
    monkeypatch.setattr(
        control,
        "resolve_project_environment_profiles",
        lambda root: (),
    )

    def fail_build(**kwargs):
        raise AssertionError("builder must not run without required profiles")

    monkeypatch.setattr(control, "build_environment_images", fail_build)
    assert (
        control.ensure_project_environment_closure(project, work_root=work)
        is None
    )


def test_project_control_closes_environment_before_research_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    work = tmp_path / "work"
    project.mkdir()
    work.mkdir()
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        control,
        "ensure_project_environment_closure",
        lambda project_root, *, work_root: calls.append(
            ("closure", (Path(project_root), Path(work_root)))
        ),
    )
    monkeypatch.setattr(
        control,
        "research_main",
        lambda argv: calls.append(("research", tuple(argv))) or 17,
    )

    result = control.main(
        [
            "--project-root",
            str(project),
            "--work-root",
            str(work),
            "--",
            "run",
            "--project",
            str(project),
        ]
    )

    assert result == 17
    assert calls == [
        ("closure", (project, work)),
        ("research", ("run", "--project", str(project))),
    ]


def test_deploy_project_run_uses_one_control_environment_closure() -> None:
    deploy = (
        Path(__file__).resolve().parents[1] / "deploy" / "noetrium"
    ).read_text(encoding="utf-8")

    assert "materialize_project_environment_profiles" not in deploy
    assert "environment-profiles.txt" not in deploy
    assert "NOETRIUM_SKIP_ENVIRONMENT_BUILD" not in deploy
    assert '"$ROOT/scripts/run_project_control.py"' in deploy

    run_branch = deploy.split('  run)\n', 1)[1].split('\n  plan)', 1)[0]
    project_branch = run_branch.split(
        'if run_has_project_selector "$@"; then',
        1,
    )[1].split("else", 1)[0]
    assert 'project_control run "$@"' in project_branch
    assert "environment_bootstrap build" not in project_branch
