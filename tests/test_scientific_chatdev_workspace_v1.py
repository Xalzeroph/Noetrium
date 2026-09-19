from __future__ import annotations

from pathlib import Path

from noetrium_platform.capabilities.environment.software.api import (
    SoftwareActionKind,
    SoftwareEnvironmentSpec,
)
from noetrium_platform.capabilities.environment.software.composition import (
    build_local_repository_software_provider,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_digest,
)
from noetrium_platform.infrastructure.lifecycle.process.api import (
    LocalCommandResult,
)
from research.reproductions.chatdev_v1.environment import (
    ChatDevV1EnvironmentApplyRequest,
    ChatDevV1EnvironmentPrepareRequest,
    ChatDevV1PhaseDisposition,
)
from research.reproductions.chatdev_v1.workspace import (
    ChatDevV1RepositoryWorkspace,
    parse_chatdev_v1_codes,
    parse_chatdev_v1_requirements,
)


class _Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path | None]] = []

    def run(
        self,
        argv,
        *,
        cwd=None,
        environment=None,
        timeout_seconds=None,
    ):
        del environment, timeout_seconds
        argv = tuple(argv)
        self.calls.append((argv, cwd))
        return LocalCommandResult(argv, 0, "ok\n", "")


def _context() -> ExecutionContext:
    return ExecutionContext(
        "chatdev-workspace-run",
        "trace",
        "span",
        task_id="chatdev:workspace:1",
    )


def _workspace(tmp_path: Path):
    runner = _Runner()
    spec = SoftwareEnvironmentSpec(
        environment_id="software.repository.chatdev-test",
        revision="1",
        workspace_root=str(tmp_path.resolve()),
        repository_digest=canonical_digest({"fixture": "chatdev-workspace"}),
        supported_actions=(
            SoftwareActionKind.LIST,
            SoftwareActionKind.READ,
            SoftwareActionKind.EDIT,
            SoftwareActionKind.EXECUTE,
            SoftwareActionKind.TEST,
        ),
    )
    provider = build_local_repository_software_provider(
        root=tmp_path,
        spec=spec,
        command_runner=runner,
        command_runner_identity_digest=canonical_digest({
            "runner": "chatdev-test",
            "revision": 1,
        }),
    )
    session = provider.open_session(
        session_id="chatdev-session",
        services=object(),
    )
    adapter = ChatDevV1RepositoryWorkspace(
        workspace=session,
        workspace_identity_digest=session.identity_digest,
        context=_context(),
    )
    return adapter, session, runner


def _row(
    phase_name: str,
    conclusion: str,
    projection,
    *,
    cycle_index: int = 0,
):
    return {
        "phase_name": phase_name,
        "cycle_index": cycle_index,
        "phase_result": {"conclusion": conclusion},
        "environment_state_projection": projection,
    }


def test_chatdev_v1_code_and_requirement_parsers_preserve_source_rules() -> None:
    generated = (
        "main.py\n```python\n\n"
        "def main():\n    pass\n\n"
        "if __name__ == '__main__':\n    main()\n"
        "```\n"
    )
    assert parse_chatdev_v1_codes(generated) == {
        "main.py": (
            "def main():\n"
            "    pass\n"
            "if __name__ == '__main__':\n"
            "    main()"
        )
    }
    assert (
        parse_chatdev_v1_requirements("```\nrequests==2.32.0\n```")
        == "requests==2.32.0\n"
    )


