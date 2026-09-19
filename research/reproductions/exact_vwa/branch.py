from __future__ import annotations

from noetrium_platform.capabilities.environment.api import ActionRequest, EnvironmentSession
from noetrium_platform.composition.environment_fork import EnvironmentSessionOpener
from noetrium_platform.composition.environment_replay import (
    EnvironmentReplayReceipt,
    replay_environment_prefix,
)

from .fidelity import EXACT_VWA_FIDELITY


def materialize_exact_candidate_parent(
    *,
    session_id: str,
    branch_id: str,
    source_cut_id: str,
    task_id: str,
    committed_actions: tuple[ActionRequest, ...],
    open_fresh: EnvironmentSessionOpener,
) -> tuple[EnvironmentSession, EnvironmentReplayReceipt]:
    """Reconstruct the released ExACT search parent by reset plus action replay.

    The released VWA search implementation resets the browser task and replays
    the committed action history before evaluating another candidate. It does
    not require or claim portable hidden-state snapshot equivalence.
    """

    if EXACT_VWA_FIDELITY.environment_branch_strategy != "reset_and_replay_action_history":
        raise ValueError("ExACT environment reconstruction strategy drifted")
    return replay_environment_prefix(
        session_id=session_id,
        branch_id=branch_id,
        source_cut_id=source_cut_id,
        task_id=task_id,
        requests=committed_actions,
        open_fresh=open_fresh,
    )


__all__ = ["materialize_exact_candidate_parent"]
