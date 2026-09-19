from __future__ import annotations

from noetrium_platform.capabilities.environment.api import ActionRequest, EnvironmentSession
from noetrium_platform.composition.environment_fork import EnvironmentSessionOpener
from noetrium_platform.composition.environment_replay import (
    EnvironmentReplayReceipt,
    replay_environment_prefix,
)

from .fidelity import TREE_SEARCH_VWA_FIDELITY


def materialize_tree_search_branch_prefix(
    *,
    session_id: str,
    branch_id: str,
    source_cut_id: str,
    task_id: str,
    committed_actions: tuple[ActionRequest, ...],
    open_fresh: EnvironmentSessionOpener,
) -> tuple[EnvironmentSession, EnvironmentReplayReceipt]:
    """Reconstruct one VWA search parent exactly as the released method does.

    Tree Search for Language Model Agents does not require a provider snapshot for
    this lane. It opens a fresh task session and replays the committed action
    history before evaluating a new branch candidate.
    """

    if TREE_SEARCH_VWA_FIDELITY.environment_branch_strategy != "reset_and_replay_action_history":
        raise ValueError("Tree Search environment branch strategy drifted")
    return replay_environment_prefix(
        session_id=session_id,
        branch_id=branch_id,
        source_cut_id=source_cut_id,
        task_id=task_id,
        requests=committed_actions,
        open_fresh=open_fresh,
    )


__all__ = ["materialize_tree_search_branch_prefix"]
