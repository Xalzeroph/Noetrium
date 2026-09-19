from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    InMemoryMachineJournal,
    MachineCut,
    MachineJournalPort,
    MachineKind,
    MachineSnapshotStorePort,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    MachineEvent,
    MemoryPresetSpec,
    MemoryRecord,
    ResearchMachineSession,
    default_memory_host,
    memory_initial_data,
)

from ..api.cognition import (
    AgentGoal,
    AgentMemoryContext,
    AgentObservation,
    AgentStepReceipt,
)
from ..api.cognition_ports import AgentMemoryPort


class NoMemoryAgentMemory(AgentMemoryPort):
    """Explicit no-memory ablation; it owns no hidden mutable state."""

    def cut(self) -> MachineCut | None:
        return None

    def recall(
        self,
        goal: AgentGoal,
        observation: AgentObservation,
        context: ExecutionContext,
    ) -> AgentMemoryContext:
        del goal, context
        return AgentMemoryContext(
            context_text="",
            generation=observation.generation,
            query_id="memory-disabled",
        )

    def record(self, receipt: AgentStepReceipt, context: ExecutionContext) -> None:
        del receipt, context


class MachineAgentMemory(AgentMemoryPort):
    """Agent-facing adapter over one journal-backed programmable Memory Machine."""

    def __init__(
        self,
        session: ResearchMachineSession,
        *,
        preset: MemoryPresetSpec = MemoryPresetSpec(),
    ) -> None:
        if not isinstance(session, ResearchMachineSession):
            raise TypeError("agent memory requires ResearchMachineSession")
        if session.machine.identity.kind is not MachineKind.MEMORY:
            raise ValueError("agent memory session must bind a MEMORY machine")
        if not isinstance(preset, MemoryPresetSpec):
            raise TypeError("agent memory preset must be MemoryPresetSpec")
        self._session = session
        self._preset = preset
        if not session.started:
            session.start(
                memory_initial_data(preset),
                command_id=f"{session.machine_id}:start",
            )
        else:
            digest = session.data.get("preset_digest")
            if digest != preset.digest:
                raise ValueError("existing Memory Machine preset identity mismatch")

    @classmethod
    def create_default(
        cls,
        memory_id: str,
        *,
        preset: MemoryPresetSpec = MemoryPresetSpec(),
        journal: MachineJournalPort | None = None,
        snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> "MachineAgentMemory":
        if type(memory_id) is not str or not memory_id.strip():
            raise ValueError("memory_id is required")
        if not isinstance(preset, MemoryPresetSpec):
            raise TypeError("agent memory preset must be MemoryPresetSpec")
        host = default_memory_host(
            journal=journal if journal is not None else InMemoryMachineJournal(),
            snapshot_store=snapshot_store,
            preset=preset,
        )
        session = host.open_session(
            machine_id=f"memory:{memory_id.strip()}",
            instance_identity={
                "memory_id": memory_id.strip(),
                "preset_digest": preset.digest,
            },
            binding=None,
        )
        return cls(session, preset=preset)

    @property
    def session(self) -> ResearchMachineSession:
        return self._session

    @property
    def records(self) -> tuple[MemoryRecord, ...]:
        rows = self._session.data.get("records", ())
        if not isinstance(rows, (tuple, list)):
            raise TypeError("Memory Machine records must be a sequence")
        return tuple(MemoryRecord.from_payload(row) for row in rows)

    def cut(self) -> MachineCut | None:
        head = self._session.machine.journal.latest(self._session.machine_id)
        return None if head is None else MachineCut.from_commit(head)

    @staticmethod
    def _artifact_refs(receipt: AgentStepReceipt) -> tuple[str, ...]:
        refs = receipt.diagnostics.get("artifact_refs", ())
        if isinstance(refs, str) or not isinstance(refs, Sequence):
            return ()
        return tuple(
            value for value in refs
            if type(value) is str and value.strip()
        )

    def _write(self, record: MemoryRecord, *, command_key: str) -> None:
        self._session.step(
            {
                "event": MachineEvent(
                    "memory.write",
                    {"record": record.as_payload()},
                    source="agent",
                ).as_payload()
            },
            command_id=(
                f"{self._session.machine_id}:write:"
                f"{command_key}:{record.record_digest[:16]}"
            ),
        )

    def record(self, receipt: AgentStepReceipt, context: ExecutionContext) -> None:
        if not isinstance(receipt, AgentStepReceipt):
            raise TypeError("agent memory record requires AgentStepReceipt")
        if not isinstance(context, ExecutionContext):
            raise TypeError("agent memory record requires ExecutionContext")
        verified = receipt.accepted and (
            receipt.verified is True or receipt.effect_certainty == "confirmed"
        )
        observation_digest = (
            receipt.observation.state_digest
            if receipt.observation is not None
            else canonical_digest({
                "action_id": receipt.action_id,
                "sequence_id": receipt.sequence_id,
                "effect_id": receipt.effect_id,
            })
        )
        generation = context.generation("environment") or (
            receipt.observation.generation
            if receipt.observation is not None
            else "agent"
        )
        record = MemoryRecord(
            record_id=f"memory:episode:{receipt.action_id}",
            kind="episodic_action",
            content=(
                f"action={receipt.action_type} "
                f"accepted={receipt.accepted} verified={receipt.verified}"
            ),
            generation=generation,
            state_digest=observation_digest,
            tags=tuple(dict.fromkeys((receipt.action_type, receipt.skill_id))),
            verified=verified,
            artifact_refs=self._artifact_refs(receipt),
            metadata={
                "action_id": receipt.action_id,
                "sequence_id": receipt.sequence_id,
                "effect_id": receipt.effect_id,
                "effect_certainty": receipt.effect_certainty,
            },
        )
        self._write(record, command_key=receipt.action_id)

        observation = receipt.observation
        if observation is None:
            return
        position = observation.state.get("position")
        if not isinstance(position, Mapping):
            return
        content = "position " + ",".join(
            f"{axis}={position.get(axis)}" for axis in ("x", "y", "z")
        )
        spatial = MemoryRecord(
            record_id="memory:position:" + observation.state_digest[:20],
            kind="spatial_landmark",
            content=content,
            generation=observation.generation,
            state_digest=observation.state_digest,
            tags=("position", "spatial"),
            verified=True,
            artifact_refs=observation.artifact_refs,
            metadata={"observation_id": observation.observation_id},
        )
        self._write(spatial, command_key=observation.observation_id)

    def recall(
        self,
        goal: AgentGoal,
        observation: AgentObservation,
        context: ExecutionContext,
    ) -> AgentMemoryContext:
        if not isinstance(goal, AgentGoal):
            raise TypeError("agent memory recall requires AgentGoal")
        if not isinstance(observation, AgentObservation):
            raise TypeError("agent memory recall requires AgentObservation")
        if not isinstance(context, ExecutionContext):
            raise TypeError("agent memory recall requires ExecutionContext")
        query_text = (
            goal.objective
            + " "
            + " ".join(str(key) for key in observation.state)
        )
        query_digest = canonical_digest({
            "goal": goal.digest,
            "observation": observation.state_digest,
            "memory_revision": self._session.revision,
        })
        self._session.step(
            {
                "event": MachineEvent(
                    "memory.retrieve",
                    {
                        "query_text": query_text,
                        "generation": observation.generation,
                        "limit": self._preset.recall_limit,
                        "require_verified": True,
                    },
                    source="agent",
                ).as_payload()
            },
            command_id=(
                f"{self._session.machine_id}:recall:"
                f"{self._session.revision}:{query_digest[:16]}"
            ),
        )
        value = self._session.previous_value
        if not isinstance(value, Mapping):
            raise ValueError("Memory Machine retrieval result is missing")
        context_text = value.get("context_text", "")
        query_id = value.get("query_id", "")
        refs = value.get("artifact_refs", ())
        if type(context_text) is not str or type(query_id) is not str:
            raise TypeError("Memory Machine retrieval projection is invalid")
        if isinstance(refs, str) or not isinstance(refs, (tuple, list)):
            raise TypeError("Memory Machine artifact refs must be a sequence")
        return AgentMemoryContext(
            context_text=context_text,
            generation=observation.generation,
            artifacts=tuple(str(value) for value in refs),
            query_id=query_id,
        )

    def verify(self, record_id: str, *, verified: bool = True) -> None:
        self._session.step(
            {
                "event": MachineEvent(
                    "memory.verify",
                    {"record_id": record_id, "verified": verified},
                    source="agent",
                ).as_payload()
            },
            command_id=(
                f"{self._session.machine_id}:verify:"
                f"{record_id}:{int(verified)}:{self._session.revision}"
            ),
        )

    def forget(self, record_ids: tuple[str, ...]) -> None:
        self._session.step(
            {
                "event": MachineEvent(
                    "memory.forget",
                    {"record_ids": record_ids},
                    source="agent",
                ).as_payload()
            },
            command_id=(
                f"{self._session.machine_id}:forget:"
                f"{canonical_digest(record_ids)[:16]}:{self._session.revision}"
            ),
        )

    def compact(self, *, keep: int) -> None:
        self._session.step(
            {
                "event": MachineEvent(
                    "memory.compact",
                    {"keep": keep},
                    source="agent",
                ).as_payload()
            },
            command_id=(
                f"{self._session.machine_id}:compact:"
                f"{keep}:{self._session.revision}"
            ),
        )


__all__ = ["MachineAgentMemory", "NoMemoryAgentMemory"]
