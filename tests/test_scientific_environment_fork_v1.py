from __future__ import annotations

from hashlib import sha256

import pytest

from noetrium_platform.capabilities.environment.api import (
    EnvironmentBranchState,
    EnvironmentIdentity,
)
from noetrium_platform.composition.environment_fork import fork_environment_session
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


_IDENTITY = EnvironmentIdentity(
    "test-environment",
    "1",
    "1",
    "1",
    "a" * 64,
)


def _context() -> ExecutionContext:
    return ExecutionContext("run", "trace", "span", task_id="task:1")


class _Session:
    def __init__(self, session_id: str, payload: bytes) -> None:
        self.session_id = session_id
        self.payload = payload
        self.closed = False

    def observe(self, context):
        raise AssertionError("fork composition must not observe")

    def act(self, request):
        raise AssertionError("fork composition must not act")

    def reconcile(self, effect, context):
        raise AssertionError("fork composition must not reconcile")

    def capture_branch_state(self, context: ExecutionContext) -> EnvironmentBranchState:
        assert context.task_id is not None
        return EnvironmentBranchState.capture(
            environment=_IDENTITY,
            source_session_id=self.session_id,
            task_id=context.task_id,
            generation="generation:1",
            state_schema_id="test.branch-state.v1",
            state_digest=sha256(self.payload).hexdigest(),
            opaque_payload=self.payload,
        )

    def restore_branch_state(
        self,
        state: EnvironmentBranchState,
        context: ExecutionContext,
    ) -> None:
        assert context.task_id is not None
        state.verify_for(
            environment=_IDENTITY,
            task_id=context.task_id,
            generation="generation:1",
        )
        self.payload = state.opaque_payload

    def close(self) -> None:
        self.closed = True


def test_environment_fork_materializes_portable_parent_state_into_distinct_child() -> None:
    parent = _Session("session:parent", b"provider-owned-state")
    children: list[_Session] = []

    def open_child(session_id: str):
        assert session_id == "session:child"
        child = _Session(session_id, b"empty")
        children.append(child)
        return child

    child, receipt = fork_environment_session(
        parent,
        parent_session_id="session:parent",
        child_session_id="session:child",
        branch_id="branch:7",
        source_cut_id="cut:parent:42",
        context=_context(),
        open_child=open_child,
    )

    assert child is children[0]
    assert child.payload == b"provider-owned-state"
    assert parent.payload == b"provider-owned-state"
    assert receipt.branch_id == "branch:7"
    assert receipt.source_cut_id == "cut:parent:42"
    assert receipt.task_id == "task:1"
    assert receipt.source_state_digest == sha256(b"provider-owned-state").hexdigest()
    assert receipt.restored_state_digest == receipt.source_state_digest
    assert len(receipt.branch_state_digest) == 64


def test_environment_fork_fails_closed_and_closes_partial_child_on_restore_error() -> None:
    parent = _Session("session:parent", b"provider-owned-state")

    class Broken(_Session):
        def restore_branch_state(self, state, context) -> None:
            raise RuntimeError("restore rejected")

    child = Broken("session:child", b"empty")
    with pytest.raises(RuntimeError, match="restore rejected"):
        fork_environment_session(
            parent,
            parent_session_id="session:parent",
            child_session_id="session:child",
            branch_id="branch:7",
            source_cut_id="cut:parent:42",
            context=_context(),
            open_child=lambda _session_id: child,
        )
    assert child.closed


def test_environment_fork_rejects_aliasing_parent_as_child() -> None:
    parent = _Session("session:parent", b"provider-owned-state")
    with pytest.raises(ValueError, match="returned the parent"):
        fork_environment_session(
            parent,
            parent_session_id="session:parent",
            child_session_id="session:child",
            branch_id="branch:7",
            source_cut_id="cut:parent:42",
            context=_context(),
            open_child=lambda _session_id: parent,
        )
