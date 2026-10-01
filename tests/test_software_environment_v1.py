from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.capabilities.environment.api import (
    ActionIdentityViolation,
    ActionRequest,
)
from noetrium_platform.capabilities.environment.category.api import (
    EnvironmentCategoryStatus,
)
from noetrium_platform.capabilities.environment.category.runtime.catalog import (
    canonical_environment_implementations,
)
from noetrium_platform.capabilities.environment.software.api import (
    SoftwareActionKind,
    SoftwareActionTimeoutError,
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
    LocalCommandTimeoutError,
)


class _Runner:
    def __init__(self) -> None:
        self.calls = []

    def run(
        self,
        argv,
        *,
        cwd=None,
        environment=None,
        timeout_seconds=None,
    ):
        self.calls.append((argv, cwd, environment, timeout_seconds))
        return LocalCommandResult(
            argv=tuple(argv),
            returncode=0,
            stdout="ok\n",
            stderr="",
        )


def _context() -> ExecutionContext:
    return ExecutionContext(
        "software-run",
        "trace",
        "span",
        task_id="workspace:test",
    )


def _provider(root: Path):
    (root / "main.py").write_text("print('v1')\n", encoding="utf-8")
    runner = _Runner()
    spec = SoftwareEnvironmentSpec(
        environment_id="software.repository.test",
        revision="1",
        workspace_root=str(root.resolve()),
        repository_digest=canonical_digest({"fixture": "software-workspace"}),
        supported_actions=(
            SoftwareActionKind.LIST,
            SoftwareActionKind.READ,
            SoftwareActionKind.EDIT,
            SoftwareActionKind.TEST,
            SoftwareActionKind.BUILD,
            SoftwareActionKind.EXECUTE,
        ),
    )
    provider = build_local_repository_software_provider(
        root=root,
        spec=spec,
        command_runner=runner,
        command_runner_identity_digest=canonical_digest({
            "runner": "test",
            "implementation_revision": 1,
        }),
    )
    return provider, runner


def test_repository_workspace_provider_is_catalogued_available() -> None:
    descriptor = next(
        item
        for item in canonical_environment_implementations()
        if item.implementation_id == "software.repository"
    )
    assert descriptor.status is EnvironmentCategoryStatus.AVAILABLE
    assert descriptor.capabilities == ("filesystem", "repository", "test_runner")


def test_repository_workspace_provider_records_read_edit_and_test_state(
    tmp_path: Path,
) -> None:
    provider, runner = _provider(tmp_path)
    session = provider.open_session(session_id="s1", services=object())
    initial = session.observe(_context())
    initial_digest = initial.generation

    listed = session.act(ActionRequest(
        "list-1",
        SoftwareActionKind.LIST.value,
        {"suffix": ".py"},
        _context(),
    ))
    assert listed.accepted is True
    assert listed.effect is None
    assert listed.observation.payload["files"] == ("main.py",)

    read = session.act(ActionRequest(
        "read-1",
        SoftwareActionKind.READ.value,
        {"path": "main.py"},
        _context(),
    ))
    assert read.accepted is True
    assert read.effect is None
    assert read.observation.payload["content"] == "print('v1')\n"

    edit_request = ActionRequest(
        "edit-1",
        SoftwareActionKind.EDIT.value,
        {"path": "main.py", "content": "print('v2')\n"},
        _context(),
    )
    edit = session.act(edit_request)
    assert edit.accepted is True
    assert edit.effect is not None
    assert edit.effect.before_artifact == initial_digest
    assert edit.effect.after_artifact != initial_digest
    edit_view = edit.observation.payload["decision_view"]
    assert edit_view == {
        "kind": "software_edit.v1",
        "path": "main.py",
        "size_bytes": len("print('v2')\n".encode("utf-8")),
        "line_count": 1,
        "workspace": {
            "file_count": 1,
            "total_bytes": len("print('v2')\n".encode("utf-8")),
        },
    }
    assert "files" not in edit_view
    assert session.reconcile(edit.effect, _context()) == edit.effect

    test = session.act(ActionRequest(
        "test-1",
        SoftwareActionKind.TEST.value,
        {"argv": ("python", "-m", "pytest", "-q"), "timeout_seconds": 12},
        _context(),
    ))
    assert test.accepted is True
    assert test.observation.payload["returncode"] == 0
    assert test.observation.payload["stdout"] == "ok\n"
    assert runner.calls[-1][0] == ("python", "-m", "pytest", "-q")
    assert runner.calls[-1][1] == tmp_path.resolve()
    assert runner.calls[-1][3] == 12.0

    diagnostics = session.diagnostics_snapshot()
    assert diagnostics.ready is True
    assert diagnostics.closed is False
    assert diagnostics.state_digest == test.observation.generation

    session.close()
    closed = session.diagnostics_snapshot()
    assert closed.ready is False
    assert closed.closed is True


