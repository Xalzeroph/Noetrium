from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from research.benchmarks.gsm8k import GSM8KTaskRecord, build_gsm8k_task_set
from research.reproductions.self_consistency_gsm8k import (
    SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM,
    build_self_consistency_gsm8k_study,
    extract_gsm8k_sample_answer,
    self_consistency_gsm8k_initial_state,
)


class _Sampler:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        self.calls += 1
        assert request.view["sample_count"] == 40
        assert request.view["sampling"] == {
            "strategy": "temperature_top_k",
            "temperature": 0.7,
            "top_k": 40,
        }
        answer = 9 if self.calls <= 25 else 8
        return MethodAgentResult(
            value=f"Reasoning path {self.calls}. The answer is {answer}."
        )


def test_self_consistency_samples_40_paths_and_marginalizes_answers() -> None:
    sampler = _Sampler()
    result = UniversalMethodMachine(max_steps=128).run(
        SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            ExecutionContext("sc-run", "trace", "span", task_id="gsm8k:test:00000"),
            agent_loop=sampler,
        ),
        initial_state=self_consistency_gsm8k_initial_state(
            task_id="gsm8k:test:00000",
            question="Janet's ducks lay 16 eggs...",
        ),
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert sampler.calls == 40
    assert result.value["reasoning_path_count"] == 40
    assert result.value["selected_answer"] == "9"
    assert result.value["selected_vote_count"] == 25


def test_self_consistency_normalizes_task_specific_numeric_answers() -> None:
    assert extract_gsm8k_sample_answer("The answer is 1,200.") == "1200"
    assert extract_gsm8k_sample_answer("work 3.5 then Answer: 3.50") == "3.5"


def test_self_consistency_study_freezes_paper_sampling_repetitions() -> None:
    records = tuple(
        GSM8KTaskRecord("test", index, "1" * 64, "2" * 64, "3" * 64)
        for index in range(1319)
    )
    benchmark = build_gsm8k_task_set(records, dataset_content_sha256="b" * 64)
    study = build_self_consistency_gsm8k_study(benchmark)

    assert study.repetitions == 10
    assert study.execution_policy.trial_budget.max_model_calls == 40
    assert {
        row.measurement_id for row in study.measurement_protocol.definitions
    } == {"model_call_count", "selected_vote_count", "task_success"}
