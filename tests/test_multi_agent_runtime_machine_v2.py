from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from noetrium_platform.foundation.kernel.kernel import DirectoryMachineJournal
from orchestration.multi_agent import (
    CommunicationEdge,
    CommunicationTopology,
    MultiAgentMessage,
    MultiAgentRunStatus,
    MultiAgentRuntime,
)


class _EchoNode:
    def __init__(self, name: str) -> None:
        self.name = name

    def handle(self, message: MultiAgentMessage) -> tuple[MultiAgentMessage, ...]:
        if message.turn >= 1:
            return ()
        recipient = "manager" if self.name == "worker" else "worker"
        return (
            MultiAgentMessage(
                self.name,
                recipient,
                "reply",
                message.turn + 1,
                conversation_id=message.conversation_id,
                causal_parent_ids=(message.message_id,),
            ),
        )


def _topology() -> CommunicationTopology:
    return CommunicationTopology(
        ("manager", "worker"),
        (
            CommunicationEdge("manager", "worker"),
            CommunicationEdge("worker", "manager"),
        ),
    )


def test_machine_state_is_the_only_multi_agent_recovery_state() -> None:
    topology = _topology()
    with TemporaryDirectory() as directory:
        root = Path(directory) / "journal"
        journal = DirectoryMachineJournal(root)
        runtime = MultiAgentRuntime(
            topology,
            {"manager": _EchoNode("manager"), "worker": _EchoNode("worker")},
            journal=journal,
        )
        initial = MultiAgentMessage(
            "manager",
            "worker",
            "task",
            0,
            conversation_id="conversation-a",
        )
        paused = runtime.run(
            initial,
            max_rounds=4,
            max_messages=1,
        )
        assert paused.status is MultiAgentRunStatus.MAX_MESSAGES
        assert paused.machine_cut.revision > 0

        restarted = MultiAgentRuntime(
            topology,
            {"manager": _EchoNode("manager"), "worker": _EchoNode("worker")},
            journal=DirectoryMachineJournal(root),
        )
        same = restarted.inspect("conversation-a")
        assert same.machine_cut == paused.machine_cut
        assert same.messages == paused.messages
        assert same.pending_messages == paused.pending_messages

        completed = restarted.resume(
            "conversation-a",
            max_rounds=4,
            max_messages=10,
        )
        assert completed.status is MultiAgentRunStatus.COMPLETED
        assert completed.machine_cut.revision > paused.machine_cut.revision


def test_invalid_participant_output_fails_closed_and_is_journaled() -> None:
    topology = _topology()

    class BadWorker:
        def handle(self, message: MultiAgentMessage) -> tuple[MultiAgentMessage, ...]:
            return (
                MultiAgentMessage(
                    "worker",
                    "manager",
                    "bad",
                    message.turn + 1,
                    conversation_id=message.conversation_id,
                    causal_parent_ids=(),
                ),
            )

    runtime = MultiAgentRuntime(
        topology,
        {"manager": _EchoNode("manager"), "worker": BadWorker()},
    )
    result = runtime.run(
        MultiAgentMessage("manager", "worker", "task", 0),
    )
    assert result.status is MultiAgentRunStatus.FAILED
    assert result.error is not None
    assert "causal parent" in result.error
    assert result.machine_cut.revision >= 3
    assert result.messages[0].recipient == "worker"


def test_cancellation_is_a_runtime_transition_not_an_external_checkpoint() -> None:
    class Cancelled:
        def cancelled(self) -> bool:
            return True

    topology = _topology()
    initial = MultiAgentMessage("manager", "worker", "task", 0)
    runtime = MultiAgentRuntime(
        topology,
        {"manager": _EchoNode("manager"), "worker": _EchoNode("worker")},
    )
    paused = runtime.run(initial, cancellation=Cancelled())
    assert paused.status is MultiAgentRunStatus.CANCELLED
    assert paused.pending_messages == (initial,)
    assert paused.messages == ()
    assert paused.machine_cut.revision == 2

    resumed = runtime.resume(
        "default",
        max_rounds=4,
        max_messages=10,
    )
    assert resumed.status is MultiAgentRunStatus.COMPLETED
