from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from noetrium_platform.capabilities.environment.api import (
    EnvironmentBranchStatePort,
    EnvironmentSession,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


@dataclass(frozen=True, slots=True)
class EnvironmentForkReceipt:
    """Proof that one portable scientific branch state materialized a child session."""

    parent_session_id: str
    child_session_id: str
    branch_id: str
    source_cut_id: str
    task_id: str
    state_schema_id: str
    source_state_digest: str
    restored_state_digest: str
    branch_state_digest: str

    def __post_init__(self) -> None:
        for name, value in (
            ("parent_session_id", self.parent_session_id),
            ("child_session_id", self.child_session_id),
            ("branch_id", self.branch_id),
            ("source_cut_id", self.source_cut_id),
            ("task_id", self.task_id),
            ("state_schema_id", self.state_schema_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"environment fork {name} is required")
        if self.parent_session_id == self.child_session_id:
            raise ValueError("environment fork child session must be distinct from parent")
        for name, value in (
            ("source_state_digest", self.source_state_digest),
            ("restored_state_digest", self.restored_state_digest),
            ("branch_state_digest", self.branch_state_digest),
        ):
            if (
                type(value) is not str
                or value != value.lower()
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise ValueError(f"environment fork {name} must be canonical sha256")
        if self.source_state_digest != self.restored_state_digest:
            raise ValueError("environment fork child scientific state does not match parent")


EnvironmentSessionOpener = Callable[[str], EnvironmentSession]


def fork_environment_session(
    parent: EnvironmentSession,
    *,
    parent_session_id: str,
    child_session_id: str,
    branch_id: str,
    source_cut_id: str,
    context: ExecutionContext,
    open_child: EnvironmentSessionOpener,
) -> tuple[EnvironmentSession, EnvironmentForkReceipt]:
    """Materialize one child from provider-owned portable branch state.

    Recovery checkpointing is intentionally not accepted here. A branchable
    provider must implement EnvironmentBranchStatePort, whose state is portable
    across sessions for the same environment implementation, task and generation.
    After restore, the child recaptures its scientific state and the state digest
    must match the parent before the fork is considered valid.
    """

    if not isinstance(parent, EnvironmentSession):
        raise TypeError("environment fork requires EnvironmentSession parent")
    if not isinstance(parent, EnvironmentBranchStatePort):
        raise TypeError("environment fork parent requires EnvironmentBranchStatePort")
    if not isinstance(context, ExecutionContext):
        raise TypeError("environment fork requires ExecutionContext")
    if context.task_id is None or not context.task_id.strip():
        raise ValueError("environment fork requires task-bound ExecutionContext")
    if not callable(open_child):
        raise TypeError("environment fork requires a child-session opener")
    for name, value in (
        ("parent_session_id", parent_session_id),
        ("child_session_id", child_session_id),
        ("branch_id", branch_id),
        ("source_cut_id", source_cut_id),
    ):
        if type(value) is not str or not value.strip():
            raise ValueError(f"environment fork {name} is required")
    if parent_session_id == child_session_id:
        raise ValueError("environment fork child session must be distinct from parent")

    state = parent.capture_branch_state(context)
    if state.source_session_id != parent_session_id:
        raise ValueError("environment fork parent session identity drift")
    if state.task_id != context.task_id:
        raise ValueError("environment fork parent task identity drift")

    child = open_child(child_session_id)
    if not isinstance(child, EnvironmentSession):
        raise TypeError("environment child opener must return EnvironmentSession")
    if child is parent:
        raise ValueError("environment fork opener returned the parent session")
    if not isinstance(child, EnvironmentBranchStatePort):
        child.close()
        raise TypeError("environment fork child requires EnvironmentBranchStatePort")

    try:
        child.restore_branch_state(state, context)
        restored = child.capture_branch_state(context)
        if restored.source_session_id != child_session_id:
            raise ValueError("environment fork child session identity drift")
        if restored.environment != state.environment:
            raise ValueError("environment fork child implementation identity drift")
        if restored.task_id != state.task_id or restored.generation != state.generation:
            raise ValueError("environment fork child task/generation identity drift")
        if restored.state_schema_id != state.state_schema_id:
            raise ValueError("environment fork child branch-state schema drift")
        if restored.state_digest != state.state_digest:
            raise ValueError("environment fork child scientific state digest mismatch")
    except BaseException:
        child.close()
        raise

    return child, EnvironmentForkReceipt(
        parent_session_id=parent_session_id,
        child_session_id=child_session_id,
        branch_id=branch_id,
        source_cut_id=source_cut_id,
        task_id=state.task_id,
        state_schema_id=state.state_schema_id,
        source_state_digest=state.state_digest,
        restored_state_digest=restored.state_digest,
        branch_state_digest=state.digest,
    )


__all__ = ["EnvironmentForkReceipt", "EnvironmentSessionOpener", "fork_environment_session"]
