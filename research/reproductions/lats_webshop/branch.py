from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from noetrium_platform.capabilities.environment.api import EnvironmentSession
from noetrium_platform.composition.environment_fork import (
    EnvironmentForkReceipt,
    EnvironmentSessionOpener,
    fork_environment_session,
)


_ResultT = TypeVar("_ResultT")


@dataclass(frozen=True, slots=True)
class LATSBranchExecution(Generic[_ResultT]):
    child: EnvironmentSession
    fork_receipt: EnvironmentForkReceipt
    result: _ResultT


def execute_candidate_from_parent(
    parent: EnvironmentSession,
    *,
    parent_session_id: str,
    child_session_id: str,
    branch_id: str,
    source_cut_id: str,
    open_child: EnvironmentSessionOpener,
    execute: Callable[[EnvironmentSession], _ResultT],
) -> LATSBranchExecution[_ResultT]:
    """Restore a child from the exact parent cut before executing a candidate.

    This is the LATS-specific composition seam. Branch state itself remains
    entirely owned by the generic environment authority; the reproduction only
    specifies when a child branch must be materialized relative to candidate
    action execution.
    """

    if not callable(execute):
        raise TypeError("LATS branch execution callback must be callable")
    child, receipt = fork_environment_session(
        parent,
        parent_session_id=parent_session_id,
        child_session_id=child_session_id,
        branch_id=branch_id,
        source_cut_id=source_cut_id,
        open_child=open_child,
    )
    try:
        result = execute(child)
    except BaseException:
        child.close()
        raise
    return LATSBranchExecution(child=child, fork_receipt=receipt, result=result)


__all__ = ["LATSBranchExecution", "execute_candidate_from_parent"]
