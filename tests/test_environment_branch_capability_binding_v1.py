from __future__ import annotations

from hashlib import sha256

from noetrium_platform.capabilities.environment.api import (
    ActionResult,
    EnvironmentBranchState,
    EnvironmentIdentity,
    Observation,
)
from noetrium_platform.capabilities.environment.composition import (
    EnvironmentBranchCapabilityBinding,
    environment_branch_action_spec,
    environment_fork_action_payload,
    environment_replay_action_payload,
)
from noetrium_platform.capabilities.participant.capability.api import CapabilityRequest
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


_ENVIRONMENT = EnvironmentIdentity(
    "branch-test",
    "1",
    "1",
    "1",
    "a" * 64,
)


class _BranchSession:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.state = "initial"
        self.generation = "generation:1"
        self.actions: list[str] = []
        self.closed = False

    def observe(self, context):
        return Observation(
            f"obs:{self.session_id}:{len(self.actions)}",
            self.generation,
            {"text": self.state},
        )

    def act(self, request):
        action = request.payload["text"]
        self.actions.append(action)
        self.state = f"{self.state}|{action}"
        return ActionResult(
            request.action_id,
            True,
            Observation(
                f"obs:{self.session_id}:{len(self.actions)}",
                self.generation,
                {
                    "text": self.state,
                    "reward": 1.0 if action == "finish" else 0.0,
                    "done": action == "finish",
                },
            ),
            None,
            {},
        )

    def reconcile(self, effect, context):
        raise AssertionError("branch test does not reconcile effects")

    def capture_branch_state(self, context):
        payload = self.state.encode("utf-8")
        return EnvironmentBranchState.capture(
            environment=_ENVIRONMENT,
            source_session_id=self.session_id,
            task_id=context.task_id,
            generation=self.generation,
            state_schema_id="branch-test.state.v1",
            state_digest=sha256(payload).hexdigest(),
            opaque_payload=payload,
        )

    def restore_branch_state(self, state, context):
        state.verify_for(
            environment=_ENVIRONMENT,
            task_id=context.task_id,
            generation=self.generation,
        )
        self.state = state.opaque_payload.decode("utf-8")

    def close(self):
        self.closed = True


def test_environment_branch_capability_proves_exact_fork_and_caches_retry() -> None:
    root = _BranchSession("root-session")
    opened: list[_BranchSession] = []

    def open_child(session_id: str):
        child = _BranchSession(session_id)
        opened.append(child)
        return child

    binding = EnvironmentBranchCapabilityBinding(
        root,
        root_session_id="root-session",
        root_branch_id="root",
        open_child=open_child,
    )
    context = ExecutionContext("run", "trace", "span", task_id="task:1")
    request = CapabilityRequest(
        "environment.branch-state",
        environment_fork_action_payload(
            parent_branch_id="root",
            child_branch_id="child:1",
            source_cut_id="initial-cut",
            action_type="command",
            action_payload={"text": "finish"},
        ),
        context,
        "fork:child:1",
    )

    result = binding.invoke(request)
    assert result.payload["proof"] == "portable_branch_state_digest_equality"
    assert result.payload["source_state_digest"] == result.payload["restored_state_digest"]
    assert result.payload["branch_id"] == "child:1"
    assert result.payload["observation"]["payload"]["reward"] == 1.0
    assert len(opened) == 1
    assert opened[0].actions == ["finish"]

    replayed = binding.invoke(request)
    assert replayed.digest() == result.digest()
    assert len(opened) == 1
    assert opened[0].actions == ["finish"]

    binding.close()
    assert opened[0].closed is True
    assert root.closed is False


def test_environment_branch_capability_keeps_replay_proof_weaker_than_exact_fork() -> None:
    root = _BranchSession("root-session")
    opened: list[_BranchSession] = []

    def open_child(session_id: str):
        child = _BranchSession(session_id)
        opened.append(child)
        return child

    binding = EnvironmentBranchCapabilityBinding(
        root,
        root_session_id="root-session",
        root_branch_id="root",
        open_child=open_child,
    )
    context = ExecutionContext("run", "trace", "span", task_id="task:1")
    request = CapabilityRequest(
        "environment.branch-state",
        environment_replay_action_payload(
            branch_id="candidate:1",
            source_cut_id="task:1:initial",
            committed_actions=(
                environment_branch_action_spec("command", {"text": "look"}),
            ),
            action_type="command",
            action_payload={"text": "finish"},
        ),
        context,
        "replay:candidate:1",
    )

    result = binding.invoke(request)
    assert result.payload["proof"] == "fresh_open_plus_ordered_prefix_replay"
    assert result.payload["accepted_prefix_action_ids"]
    assert "source_state_digest" not in result.payload
    assert result.payload["observation"]["payload"]["reward"] == 1.0
    assert opened[0].actions == ["look", "finish"]
    assert opened[0].closed is True
