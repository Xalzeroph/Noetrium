"""Typed contracts shared by reusable single-agent method components.

These components are method implementations, not Platform authorities. They
accept downstream policies, model clients, and tool ports through narrow seams.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from noetrium.contracts.json import JsonValue, canonical_digest, freeze_json
from noetrium_platform.capabilities.participant.capability.api import CapabilityResult
from noetrium_platform.foundation.kernel.kernel import EffectReceipt


class ReferenceAgentStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    MAX_STEPS = "max_steps"


class ReferenceAgentActionKind(StrEnum):
    TOOL = "tool"
    FINAL = "final"
    CONTINUE = "continue"


@dataclass(frozen=True, slots=True)
class ReferenceAgentMessage:
    role: str
    content: str
    name: str | None = None

    def __post_init__(self) -> None:
        if type(self.role) is not str or not self.role.strip():
            raise ValueError("agent message role must be non-empty")
        if type(self.content) is not str:
            raise TypeError("agent message content must be string")
        if self.name is not None and (type(self.name) is not str or not self.name.strip()):
            raise ValueError("agent message name must be non-empty when present")


@dataclass(frozen=True, slots=True)
class ReferenceAgentState:
    task: str
    messages: tuple[ReferenceAgentMessage, ...] = ()
    scratchpad: tuple[ReferenceAgentMessage, ...] = ()
    step: int = 0

    def __post_init__(self) -> None:
        if type(self.task) is not str or not self.task.strip():
            raise ValueError("agent state task must be non-empty")
        if type(self.messages) is not tuple or any(type(row) is not ReferenceAgentMessage for row in self.messages):
            raise TypeError("agent state messages must contain ReferenceAgentMessage")
        if type(self.scratchpad) is not tuple or any(type(row) is not ReferenceAgentMessage for row in self.scratchpad):
            raise TypeError("agent state scratchpad must contain ReferenceAgentMessage")
        if type(self.step) is not int or isinstance(self.step, bool) or self.step < 0:
            raise ValueError("agent state step must be a non-negative integer")

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ReferenceAgentAction:
    kind: ReferenceAgentActionKind
    name: str
    arguments: Mapping[str, JsonValue] = field(default_factory=dict)
    content: str = ""
    action_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ReferenceAgentActionKind) or type(self.name) is not str or not self.name.strip():
            raise ValueError("agent action kind/name are invalid")
        if type(self.content) is not str:
            raise TypeError("agent action content must be string")
        if not isinstance(self.arguments, Mapping):
            raise TypeError("agent action arguments must be a mapping")
        raw_arguments = tuple(self.arguments.items())
        keys = [row[0] for row in raw_arguments]
        if any(type(key) is not str or not key.strip() for key in keys) or len(keys) != len(set(keys)):
            raise ValueError("agent action argument keys must be unique non-empty strings")
        normalized_arguments = {
            key: freeze_json(value) for key, value in raw_arguments
        }
        frozen_arguments = freeze_json(normalized_arguments)
        object.__setattr__(self, "arguments", frozen_arguments)
        object.__setattr__(self, "action_digest", canonical_digest({"kind": self.kind.value, "name": self.name, "arguments": frozen_arguments, "content": self.content}))

    @classmethod
    def from_mapping(
        cls,
        kind: ReferenceAgentActionKind,
        name: str,
        arguments: Mapping[str, JsonValue] | None = None,
        *,
        content: str = "",
    ) -> "ReferenceAgentAction":
        values = {} if arguments is None else arguments
        if not isinstance(values, Mapping):
            raise TypeError("agent action arguments must be a mapping")
        return cls(kind, name, values, content)

    def argument_values(self) -> dict[str, JsonValue]:
        return dict(self.arguments)

    @property
    def arguments_mapping(self) -> Mapping[str, JsonValue]:
        return self.argument_values()


@dataclass(frozen=True, slots=True)
class ReferenceAgentObservation:
    action_digest: str
    content: str
    success: bool
    capability_id: str | None = None
    result_digest: str | None = None
    artifacts: tuple[str, ...] = ()
    effect_receipt: EffectReceipt | None = None
    capability_result: CapabilityResult | None = None
    observation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.action_digest) is not str or len(self.action_digest) != 64:
            raise ValueError("agent observation action_digest must be SHA-256")
        if type(self.content) is not str or type(self.success) is not bool:
            raise TypeError("agent observation content/success types are invalid")
        if self.capability_id is not None and (type(self.capability_id) is not str or not self.capability_id.strip()):
            raise ValueError("agent observation capability_id must be non-empty when present")
        if self.result_digest is not None and (type(self.result_digest) is not str or len(self.result_digest) != 64):
            raise ValueError("agent observation result_digest must be SHA-256 when present")
        if type(self.artifacts) is not tuple or any(type(item) is not str or not item.strip() for item in self.artifacts):
            raise TypeError("agent observation artifacts must be non-empty strings")
        if self.effect_receipt is not None and not isinstance(self.effect_receipt, EffectReceipt):
            raise TypeError("agent observation effect_receipt must be EffectReceipt")
        if self.capability_result is not None:
            if not isinstance(self.capability_result, CapabilityResult):
                raise TypeError("agent observation capability_result must be CapabilityResult")
            if self.capability_id is not None and self.capability_id != self.capability_result.capability_id:
                raise ValueError("agent observation capability identity disagrees with capability_result")
            result_digest = self.capability_result.digest()
            if self.result_digest is not None and self.result_digest != result_digest:
                raise ValueError("agent observation result_digest disagrees with capability_result")
            if self.artifacts and self.artifacts != self.capability_result.artifacts:
                raise ValueError("agent observation artifacts disagree with capability_result")
            if self.effect_receipt is not None and self.effect_receipt != self.capability_result.effect:
                raise ValueError("agent observation effect disagrees with capability_result")
            object.__setattr__(self, "capability_id", self.capability_result.capability_id)
            object.__setattr__(self, "result_digest", result_digest)
            object.__setattr__(self, "artifacts", self.capability_result.artifacts)
            object.__setattr__(self, "effect_receipt", self.capability_result.effect)
        object.__setattr__(self, "observation_digest", canonical_digest({
            "action_digest": self.action_digest,
            "content": self.content,
            "success": self.success,
            "capability_id": self.capability_id,
            "result_digest": self.result_digest,
            "artifacts": self.artifacts,
            "effect_receipt": self.effect_receipt,
            "capability_result": self.capability_result,
        }))


@dataclass(frozen=True, slots=True)
class ReferenceAgentDecision:
    action: ReferenceAgentAction
    reasoning: str = ""

    def __post_init__(self) -> None:
        if type(self.action) is not ReferenceAgentAction or type(self.reasoning) is not str:
            raise TypeError("agent decision fields are invalid")
@dataclass(frozen=True, slots=True)
class ReferenceAgentRunResult:
    status: ReferenceAgentStatus
    answer: str | None
    state: ReferenceAgentState
    error: str | None = None
    tool_observations: tuple[ReferenceAgentObservation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, ReferenceAgentStatus) or type(self.state) is not ReferenceAgentState:
            raise TypeError("agent run result fields are invalid")
        if self.answer is not None and type(self.answer) is not str:
            raise TypeError("agent run result answer must be string or None")
        if self.error is not None and type(self.error) is not str:
            raise TypeError("agent run result error must be string or None")
        if type(self.tool_observations) is not tuple or any(
            type(item) is not ReferenceAgentObservation for item in self.tool_observations
        ):
            raise TypeError("agent run result tool_observations must contain observations")
        if self.status is ReferenceAgentStatus.COMPLETED and not self.answer:
            raise ValueError("completed agent run requires an answer")


class ReferenceAgentDecisionPort(Protocol):
    def decide(self, state: ReferenceAgentState) -> ReferenceAgentDecision: ...


class ReferenceAgentToolPort(Protocol):
    def invoke(self, name: str, arguments: Mapping[str, JsonValue]) -> ReferenceAgentObservation: ...


class ReferenceAgentActionToolPort(Protocol):
    def invoke_action(self, action: ReferenceAgentAction) -> ReferenceAgentObservation: ...


class ReferenceAgentReflectionPort(Protocol):
    def reflect(self, state: ReferenceAgentState, result: ReferenceAgentRunResult) -> ReferenceAgentMessage: ...


class ReferenceAgentPlannerPort(Protocol):
    def plan(self, task: str) -> tuple[str, ...]: ...


class ReferenceAgentSolverPort(Protocol):
    def solve(self, task: str, plan: tuple[str, ...]) -> ReferenceAgentRunResult: ...


__all__ = [
    "ReferenceAgentAction", "ReferenceAgentActionKind", "ReferenceAgentActionToolPort", "ReferenceAgentDecision", "ReferenceAgentDecisionPort",
    "ReferenceAgentMessage", "ReferenceAgentObservation", "ReferenceAgentPlannerPort", "ReferenceAgentReflectionPort",
    "ReferenceAgentRunResult", "ReferenceAgentSolverPort", "ReferenceAgentState", "ReferenceAgentStatus", "ReferenceAgentToolPort",
]
