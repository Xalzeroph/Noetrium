from __future__ import annotations

import pytest

from noetrium_platform.capabilities.environment.api import (
    ActionRequest,
    ActionResult,
    ExecutionContext,
    Observation,
)
from noetrium_platform.composition.environment_replay import (
    EnvironmentReplayError,
    replay_environment_prefix,
)


class _ReplaySession:
    def __init__(self, *, reject_action_id: str | None = None, fail_action_id: str | None = None) -> None:
        self.actions: list[str] = []
        self.closed = False
        self.reject_action_id = reject_action_id
        self.fail_action_id = fail_action_id

    def observe(self, context):
        raise AssertionError("replay composition must not introduce extra observations")

    def act(self, request: ActionRequest) -> ActionResult:
        if request.action_id == self.fail_action_id:
            raise RuntimeError("provider act failed")
        self.actions.append(request.action_id)
        return ActionResult(
            action_id=request.action_id,
            accepted=request.action_id != self.reject_action_id,
            observation=Observation(
                f"obs:{request.action_id}",
                "generation:replay",
                {"action_id": request.action_id},
            ),
            effect=None,
            diagnostics={},
        )

    def reconcile(self, effect, context):
        raise AssertionError("replay composition must not reconcile")

    def checkpoint(self) -> bytes:
        raise AssertionError("reset+replay must not pretend to use provider checkpoints")

    def restore(self, payload: bytes) -> None:
        raise AssertionError("reset+replay must not pretend to restore checkpoints")

    def close(self) -> None:
        self.closed = True


def _requests() -> tuple[ActionRequest, ...]:
    return tuple(
        ActionRequest(
            f"replay-{index}",
            "browser-action",
            {"index": index},
            ExecutionContext(
                "run",
                "trace",
                f"span-{index}",
                study_id="study",
                task_id="task:7",
                decision_cycle_id=f"dc:{index}",
            ),
        )
        for index in range(3)
    )


def test_environment_replay_materializes_fresh_prefix_without_checkpoint_claim() -> None:
    child = _ReplaySession()
    opened: list[str] = []

    session, receipt = replay_environment_prefix(
        session_id="session:branch:3",
        branch_id="branch:3",
        source_cut_id="benchmark-cut:vwa:shopping:7",
        task_id="task:7",
        requests=_requests(),
        open_fresh=lambda session_id: (opened.append(session_id), child)[1],
    )

    assert session is child
    assert opened == ["session:branch:3"]
    assert child.actions == ["replay-0", "replay-1", "replay-2"]
    assert receipt.accepted_action_ids == tuple(child.actions)
    assert receipt.observation_ids == (
        "obs:replay-0",
        "obs:replay-1",
        "obs:replay-2",
    )
    assert len(receipt.action_request_digests) == 3
    assert len(receipt.prefix_digest) == 64
    assert not child.closed


def test_environment_replay_closes_partial_session_when_prefix_is_rejected() -> None:
    child = _ReplaySession(reject_action_id="replay-1")
    with pytest.raises(EnvironmentReplayError, match="was rejected"):
        replay_environment_prefix(
            session_id="session:branch:bad",
            branch_id="branch:bad",
            source_cut_id="cut:task",
            task_id="task:7",
            requests=_requests(),
            open_fresh=lambda _session_id: child,
        )
    assert child.actions == ["replay-0", "replay-1"]
    assert child.closed


def test_environment_replay_closes_partial_session_on_provider_failure() -> None:
    child = _ReplaySession(fail_action_id="replay-1")
    with pytest.raises(RuntimeError, match="provider act failed"):
        replay_environment_prefix(
            session_id="session:branch:error",
            branch_id="branch:error",
            source_cut_id="cut:task",
            task_id="task:7",
            requests=_requests(),
            open_fresh=lambda _session_id: child,
        )
    assert child.actions == ["replay-0"]
    assert child.closed


def test_environment_replay_rejects_cross_task_prefix_before_provider_action() -> None:
    child = _ReplaySession()
    wrong = (
        ActionRequest(
            "wrong-task-action",
            "browser-action",
            {},
            ExecutionContext("run", "trace", "span", task_id="task:other"),
        ),
    )
    with pytest.raises(EnvironmentReplayError, match="task identity mismatch"):
        replay_environment_prefix(
            session_id="session:branch:cross-task",
            branch_id="branch:cross-task",
            source_cut_id="cut:task",
            task_id="task:7",
            requests=wrong,
            open_fresh=lambda _session_id: child,
        )
    assert child.actions == []
    assert child.closed
