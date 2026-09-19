from __future__ import annotations

from noetrium_platform.capabilities.environment.api import ActionRequest, EnvironmentSession
from noetrium_platform.composition.environment_fork import EnvironmentSessionOpener
from noetrium_platform.composition.environment_replay import (
    EnvironmentReplayReceipt,
    replay_environment_prefix,
)

from .fidelity import QLASS_ALFWORLD_RELEASED_FIDELITY


def materialize_qlass_candidate_parent(
    *,
    session_id: str,
    branch_id: str,
    source_cut_id: str,
    task_id: str,
    committed_actions: tuple[ActionRequest, ...],
    open_fresh: EnvironmentSessionOpener,
) -> tuple[EnvironmentSession, EnvironmentReplayReceipt]:
    """Rebuild the committed QLASS trajectory prefix before one candidate action."""

    if (
        QLASS_ALFWORLD_RELEASED_FIDELITY.branch_strategy
        != "reset_and_replay_committed_action_history"
    ):
        raise ValueError("QLASS environment branch strategy drifted")
    return replay_environment_prefix(
        session_id=session_id,
        branch_id=branch_id,
        source_cut_id=source_cut_id,
        task_id=task_id,
        requests=committed_actions,
        open_fresh=open_fresh,
    )


__all__ = ["materialize_qlass_candidate_parent"]
