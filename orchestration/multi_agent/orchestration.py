"""Machine-backed reference multi-agent Runtime.

This facade drives one Runtime Machine per topology/conversation. It owns no
durable queue, transcript, checkpoint, round counter or delivery history.
"""

from __future__ import annotations

from noetrium.contracts.json import canonical_digest
from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineCut,
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
)
from noetrium_platform.research.execution.machines import (
    MachineEvent,
    ResearchMachineSession,
    ResearchProgramHost,
)

from .contracts import (
    CommunicationTopology,
    MultiAgentCancellationPort,
    MultiAgentMessage,
    MultiAgentNodePort,
    MultiAgentRunResult,
    MultiAgentRunStatus,
)
from .program import (
    compile_multi_agent_runtime_program,
    message_from_payload,
    message_payload,
    multi_agent_handlers,
    multi_agent_initial_data,
    multi_agent_rule_set,
    receipt_from_payload,
)


class MultiAgentRuntime:
    """Reference multi-agent driver over the universal Runtime Machine."""

    def __init__(
        self,
        topology: CommunicationTopology,
        nodes: dict[str, MultiAgentNodePort],
        *,
        journal: MachineJournalPort | None = None,
        snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> None:
        if not isinstance(topology, CommunicationTopology):
            raise TypeError(
                "multi-agent Runtime requires CommunicationTopology"
            )
        if set(nodes) != set(topology.nodes) or any(
            not callable(getattr(node, "handle", None))
            for node in nodes.values()
        ):
            raise ValueError(
                "multi-agent Runtime nodes must exactly match topology"
            )
        self._topology = topology
        self._nodes = dict(nodes)
        self._journal = (
            journal if journal is not None else InMemoryMachineJournal()
        )
        self._snapshot_store = snapshot_store
        self._program = compile_multi_agent_runtime_program()
        self._host = ResearchProgramHost(
            host_id="runtime.multi-agent",
            program=self._program,
            journal=self._journal,
            snapshot_store=self._snapshot_store,
            base_handlers=multi_agent_handlers(self._topology),
            dependency_identity={
                "topology_digest": self._topology.topology_digest,
                "nodes": tuple(sorted(self._nodes)),
                "rule_set_digest": multi_agent_rule_set().rule_set_digest,
            },
        )

    @property
    def topology(self) -> CommunicationTopology:
        return self._topology

    @property
    def journal(self) -> MachineJournalPort:
        return self._journal

    def _machine_id(self, conversation_id: str) -> str:
        if type(conversation_id) is not str or not conversation_id.strip():
            raise ValueError("multi-agent conversation_id is required")
        identity = canonical_digest({
            "topology_digest": self._topology.topology_digest,
            "conversation_id": conversation_id,
        })
        return f"runtime:multi-agent:{identity[:32]}"

    def _session(self, conversation_id: str) -> ResearchMachineSession:
        return self._host.open_session(
            machine_id=self._machine_id(conversation_id),
            instance_identity={
                "topology_digest": self._topology.topology_digest,
                "conversation_id": conversation_id,
            },
            binding=None,
        )

    @staticmethod
    def _limits(max_rounds: int, max_messages: int) -> None:
        if type(max_rounds) is not int or max_rounds <= 0:
            raise ValueError("multi-agent max_rounds must be positive")
        if type(max_messages) is not int or max_messages <= 0:
            raise ValueError("multi-agent max_messages must be positive")

    def run(
        self,
        initial: MultiAgentMessage,
        *,
        max_rounds: int = 8,
        max_messages: int = 10_000,
        cancellation: MultiAgentCancellationPort | None = None,
    ) -> MultiAgentRunResult:
        return self.run_many(
            (initial,),
            max_rounds=max_rounds,
            max_messages=max_messages,
            cancellation=cancellation,
        )

    def run_many(
        self,
        initials: tuple[MultiAgentMessage, ...],
        *,
        max_rounds: int = 8,
        max_messages: int = 10_000,
        cancellation: MultiAgentCancellationPort | None = None,
    ) -> MultiAgentRunResult:
        self._limits(max_rounds, max_messages)
        initial_data = multi_agent_initial_data(self._topology, initials)
        conversation_id = initials[0].conversation_id
        session = self._session(conversation_id)
        if session.started:
            raise RuntimeError(
                "multi-agent Runtime already exists; use resume()"
            )
        session.start(
            initial_data,
            command_id=f"{session.machine_id}:start",
        )
        return self._drive(
            session,
            max_rounds=max_rounds,
            max_messages=max_messages,
            cancellation=cancellation,
        )

    def resume(
        self,
        conversation_id: str,
        *,
        max_rounds: int = 8,
        max_messages: int = 10_000,
        cancellation: MultiAgentCancellationPort | None = None,
    ) -> MultiAgentRunResult:
        self._limits(max_rounds, max_messages)
        session = self._session(conversation_id)
        if not session.started:
            raise KeyError(
                f"no multi-agent Runtime for conversation: {conversation_id}"
            )
        if session.status is MachineStatus.WAITING:
            session.resume(
                command_id=(
                    f"{session.machine_id}:resume:{session.revision}"
                )
            )
        if session.status in {
            MachineStatus.COMPLETED,
            MachineStatus.FAILED,
        }:
            return self._result(session)
        return self._drive(
            session,
            max_rounds=max_rounds,
            max_messages=max_messages,
            cancellation=cancellation,
        )

    def inspect(self, conversation_id: str) -> MultiAgentRunResult:
        session = self._session(conversation_id)
        if not session.started:
            raise KeyError(
                f"no multi-agent Runtime for conversation: {conversation_id}"
            )
        return self._result(session)

    def _pause(
        self,
        session: ResearchMachineSession,
        *,
        reason: str,
    ) -> None:
        if session.status is not MachineStatus.RUNNABLE:
            return
        session.step(
            {
                "event": MachineEvent(
                    "multi_agent.pause",
                    {"reason": reason},
                    source="operator",
                ).as_payload()
            },
            command_id=(
                f"{session.machine_id}:pause:{session.revision}"
            ),
        )

    def _select(
        self,
        session: ResearchMachineSession,
        *,
        max_rounds: int,
        max_messages: int,
    ) -> None:
        session.step(
            {
                "event": MachineEvent(
                    "multi_agent.select",
                    {
                        "max_rounds": max_rounds,
                        "max_messages": max_messages,
                    },
                    source="runtime",
                ).as_payload()
            },
            command_id=(
                f"{session.machine_id}:select:{session.revision}"
            ),
        )

    def _complete(
        self,
        session: ResearchMachineSession,
        message: MultiAgentMessage,
        outputs: tuple[MultiAgentMessage, ...],
    ) -> None:
        session.step(
            {
                "event": MachineEvent(
                    "multi_agent.complete",
                    {
                        "message_id": message.message_id,
                        "outputs": tuple(
                            message_payload(output) for output in outputs
                        ),
                    },
                    source=message.recipient,
                ).as_payload()
            },
            command_id=(
                f"{session.machine_id}:complete:"
                f"{message.message_id}:{session.revision}"
            ),
        )

    def _fail(
        self,
        session: ResearchMachineSession,
        message: MultiAgentMessage,
        exc: BaseException,
    ) -> None:
        if session.status is not MachineStatus.RUNNABLE:
            return
        error = f"{type(exc).__name__}: {exc}"
        session.step(
            {
                "event": MachineEvent(
                    "multi_agent.fail",
                    {
                        "message_id": message.message_id,
                        "error": error,
                    },
                    source=message.recipient,
                ).as_payload()
            },
            command_id=(
                f"{session.machine_id}:fail:"
                f"{message.message_id}:{session.revision}"
            ),
        )

    def _in_flight(
        self,
        session: ResearchMachineSession,
    ) -> MultiAgentMessage | None:
        value = session.data.get("in_flight")
        return None if value is None else message_from_payload(value)

    def _drive(
        self,
        session: ResearchMachineSession,
        *,
        max_rounds: int,
        max_messages: int,
        cancellation: MultiAgentCancellationPort | None,
    ) -> MultiAgentRunResult:
        while session.status is MachineStatus.RUNNABLE:
            if (
                cancellation is not None
                and cancellation.cancelled()
            ):
                self._pause(session, reason="cancelled")
                break

            message = self._in_flight(session)
            if message is None:
                self._select(
                    session,
                    max_rounds=max_rounds,
                    max_messages=max_messages,
                )
                if session.status is not MachineStatus.RUNNABLE:
                    break
                message = self._in_flight(session)
                if message is None:
                    raise RuntimeError(
                        "multi-agent selection committed without in-flight message"
                    )

            if (
                cancellation is not None
                and cancellation.cancelled()
            ):
                self._pause(session, reason="cancelled")
                break

            try:
                outputs = self._nodes[message.recipient].handle(message)
                if type(outputs) is not tuple or any(
                    type(output) is not MultiAgentMessage
                    for output in outputs
                ):
                    raise TypeError(
                        "multi-agent node must return tuple[MultiAgentMessage, ...]"
                    )
                self._complete(session, message, outputs)
            except Exception as exc:
                self._fail(session, message, exc)
                break
        return self._result(session)

    def _result(
        self,
        session: ResearchMachineSession,
    ) -> MultiAgentRunResult:
        data = session.data
        topology_digest = data.get("topology_digest")
        conversation_id = data.get("conversation_id")
        rounds = data.get("rounds", 0)
        run_status = data.get(
            "run_status",
            MultiAgentRunStatus.RUNNING.value,
        )
        if type(topology_digest) is not str:
            raise TypeError("multi-agent topology state is invalid")
        if type(conversation_id) is not str:
            raise TypeError("multi-agent conversation state is invalid")
        if type(rounds) is not int or rounds < 0:
            raise ValueError("multi-agent rounds state is invalid")

        delivered_value = data.get("delivered", ())
        pending_value = data.get("pending", ())
        receipts_value = data.get("receipts", ())
        if not isinstance(delivered_value, (tuple, list)):
            raise TypeError("multi-agent delivered state is invalid")
        if not isinstance(pending_value, (tuple, list)):
            raise TypeError("multi-agent pending state is invalid")
        if not isinstance(receipts_value, (tuple, list)):
            raise TypeError("multi-agent receipt state is invalid")

        delivered = tuple(
            message_from_payload(value) for value in delivered_value
        )
        pending = [
            message_from_payload(value) for value in pending_value
        ]
        in_flight = self._in_flight(session)
        if in_flight is not None:
            pending.insert(0, in_flight)
        receipts = tuple(
            receipt_from_payload(value) for value in receipts_value
        )
        head = session.machine.journal.latest(session.machine_id)
        if head is None:
            raise RuntimeError("multi-agent Runtime has no journal head")
        status = MultiAgentRunStatus(run_status)
        return MultiAgentRunResult(
            topology_digest=topology_digest,
            conversation_id=conversation_id,
            messages=delivered,
            pending_messages=tuple(pending),
            rounds=rounds,
            terminated=(
                status is MultiAgentRunStatus.COMPLETED
                and not pending
            ),
            status=status,
            receipts=receipts,
            machine_cut=MachineCut.from_commit(head),
            error=(
                data.get("error")
                if isinstance(data.get("error"), str)
                else None
            ),
        )


def group_chat_initial_messages(
    topology: CommunicationTopology,
    moderator: str,
    topic: str,
    *,
    conversation_id: str = "default",
) -> tuple[MultiAgentMessage, ...]:
    neighbors = topology.neighbors(moderator)
    if not neighbors:
        raise ValueError("group chat moderator has no participants")
    return tuple(
        MultiAgentMessage(
            moderator,
            target,
            topic,
            0,
            conversation_id=conversation_id,
        )
        for target in neighbors
    )


def debate_initial_message(
    topology: CommunicationTopology,
    proposer: str,
    judge: str,
    topic: str,
    *,
    conversation_id: str = "default",
) -> MultiAgentMessage:
    if not topology.can_send(proposer, judge):
        raise ValueError("debate proposer cannot route to judge")
    return MultiAgentMessage(
        proposer,
        judge,
        topic,
        0,
        conversation_id=conversation_id,
    )


def hierarchical_initial_message(
    topology: CommunicationTopology,
    manager: str,
    worker: str,
    task: str,
    *,
    conversation_id: str = "default",
) -> MultiAgentMessage:
    if not topology.can_send(manager, worker):
        raise ValueError("hierarchical manager cannot route to worker")
    return MultiAgentMessage(
        manager,
        worker,
        task,
        0,
        conversation_id=conversation_id,
    )


__all__ = [
    "MultiAgentRuntime",
    "debate_initial_message",
    "group_chat_initial_messages",
    "hierarchical_initial_message",
]
