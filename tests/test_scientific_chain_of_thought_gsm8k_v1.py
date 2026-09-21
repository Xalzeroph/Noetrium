from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_digest
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from research.benchmarks.gsm8k import GSM8KTaskRecord, build_gsm8k_task_set
from research.reproductions.chain_of_thought_gsm8k import (
    CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM,
    build_chain_of_thought_gsm8k_study,
    chain_of_thought_gsm8k_initial_state,
)
from research.reproductions.chain_of_thought_gsm8k.runtime import _model_identity


class _Reasoner:
    def __init__(self) -> None:
        self.views = []

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        self.views.append(request.view)
        return MethodAgentResult(
            value="Janet has 16 eggs. She eats 3 and bakes 4, so 16-3-4=9. The answer is 9."
        )


def test_chain_of_thought_runs_one_greedy_eight_shot_reasoning_path() -> None:
    reasoner = _Reasoner()
    result = UniversalMethodMachine(max_steps=8).run(
        CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            ExecutionContext("cot-run", "trace", "span", task_id="gsm8k:test:00000"),
            agent_loop=reasoner,
        ),
        initial_state=chain_of_thought_gsm8k_initial_state(
            task_id="gsm8k:test:00000",
            question="Janet's ducks lay 16 eggs...",
        ),
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["reasoning_path_count"] == 1
    assert "answer is 9" in result.value["completion"].lower()
    assert len(reasoner.views) == 1
    assert reasoner.views[0]["exemplar_count"] == 8
    assert reasoner.views[0]["decoding"] == "greedy"
    assert (
        reasoner.views[0]["prompt_bundle"]
        == "cot.gsm8k.neurips2022.appendix-table20"
    )


def test_chain_of_thought_study_requires_full_gsm8k_test_cut() -> None:
    records = tuple(
        GSM8KTaskRecord("test", index, "1" * 64, "2" * 64, "3" * 64)
        for index in range(1319)
    )
    benchmark = build_gsm8k_task_set(
        records,
        dataset_content_sha256="a" * 64,
    )
    study = build_chain_of_thought_gsm8k_study(benchmark)

    assert study.benchmark_split_id == "test"
    assert study.repetitions == 1
    assert study.execution_policy.trial_budget.max_model_calls == 1
    assert {
        row.measurement_id for row in study.measurement_protocol.definitions
    } == {"task_success", "model_call_count"}


def test_substitute_document_identity_is_distinct_from_immutable_model_identity() -> None:
    model = {
        "logical_name": "qwen3-8b-substitute",
        "model_id": "Qwen3-8B",
        "revision": "a" * 64,
        "engine": "vllm",
        "engine_version": "0.8.5",
        "dtype": "bfloat16",
        "quantization": None,
        "context_length": 8192,
        "tokenizer_revision": "b" * 64,
    }
    first = {
        "schema": "noetrium.external-model-identity.v2",
        "lane": "platform-substitute",
        "matched_reproduction": False,
        "deployment_id": "gpu3",
        "deployment_generation": "3" * 64,
        "deployment_observation": {"gpu_index": 3},
        "model": model,
    }
    second = {
        **first,
        "deployment_id": "gpu5",
        "deployment_generation": "5" * 64,
        "deployment_observation": {"gpu_index": 5},
    }
    assert canonical_digest(first) != canonical_digest(second)
    assert canonical_digest(_model_identity(first)) == canonical_digest(_model_identity(second))