def test_edit_reuses_post_edit_workspace_scan(tmp_path: Path) -> None:
    provider, _runner = _provider(tmp_path)
    session = provider.open_session(session_id="scan-count", services=object())
    calls = 0
    original = session._workspace_rows

    def counted():
        nonlocal calls
        calls += 1
        return original()

    session._workspace_rows = counted
    session.act(ActionRequest(
        "edit-scan",
        SoftwareActionKind.EDIT.value,
        {"path": "main.py", "content": "print('fast')\n"},
        _context(),
    ))
    assert calls == 2


def test_repository_workspace_provider_rejects_path_escape_and_action_drift(
    tmp_path: Path,
) -> None:
    provider, _ = _provider(tmp_path)
    session = provider.open_session(session_id="s1", services=object())

    with pytest.raises(ValueError, match="escapes workspace root"):
        session.act(ActionRequest(
            "escape",
            SoftwareActionKind.EDIT.value,
            {"path": "../outside.py", "content": "x"},
            _context(),
        ))

    request = ActionRequest(
        "same-id",
        SoftwareActionKind.READ.value,
        {"path": "main.py"},
        _context(),
    )
    first = session.act(request)
    assert session.act(request) == first

    with pytest.raises(ActionIdentityViolation, match="reused with drift"):
        session.act(ActionRequest(
            "same-id",
            SoftwareActionKind.READ.value,
            {"path": "other.py"},
            _context(),
        ))


def test_repository_workspace_translates_process_timeout(
    tmp_path: Path,
) -> None:
    class _TimeoutRunner:
        def run(
            self,
            argv,
            *,
            cwd=None,
            environment=None,
            timeout_seconds=None,
        ):
            del argv, cwd, environment, timeout_seconds
            raise LocalCommandTimeoutError(
                "software-test",
                "simulated timeout",
            )

    (tmp_path / "main.py").write_text("print('v1')\n", encoding="utf-8")
    spec = SoftwareEnvironmentSpec(
        environment_id="software.repository.timeout",
        revision="1",
        workspace_root=str(tmp_path.resolve()),
        repository_digest=canonical_digest({"fixture": "timeout"}),
        supported_actions=(SoftwareActionKind.TEST,),
    )
    provider = build_local_repository_software_provider(
        root=tmp_path,
        spec=spec,
        command_runner=_TimeoutRunner(),
        command_runner_identity_digest=canonical_digest({
            "runner": "timeout-test",
        }),
    )
    session = provider.open_session(session_id="timeout", services=object())

    with pytest.raises(
        SoftwareActionTimeoutError,
        match="software test action timed out",
    ):
        session.act(ActionRequest(
            "timeout-1",
            SoftwareActionKind.TEST.value,
            {"argv": ("python", "main.py"), "timeout_seconds": 0.01},
            _context(),
        ))


def test_software_decision_views_bound_large_model_context(tmp_path: Path) -> None:
    provider, runner = _provider(tmp_path)
    session = provider.open_session(session_id="context", services=object())

    large = "HEAD\n" + ("x" * 20_000) + "\nTAIL\n"
    (tmp_path / "large.txt").write_text(large, encoding="utf-8")
    read = session.act(ActionRequest(
        "read-large",
        SoftwareActionKind.READ.value,
        {"path": "large.txt"},
        _context(),
    ))
    payload = read.observation.payload
    assert payload["content"] == large
    view = payload["decision_view"]
    assert view["kind"] == "software_read.v1"
    assert view["truncated"] is True
    assert len(view["content"]) < len(large)
    assert "HEAD" in view["content"]
    assert "TAIL" in view["content"]

    ranged = session.act(ActionRequest(
        "read-range",
        SoftwareActionKind.READ.value,
        {"path": "large.txt", "start_line": 1, "end_line": 1},
        _context(),
    ))
    assert ranged.observation.payload["decision_view"]["content"] == "HEAD\n"

    runner.run = lambda *args, **kwargs: LocalCommandResult(
        argv=("tool",),
        returncode=1,
        stdout="begin\n" + ("o" * 20_000) + "\nend-out\n",
        stderr="err-begin\n" + ("e" * 20_000) + "\nerr-end\n",
    )
    executed = session.act(ActionRequest(
        "execute-large",
        SoftwareActionKind.EXECUTE.value,
        {"argv": ("tool",)},
        _context(),
    ))
    raw = executed.observation.payload
    assert len(raw["stdout"]) > 20_000
    command_view = raw["decision_view"]
    assert command_view["stdout"]["truncated"] is True
    assert command_view["stderr"]["truncated"] is True
    assert "begin" in command_view["stdout"]["text"]
    assert "end-out" in command_view["stdout"]["text"]
    assert "err-end" in command_view["stderr"]["text"]
