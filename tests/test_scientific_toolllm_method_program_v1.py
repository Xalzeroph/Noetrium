from __future__ import annotations

import hashlib

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.foundation.kernel.kernel import EffectClass, ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRuntimeContext,
    MethodRunStatus,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from research.reproductions.toolllm_toolbench.program import (
    build_toolllm_toolbench_method_program,
    toolllm_toolbench_initial_state,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _catalog():
    return (
        {
            "capability_id": "weather_for_alpha",
            "descriptor_digest": _digest("weather"),
            "function_schema": {
                "name": "weather_for_alpha",
                "description": "weather",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "capability_id": "news_for_beta",
            "descriptor_digest": _digest("news"),
            "function_schema": {
                "name": "news_for_beta",
                "description": "news",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    )


class _Capabilities:
    def __init__(self, *, retrieval: bool = False) -> None:
        self.requests: list[CapabilityRequest] = []
        self.retrieval = retrieval

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        if capability_id == "data.semantic-similarity":
            return CapabilityDescriptor(
                capability_id, "1", "json", "json", EffectClass.PURE, True
            )
        return CapabilityDescriptor(
            capability_id,
            "1",
            "json",
            "json",
            EffectClass.PURE,
            True,
        )

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        self.requests.append(request)
        if request.capability_id == "data.semantic-similarity":
            return CapabilityResult(
                request.capability_id,
                {
                    "projection_digest": request.payload["projection_digest"],
                    "source_cut_digest": request.payload["source_cut_digest"],
                    "embedding_model_digest": request.payload["embedding_model_digest"],
                    "metric": "cosine_similarity",
                    "candidate_count": 2,
                    "matches": (
                        {
                            "source_id": "tool-catalog",
                            "record_id": "weather_for_alpha",
                            "content_digest": _digest("weather"),
                            "score": 0.99,
                            "rank": 1,
                        },
                    ),
                },
            )
        assert request.capability_id == "weather_for_alpha"
        assert request.payload == {
            "function_name": "weather_for_alpha",
            "arguments": '{"city":"Paris"}',
        }
        return CapabilityResult(
            request.capability_id,
            {"content": '{"temperature":21}', "status": 0},
        )


class _ToolThenFinish:
    def __init__(self) -> None:
        self.calls = 0
        self.views = []

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        self.calls += 1
        self.views.append(request.view)
        if self.calls == 1:
            return MethodAgentResult(
                value={
                    "thought": "Need current weather.",
                    "action_name": "weather_for_alpha",
                    "action_input": {"city": "Paris"},
                }
            )
        return MethodAgentResult(
            value={
                "thought": "I can answer now.",
                "action_name": "Finish",
                "action_input": {
                    "return_type": "give_answer",
                    "final_answer": "Paris is 21 degrees.",
                },
            }
        )


def test_toolllm_oracle_dfsdt_invokes_real_tool_then_finish() -> None:
    program = build_toolllm_toolbench_method_program(
        ("weather_for_alpha", "news_for_beta"),
        retrieval_mode="oracle",
    )
    loop = _ToolThenFinish()
    capabilities = _Capabilities()
    result = UniversalMethodMachine(max_steps=100).run(
        program,
        runtime=MethodRuntimeContext(
            ExecutionContext("toolllm-run", "trace", "span", task_id="toolbench:q1"),
            capabilities=capabilities,
            agent_loop=loop,
        ),
        initial_state=toolllm_toolbench_initial_state(
            task_id="toolbench:q1",
            task_instruction="What is the weather in Paris?",
            tool_catalog=_catalog(),
            allowed_capability_ids=("weather_for_alpha", "news_for_beta"),
            retrieval_mode="oracle",
            oracle_tool_ids=("weather_for_alpha", "news_for_beta"),
        ),
    )
    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["task_success"] is True
    assert result.value["final_answer"] == "Paris is 21 degrees."
    assert result.value["query_count"] == 2
    assert result.value["tool_call_count"] == 1
    assert [row.capability_id for row in capabilities.requests] == [
        "weather_for_alpha"
    ]
    assert len(loop.views[0]["functions"]) == 3
    assert loop.views[0]["search_policy"] == "DFS_woFilter_w2"


class _RestartThenAnswer:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        self.calls += 1
        if self.calls == 1:
            return MethodAgentResult(
                value={
                    "thought": "Try a nonexistent function.",
                    "action_name": "missing_function",
                    "action_input": {},
                }
            )
        if self.calls == 2:
            assert request.view["tree_depth"] == 3
            return MethodAgentResult(
                value={
                    "thought": "This branch is blocked.",
                    "action_name": "Finish",
                    "action_input": {"return_type": "give_up_and_restart"},
                }
            )
        assert request.view["tree_depth"] == 0
        assert len(request.view["previous_siblings"]) == 1
        return MethodAgentResult(
            value={
                "thought": "Use the second root sibling.",
                "action_name": "Finish",
                "action_input": {
                    "return_type": "give_answer",
                    "final_answer": "Recovered after restart.",
                },
            }
        )


def test_toolllm_give_up_prunes_current_frame_and_resumes_parent_sibling() -> None:
    result = UniversalMethodMachine(max_steps=100).run(
        build_toolllm_toolbench_method_program(
            ("weather_for_alpha",),
            retrieval_mode="oracle",
        ),
        runtime=MethodRuntimeContext(
            ExecutionContext("toolllm-restart", "trace", "span", task_id="toolbench:q2"),
            capabilities=_Capabilities(),
            agent_loop=_RestartThenAnswer(),
        ),
        initial_state=toolllm_toolbench_initial_state(
            task_id="toolbench:q2",
            task_instruction="Recover from an invalid path.",
            tool_catalog=(_catalog()[0],),
            allowed_capability_ids=("weather_for_alpha",),
            retrieval_mode="oracle",
            oracle_tool_ids=("weather_for_alpha",),
        ),
    )
    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["task_success"] is True
    assert result.value["give_up_count"] == 1
    assert result.value["query_count"] == 3
    assert result.value["final_answer"] == "Recovered after restart."


def test_toolllm_retrieved_top5_uses_semantic_cut_before_policy() -> None:
    program = build_toolllm_toolbench_method_program(
        ("weather_for_alpha", "news_for_beta"),
        retrieval_mode="retrieved-top5",
    )
    loop = _ToolThenFinish()
    capabilities = _Capabilities(retrieval=True)
    result = UniversalMethodMachine(max_steps=120).run(
        program,
        runtime=MethodRuntimeContext(
            ExecutionContext("toolllm-open", "trace", "span", task_id="toolbench:q3"),
            capabilities=capabilities,
            agent_loop=loop,
        ),
        initial_state=toolllm_toolbench_initial_state(
            task_id="toolbench:q3",
            task_instruction="What is the weather in Paris?",
            tool_catalog=_catalog(),
            allowed_capability_ids=("weather_for_alpha", "news_for_beta"),
            retrieval_mode="retrieved-top5",
            retrieval_query_vector=(1.0, 0.0),
            projection_digest=_digest("projection"),
            source_cut_digest=_digest("source-cut"),
            embedding_model_digest=_digest("retriever"),
        ),
    )
    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["task_success"] is True
    assert result.value["selected_tool_ids"] == ("weather_for_alpha",)
    assert [row.capability_id for row in capabilities.requests] == [
        "data.semantic-similarity",
        "weather_for_alpha",
    ]
    assert tuple(
        schema["name"] for schema in loop.views[0]["functions"]
    ) == ("weather_for_alpha", "Finish")


class _LenientFinish:
    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        del request
        # Deliberately malformed JSON. The released RapidAPI wrapper extracts
        # these literal markers instead of rejecting the model turn outright.
        return MethodAgentResult(
            value={
                "action_name": "Finish",
                "action_input": (
                    '{"return_type": "give_answer", '
                    '"final_answer": "answer from fallback parser'
                ),
            }
        )


def test_toolllm_finish_preserves_paper_era_lenient_fallback_parser() -> None:
    result = UniversalMethodMachine(max_steps=40).run(
        build_toolllm_toolbench_method_program(
            ("weather_for_alpha",),
            retrieval_mode="oracle",
        ),
        runtime=MethodRuntimeContext(
            ExecutionContext(
                "toolllm-lenient-finish",
                "trace",
                "span",
                task_id="toolbench:q-lenient",
            ),
            capabilities=_Capabilities(),
            agent_loop=_LenientFinish(),
        ),
        initial_state=toolllm_toolbench_initial_state(
            task_id="toolbench:q-lenient",
            task_instruction="Return the answer.",
            tool_catalog=(_catalog()[0],),
            allowed_capability_ids=("weather_for_alpha",),
            retrieval_mode="oracle",
            oracle_tool_ids=("weather_for_alpha",),
        ),
    )
    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["task_success"] is True
    assert result.value["final_answer"] == "answer from fallback parser"
    assert result.value["query_count"] == 1
