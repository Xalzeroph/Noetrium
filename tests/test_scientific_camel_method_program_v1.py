from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from research.reproductions.camel_role_playing import (
    CAMEL_AI_SOCIETY_METHOD_PROGRAM,
    camel_ai_society_initial_state,
)


class _TaskDoneModels:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        phase = request.view["phase"]
        self.calls.append((request.agent_id, phase))
        if phase == "task_specification":
            return MethodAgentResult(value={"content": "Build a detailed market analysis."})
        if phase == "task_planning":
            return MethodAgentResult(value={"content": "1. Collect data. 2. Analyze it."})
        if phase == "hidden_assistant_bootstrap":
            return MethodAgentResult(value={"content": "hidden bootstrap response"})
        if phase == "user_agent":
            return MethodAgentResult(value={"content": "<CAMEL_TASK_DONE>"})
        if phase == "assistant_agent":
            return MethodAgentResult(value={"content": "generated but not publicly saved"})
        raise AssertionError(phase)


def _initial():
    return camel_ai_society_initial_state(
        task_id="camel-ai-society:001:001:001",
        assistant_role="Python Programmer",
        user_role="Stock Trader",
        original_task="Develop a trading bot.",
    )


def test_camel_task_done_saves_user_message_but_not_already_generated_assistant_reply() -> None:
    models = _TaskDoneModels()
    result = UniversalMethodMachine(max_steps=128).run(
        CAMEL_AI_SOCIETY_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            ExecutionContext(
                "camel-run",
                "trace",
                "span",
                task_id="camel-ai-society:001:001:001",
            ),
            agent_loop=models,
        ),
        initial_state=_initial(),
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["task_done"] is True
    assert result.value["termination_reason"] == "<CAMEL_TASK_DONE>"
    assert result.value["num_messages"] == 1
    assert result.value["transcript"] == (
        {"speaker": "user", "content": "<CAMEL_TASK_DONE>"},
    )
    assert models.calls == [
        ("camel.task-specifier", "task_specification"),
        ("camel.task-planner", "task_planning"),
        ("camel.assistant-agent", "hidden_assistant_bootstrap"),
        ("camel.user-agent", "user_agent"),
        ("camel.assistant-agent", "assistant_agent"),
    ]


class _NoInstructionModels:
    def __init__(self) -> None:
        self.user_calls = 0
        self.assistant_calls = 0

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        phase = request.view["phase"]
        if phase == "task_specification":
            return MethodAgentResult(value={"content": "Specified task"})
        if phase == "task_planning":
            return MethodAgentResult(value={"content": "Plan"})
        if phase == "hidden_assistant_bootstrap":
            return MethodAgentResult(value={"content": "bootstrap"})
        if phase == "user_agent":
            self.user_calls += 1
            return MethodAgentResult(value={"content": f"request without marker {self.user_calls}"})
        if phase == "assistant_agent":
            self.assistant_calls += 1
            return MethodAgentResult(value={"content": f"solution {self.assistant_calls}"})
        raise AssertionError(phase)


def test_camel_third_missing_instruction_pair_is_generated_but_not_saved() -> None:
    models = _NoInstructionModels()
    result = UniversalMethodMachine(max_steps=128).run(
        CAMEL_AI_SOCIETY_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            ExecutionContext(
                "camel-run-2",
                "trace",
                "span",
                task_id="camel-ai-society:001:001:001",
            ),
            agent_loop=models,
        ),
        initial_state=_initial(),
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["termination_reason"] == "user_no_instruct_threshold"
    assert result.value["num_messages"] == 4
    assert len(result.value["transcript"]) == 4
    assert models.user_calls == 3
    assert models.assistant_calls == 3


def test_camel_method_program_freezes_paper_message_and_prompt_semantics() -> None:
    program = CAMEL_AI_SOCIETY_METHOD_PROGRAM
    assert program.required_capabilities == ()
    assert program.configuration["max_saved_messages"] == 40
    assert program.configuration["task_specifier_temperature"] == 1.4
    assert program.configuration["default_chat_temperature"] == 0.2
    assert program.configuration["repeat_threshold_breaks_inner_loop_only"] is True
    assert len(program.configuration["prompt_blobs"]) == 3
    assert len(program.configuration["role_blobs"]) == 2