def test_chatdev_v1_workspace_rebuilds_phase_state_from_history(
    tmp_path: Path,
) -> None:
    adapter, session, runner = _workspace(tmp_path)

    demand_prepare = adapter.prepare(
        ChatDevV1EnvironmentPrepareRequest(
            "DemandAnalysis",
            0,
            "build a demo",
            (),
        )
    )
    demand_apply = adapter.apply(
        ChatDevV1EnvironmentApplyRequest(
            "DemandAnalysis",
            0,
            "Application.",
            {"conclusion": "Application."},
            {
                "placeholders": demand_prepare.placeholders,
                "disposition": demand_prepare.disposition.value,
            },
        )
    )
    assert demand_apply.state_projection["modality"] == "application"
    rows = (
        _row(
            "DemandAnalysis",
            "Application.",
            demand_apply.state_projection,
        ),
    )

    language_prepare = adapter.prepare(
        ChatDevV1EnvironmentPrepareRequest(
            "LanguageChoose",
            0,
            "build a demo",
            rows,
        )
    )
    assert language_prepare.placeholders["modality"] == "application"
    language_apply = adapter.apply(
        ChatDevV1EnvironmentApplyRequest(
            "LanguageChoose",
            0,
            "Python",
            {"conclusion": "Python"},
            {
                "placeholders": language_prepare.placeholders,
                "disposition": language_prepare.disposition.value,
            },
        )
    )
    rows += (
        _row(
            "LanguageChoose",
            "Python",
            language_apply.state_projection,
        ),
    )

    coding_prepare = adapter.prepare(
        ChatDevV1EnvironmentPrepareRequest(
            "Coding",
            0,
            "build a demo",
            rows,
        )
    )
    assert coding_prepare.placeholders["language"] == "Python"
    coding_conclusion = (
        "main.py\n```python\n"
        "def main():\n"
        "    pass\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
        "```"
    )
    coding_apply = adapter.apply(
        ChatDevV1EnvironmentApplyRequest(
            "Coding",
            0,
            coding_conclusion,
            {"conclusion": coding_conclusion},
            {
                "placeholders": coding_prepare.placeholders,
                "disposition": coding_prepare.disposition.value,
            },
        )
    )
    assert (tmp_path / "main.py").is_file()
    rows += (
        _row("Coding", coding_conclusion, coding_apply.state_projection),
    )

    complete_prepare = adapter.prepare(
        ChatDevV1EnvironmentPrepareRequest(
            "CodeComplete",
            0,
            "build a demo",
            rows,
        )
    )
    assert complete_prepare.disposition is ChatDevV1PhaseDisposition.EXECUTE
    assert complete_prepare.placeholders["unimplemented_file"] == "main.py"

    complete_conclusion = (
        "main.py\n```python\n"
        "def main():\n"
        "    print('done')\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
        "```"
    )
    complete_apply = adapter.apply(
        ChatDevV1EnvironmentApplyRequest(
            "CodeComplete",
            0,
            complete_conclusion,
            {"conclusion": complete_conclusion},
            {
                "placeholders": complete_prepare.placeholders,
                "disposition": complete_prepare.disposition.value,
            },
        )
    )
    assert complete_apply.state_projection["unimplemented_file"] == "main.py"
    rows += (
        _row(
            "CodeComplete",
            complete_conclusion,
            complete_apply.state_projection,
        ),
    )

    next_complete = adapter.prepare(
        ChatDevV1EnvironmentPrepareRequest(
            "CodeComplete",
            1,
            "build a demo",
            rows,
        )
    )
    assert next_complete.disposition is ChatDevV1PhaseDisposition.SKIP
    assert next_complete.reason_code == "unimplemented_file_is_empty"

    test_prepare = adapter.prepare(
        ChatDevV1EnvironmentPrepareRequest(
            "TestErrorSummary",
            0,
            "build a demo",
            rows,
        )
    )
    assert test_prepare.disposition is ChatDevV1PhaseDisposition.SKIP
    assert test_prepare.placeholders["exist_bugs_flag"] is False
    assert test_prepare.placeholders["test_reports"].startswith(
        "The software run successfully"
    )
    assert runner.calls[-1][0] == ("python3", "main.py")

    session.close()


def test_chatdev_v1_workspace_writes_requirements_and_manual(
    tmp_path: Path,
) -> None:
    adapter, session, _ = _workspace(tmp_path)

    env_prepare = adapter.prepare(
        ChatDevV1EnvironmentPrepareRequest(
            "EnvironmentDoc",
            0,
            "build a demo",
            (),
        )
    )
    env_apply = adapter.apply(
        ChatDevV1EnvironmentApplyRequest(
            "EnvironmentDoc",
            0,
            "```\nrequests==2.32.0\n```",
            {"conclusion": "requirements"},
            {
                "placeholders": env_prepare.placeholders,
                "disposition": env_prepare.disposition.value,
            },
        )
    )
    assert (tmp_path / "requirements.txt").read_text(
        encoding="utf-8"
    ) == "requests==2.32.0\n"

    rows = (
        _row(
            "EnvironmentDoc",
            "requirements",
            env_apply.state_projection,
        ),
    )
    manual_prepare = adapter.prepare(
        ChatDevV1EnvironmentPrepareRequest(
            "Manual",
            0,
            "build a demo",
            rows,
        )
    )
    assert "requests==2.32.0" in manual_prepare.placeholders["requirements"]

    manual_apply = adapter.apply(
        ChatDevV1EnvironmentApplyRequest(
            "Manual",
            0,
            "# Manual\nRun the app.",
            {"conclusion": "# Manual\nRun the app."},
            {
                "placeholders": manual_prepare.placeholders,
                "disposition": manual_prepare.disposition.value,
            },
        )
    )
    assert (tmp_path / "manual.md").read_text(
        encoding="utf-8"
    ) == "# Manual\nRun the app."
    assert len(manual_apply.environment_digest) == 64

    session.close()
