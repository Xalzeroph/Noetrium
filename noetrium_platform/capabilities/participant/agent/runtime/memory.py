from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Mapping

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_digest

from ..api.cognition import (
    AgentActionSequence,
    AgentGoal,
    AgentMemoryContext,
    AgentObservation,
    AgentStepReceipt,
)
from ..api.cognition_ports import AgentMemoryPort
from ..api.memory_checkpoint import AgentMemoryCheckpoint, AgentMemoryCheckpointRecord


class MemoryPlane:
    MEMORY = "mem"
    AUDIT = "audit"


@dataclass(frozen=True, slots=True)
class AgentMemoryRecord:
    memory_id: str
    plane: str
    kind: str
    content: str
    generation: str
    state_digest: str
    tags: tuple[str, ...] = ()
    verified: bool = False
    step: int = 0
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (self.memory_id, self.plane, self.kind, self.content, self.generation)):
            raise ValueError("agent memory identity and content are required")
        if self.plane not in {MemoryPlane.MEMORY, MemoryPlane.AUDIT}:
            raise ValueError("agent memory plane is invalid")
        if self.step < 0:
            raise ValueError("agent memory step cannot be negative")


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_:-]+", value.lower()) if len(token) > 1}


class DisabledAgentMemory(AgentMemoryPort):
    """Explicit no-memory implementation for controlled ablations."""

    def recall(self, goal: AgentGoal, observation: AgentObservation, context: ExecutionContext) -> AgentMemoryContext:
        del goal, context
        return AgentMemoryContext(
            context_text="",
            generation=observation.generation,
            query_id="memory-disabled",
        )

    def record(self, receipt: AgentStepReceipt, context: ExecutionContext) -> None:
        del receipt, context

    def checkpoint(self) -> AgentMemoryCheckpoint:
        return AgentMemoryCheckpoint(sequence_counter=0, records=())

    def restore(self, checkpoint: AgentMemoryCheckpoint) -> None:
        if not isinstance(checkpoint, AgentMemoryCheckpoint):
            raise TypeError("checkpoint must be an AgentMemoryCheckpoint")


