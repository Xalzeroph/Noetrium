from __future__ import annotations

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.foundation.kernel.kernel import EffectClass, ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from research.reproductions.memgpt_classic.program import (
    MEMGPT_CLASSIC_METHOD_PROGRAM,
    memgpt_classic_initial_state,
)


class _ScriptedAgentLoop:
    def __init__(self) -> None:
        self.main_calls = 0
        self.summary_calls = 0

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id == "memgpt.classic.summarizer":
            self.summary_calls += 1
            assert request.previous_value["cutoff"] >= 1
            assert request.previous_value["messages_to_summarize"]
            return MethodAgentResult(value={"summary": "compressed conversation"})

        assert request.agent_id == "memgpt.classic.agent"
        self.main_calls += 1
        if self.main_calls == 1:
            return MethodAgentResult(
                value={
                    "kind": "core_append",
                    "label": "human",
                    "content": "likes graphs",
                }
            )
        if self.main_calls == 2:
            return MethodAgentResult(
                value={
                    "kind": "recall_query",
                    "query": "previous preference",
                    "page": 1,
                }
            )
        if self.main_calls == 3:
            return MethodAgentResult(value={"kind": "context_overflow"})
        return MethodAgentResult(
            value={"kind": "final", "content": "Use a graph-first explanation."}
        )


class _MemoryCapabilities:
    def __init__(self) -> None:
        self.requests: list[CapabilityRequest] = []

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        effect = (
            EffectClass.RECONCILABLE
            if capability_id == "memory.archival.insert"
            else EffectClass.PURE
        )
        return CapabilityDescriptor(
            capability_id,
            "1",
            "json",
            "json",
            effect,
        )

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        self.requests.append(request)
        if request.capability_id == "memory.recall.query":
            return CapabilityResult(
                request.capability_id,
                {"items": ("likes concise answers",)},
            )
        if request.capability_id == "memory.archival.query":
            return CapabilityResult(request.capability_id, {"items": ()})
        if request.capability_id == "memory.archival.insert":
            return CapabilityResult(request.capability_id, {"stored": True})
        raise AssertionError(request.capability_id)


def _context() -> ExecutionContext:
    return ExecutionContext("memgpt-run", "trace-1", "span-1")


def test_memgpt_classic_method_program_runs_memory_and_overflow_semantics() -> None:
    agent_loop = _ScriptedAgentLoop()
    capabilities = _MemoryCapabilities()
    initial_state = memgpt_classic_initial_state(
        core_memory={"human": "name: Alice", "persona": "helpful"},
        messages=(
            {"role": "system", "content": "system"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
        ),
    )

    result = UniversalMethodMachine(max_steps=64).run(
        MEMGPT_CLASSIC_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            _context(),
            capabilities=capabilities,
            agent_loop=agent_loop,
        ),
        input_value={"task": "remember and answer"},
        initial_state=initial_state,
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["response"] == "Use a graph-first explanation."
    assert result.value["turns"] == 3
    assert result.value["memory_query_count"] == 1
    assert result.value["memory_write_count"] == 1
    assert result.value["summary_count"] == 1
    assert result.value["core_memory"]["human"] == "name: Alice\nlikes graphs"
    assert agent_loop.summary_calls == 1

    recall = next(
        request
        for request in capabilities.requests
        if request.capability_id == "memory.recall.query"
    )
    assert recall.payload == {
        "tier": "recall",
        "query": "previous preference",
        "page": 1,
        "count": 5,
        "start": 5,
    }


def test_memgpt_overflow_summary_retries_without_consuming_a_main_turn() -> None:
    agent_loop = _ScriptedAgentLoop()
    initial_state = memgpt_classic_initial_state(
        core_memory={"human": "h", "persona": "p"},
        messages=(
            {"role": "system", "content": "system"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "assistant", "content": "a2"},
        ),
    )
    result = UniversalMethodMachine(max_steps=64).run(
        MEMGPT_CLASSIC_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            _context(),
            capabilities=_MemoryCapabilities(),
            agent_loop=agent_loop,
        ),
        initial_state=initial_state,
    )
    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["turns"] == 3
    assert result.state["summary_count"] == 1
    assert result.state["messages"][0] == {"role": "system", "content": "system"}
    assert result.state["messages"][1]["kind"] == "conversation_summary"
