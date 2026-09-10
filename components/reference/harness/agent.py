"""Replaceable agent-loop seams for the universal research Harness."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from noetrium.contracts.json import JsonValue, canonical_digest, freeze_json

from components.reference.single_agent.agent.contracts import (
    ReferenceAgentRunResult,
    ReferenceAgentState,
)
from components.reference.single_agent.agent.methods import ReferenceReActMethod
from components.reference.single_agent.agent.harness import ReferenceAgentHarness


class HarnessAgentLoopPort(Protocol):
    loop_id: str
    loop_digest: str

    def run(
        self,
        task: str,
        *,
        max_steps: int = 16,
        initial_state: ReferenceAgentState | None = None,
    ) -> ReferenceAgentRunResult:
        ...


@dataclass(frozen=True, slots=True)
class CallableAgentLoop:
    """A downstream-owned loop with a stable identity and typed result."""

    loop_id: str
    runner: Callable[..., ReferenceAgentRunResult]
    revision: str = "1"
    loop_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.loop_id) is not str or not self.loop_id.strip():
            raise ValueError("agent loop id must be non-empty")
        if not callable(self.runner):
            raise TypeError("agent loop runner must be callable")
        if type(self.revision) is not str or not self.revision.strip():
            raise ValueError("agent loop revision must be non-empty")
        object.__setattr__(self, "loop_digest", canonical_digest({
            "loop_id": self.loop_id,
            "revision": self.revision,
        }))

    def run(
        self,
        task: str,
        *,
        max_steps: int = 16,
        initial_state: ReferenceAgentState | None = None,
    ) -> ReferenceAgentRunResult:
        result = self.runner(
            task,
            max_steps=max_steps,
            initial_state=initial_state,
        )
        if type(result) is not ReferenceAgentRunResult:
            raise TypeError("agent loop runner must return ReferenceAgentRunResult")
        return result


@dataclass(frozen=True, slots=True)
class ReferenceReActLoop:
    """Default loop adapter; policy, tools, hooks, and model remain injected."""

    harness: ReferenceAgentHarness
    loop_id: str = "reference-react"
    revision: str = "1"
    loop_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.harness, ReferenceAgentHarness):
            raise TypeError("ReferenceReActLoop requires ReferenceAgentHarness")
        object.__setattr__(self, "loop_digest", canonical_digest({
            "loop_id": self.loop_id,
            "revision": self.revision,
        }))

    def run(
        self,
        task: str,
        *,
        max_steps: int = 16,
        initial_state: ReferenceAgentState | None = None,
    ) -> ReferenceAgentRunResult:
        return self.harness.run(
            task,
            max_steps=max_steps,
            initial_state=initial_state,
        )


@dataclass(frozen=True, slots=True)
class AgentLoopNode:
    """Invoke the selected loop from a Harness service container."""

    service_key: str = "agent_loop"
    task_key: str = "task"
    result_key: str = "agent_result"
    max_steps: int = 16

    def run(self, context: object, state: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        require = getattr(context, "require", None)
        if not callable(require):
            raise TypeError("agent loop node requires a HarnessContext")
        loop = require(self.service_key)
        if not callable(getattr(loop, "run", None)):
            raise TypeError(f"service {self.service_key!r} is not an agent loop")
        task = state.get(self.task_key)
        if type(task) is not str or not task.strip():
            raise ValueError(f"agent loop node requires non-empty state[{self.task_key!r}]")
        result = loop.run(task, max_steps=self.max_steps)
        if not isinstance(result, ReferenceAgentRunResult):
            raise TypeError("agent loop must return ReferenceAgentRunResult")
        return {
            self.result_key: freeze_json({
                "status": result.status.value,
                "answer": result.answer,
                "error": result.error,
                "state_digest": result.state.digest,
                "tool_observation_count": len(result.tool_observations),
            }),
        }


__all__ = [
    "AgentLoopNode",
    "CallableAgentLoop",
    "HarnessAgentLoopPort",
    "ReferenceReActLoop",
]