class InMemoryAgentMemory(AgentMemoryPort):
    """Episodic + spatial memory with a strict verified-memory read firewall."""

    def __init__(self, *, max_records: int = 2048, recall_limit: int = 12) -> None:
        if max_records < 1 or recall_limit < 1:
            raise ValueError("memory limits must be positive")
        self._max_records = max_records
        self._recall_limit = recall_limit
        self._records: list[AgentMemoryRecord] = []
        self._sequence_counter = 0

    @property
    def records(self) -> tuple[AgentMemoryRecord, ...]:
        return tuple(self._records)

    def record_observation(self, observation: AgentObservation, *, step: int = 0) -> None:
        state = observation.state
        position = state.get("position")
        if isinstance(position, Mapping):
            content = "position " + ",".join(f"{axis}={position.get(axis)}" for axis in ("x", "y", "z"))
            self._append(
                AgentMemoryRecord(
                    memory_id="memory:position:" + observation.state_digest[:20],
                    plane=MemoryPlane.MEMORY,
                    kind="spatial_landmark",
                    content=content,
                    generation=observation.generation,
                    state_digest=observation.state_digest,
                    tags=("position", "spatial"),
                    verified=True,
                    step=step,
                    artifact_refs=observation.artifact_refs,
                )
            )

    def recall(self, goal: AgentGoal, observation: AgentObservation, context: ExecutionContext) -> AgentMemoryContext:
        query = _tokens(goal.objective + " " + " ".join(str(key) for key in observation.state))
        scored: list[tuple[int, int, AgentMemoryRecord]] = []
        for index, record in enumerate(self._records):
            if record.plane != MemoryPlane.MEMORY or not record.verified:
                continue
            overlap = len(query & _tokens(record.content + " " + " ".join(record.tags)))
            generation_bonus = 2 if record.generation == observation.generation else 0
            score = overlap * 5 + generation_bonus + min(record.step, 100) // 10
            if score:
                scored.append((score, index, record))
        scored.sort(key=lambda item: (-item[0], -item[1]))
        selected = [item[2] for item in scored[: self._recall_limit]]
        lines = [f"[{record.kind}] {record.content}" for record in selected]
        return AgentMemoryContext(
            context_text="\n".join(lines),
            generation=observation.generation,
            artifacts=tuple(ref for record in selected for ref in record.artifact_refs),
            query_id="memory-query:" + canonical_digest({"goal": goal.digest, "state": observation.state_digest}),
        )

    def record(self, receipt: AgentStepReceipt, context: ExecutionContext) -> None:
        self._sequence_counter += 1
        verified = receipt.accepted and (
            receipt.verified is True or receipt.effect_certainty == "confirmed"
        )
        observation_digest = receipt.observation.state_digest if receipt.observation else "unknown"
        self._append(
            AgentMemoryRecord(
                memory_id=f"memory:episode:{self._sequence_counter}",
                plane=MemoryPlane.MEMORY,
                kind="episodic_action",
                content=f"action={receipt.action_type} accepted={receipt.accepted} verified={receipt.verified}",
                generation=context.generation("environment") or "agent",
                state_digest=observation_digest,
                tags=(receipt.action_type, receipt.skill_id),
                verified=verified,
                step=self._sequence_counter,
                artifact_refs=tuple(str(value) for value in receipt.diagnostics.get("artifact_refs", []) if isinstance(value, str)),
            )
        )
        if receipt.observation is not None:
            self.record_observation(receipt.observation, step=self._sequence_counter)

    def record_sequence(self, sequence: AgentActionSequence, receipts: tuple[AgentStepReceipt, ...], *, success: bool, context: ExecutionContext) -> None:
        if not receipts:
            return
        summary = ",".join(step.action_type for step in sequence.steps)
        self._append(
            AgentMemoryRecord(
                memory_id="memory:skill:" + canonical_digest({"sequence": sequence.sequence_id, "success": success})[:20],
                plane=MemoryPlane.MEMORY,
                kind="skill_episode",
                content=f"skill={sequence.skill_id} success={success} actions={summary}",
                generation=context.generation("environment") or "agent",
                state_digest=receipts[-1].observation.state_digest if receipts[-1].observation else "unknown",
                tags=(sequence.skill_id, "success" if success else "failure"),
                verified=success and all(receipt.accepted and (receipt.verified is True or receipt.effect_certainty == "confirmed") for receipt in receipts),
            )
        )

    def _append(self, record: AgentMemoryRecord) -> None:
        self._records = [existing for existing in self._records if existing.memory_id != record.memory_id]
        self._records.append(record)
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records :]

    def snapshot(self) -> tuple[AgentMemoryRecord, ...]:
        return tuple(self._records)

    def checkpoint(self) -> AgentMemoryCheckpoint:
        return AgentMemoryCheckpoint(
            sequence_counter=self._sequence_counter,
            records=tuple(
                AgentMemoryCheckpointRecord(
                    memory_id=record.memory_id,
                    plane=record.plane,
                    kind=record.kind,
                    content=record.content,
                    generation=record.generation,
                    state_digest=record.state_digest,
                    tags=record.tags,
                    verified=record.verified,
                    step=record.step,
                    artifact_refs=record.artifact_refs,
                )
                for record in self._records
            ),
        )

    def restore(self, checkpoint: AgentMemoryCheckpoint) -> None:
        if not isinstance(checkpoint, AgentMemoryCheckpoint):
            raise TypeError("checkpoint must be an AgentMemoryCheckpoint")
        if len(checkpoint.records) > self._max_records:
            raise ValueError("agent memory checkpoint exceeds configured record capacity")
        restored = [
            AgentMemoryRecord(
                memory_id=record.memory_id,
                plane=record.plane,
                kind=record.kind,
                content=record.content,
                generation=record.generation,
                state_digest=record.state_digest,
                tags=record.tags,
                verified=record.verified,
                step=record.step,
                artifact_refs=record.artifact_refs,
            )
            for record in checkpoint.records
        ]
        self._records = restored
        self._sequence_counter = checkpoint.sequence_counter


__all__ = ["AgentMemoryRecord", "DisabledAgentMemory", "InMemoryAgentMemory", "MemoryPlane"]
