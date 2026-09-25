from __future__ import annotations

from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodProgramIdentity
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.platform import run_method_program
from noetrium_platform.research.execution.workflow.api import (
    MethodNodeKind,
    MethodNodeResult,
    MethodNodeSpec,
    MethodProgramBuilder,
    MethodRuntimeContext,
    MethodRunStatus,
)


def _program():
    identity = MethodProgramIdentity(MethodIdentity("test.public-machine-binding", "1", "1", "1"))
    def finish(request):
        return MethodNodeResult(value={"resumed": request.previous_value is None})
    return (
        MethodProgramBuilder(identity, entrypoint="pause")
        .add(MethodNodeSpec("pause", "test.pause", ("finish",), kind=MethodNodeKind.INTERRUPT))
        .add(MethodNodeSpec("finish", "test.finish", (), finish, kind=MethodNodeKind.RETURN))
        .build()
    )


def _runtime():
    return MethodRuntimeContext(ExecutionContext("public-run", "trace", "span"))


def test_public_binding_resumes_from_machine_journal_not_method_checkpoint_state(tmp_path) -> None:
    program = _program()
    state_root = tmp_path / "method-state"

    first = run_method_program(program, runtime=_runtime(), state_root=state_root)
    assert first.status is MethodRunStatus.INTERRUPTED
    assert first.checkpoint is not None
    assert first.checkpoint.machine_revision >= 1
    assert first.checkpoint.machine_commit_id is not None

    resumed = run_method_program(
        program,
        runtime=_runtime(),
        state_root=state_root,
        resume=True,
    )
    assert resumed.status is MethodRunStatus.SUCCEEDED
    assert resumed.step_count == 2
