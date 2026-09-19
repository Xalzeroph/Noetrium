from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from research.reproductions.self_refine import (
    SELF_REFINE_COMMONGEN_METHOD_PROGRAM,
    self_refine_commongen_initial_state,
)


class _SharedModel:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        assert request.agent_id == "self-refine.model"
        phase = request.view["phase"]
        self.calls.append(phase)
        if phase == "init":
            assert request.view["concepts"] == ("beat", "drum", "pen", "sit", "use")
            return MethodAgentResult(
                value={"sentence": "A man uses a drum to beat a pen."}
            )
        if phase == "feedback" and self.calls.count("feedback") == 1:
            return MethodAgentResult(
                value={
                    "concept_feedback": "sit",
                    "commonsense_feedback": "None",
                }
            )
        if phase == "iterate":
            assert len(request.view["sentence_to_feedback"]) == 1
            return MethodAgentResult(
                value={"sentence": "A man sits and uses a drum to beat a pen."}
            )
        if phase == "feedback":
            return MethodAgentResult(
                value={
                    "concept_feedback": "None",
                    "commonsense_feedback": "None",
                }
            )
        raise AssertionError(phase)


def test_self_refine_commongen_runs_init_feedback_iterate_with_one_shared_model() -> None:
    model = _SharedModel()
    result = UniversalMethodMachine(max_steps=64).run(
        SELF_REFINE_COMMONGEN_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            ExecutionContext("self-refine-run", "trace", "span", task_id="commongen:1"),
            agent_loop=model,
        ),
        initial_state=self_refine_commongen_initial_state(
            task_id="commongen:1",
            concepts=("beat", "drum", "pen", "sit", "use"),
        ),
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["attempt_count"] == 2
    assert result.value["direct_concept_success"] is False
    assert result.value["direct_commonsense_success"] is True
    assert result.value["direct_success"] is False
    assert result.value["iter_concept_success"] is True
    assert result.value["iter_commonsense_success"] is True
    assert result.value["iter_success"] is True
    assert result.value["accepted"] is True
    assert model.calls == ["init", "feedback", "iterate", "feedback"]


def test_self_refine_commongen_program_freezes_paper_batch_budget_and_shared_model() -> None:
    program = SELF_REFINE_COMMONGEN_METHOD_PROGRAM
    assert program.required_capabilities == ()
    assert program.configuration["max_attempts"] == 4
    assert program.configuration["temperature"] == 0.7
    assert program.configuration["max_output_tokens"] == 300
    assert program.configuration["same_model_reused_across_roles"] is True
    assert len(program.configuration["prompt_blobs"]) == 3
    agent_ids = {
        node.agent_id
        for node in program.nodes
        if node.agent_id is not None
    }
    assert agent_ids == {"self-refine.model"}
