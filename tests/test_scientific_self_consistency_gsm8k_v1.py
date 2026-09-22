from __future__ import annotations

from noetrium_platform.composition.model_requests import (
    build_directory_model_request_recorder,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointDispatchResult,
    ModelEndpointRequest,
    ModelEndpointResponse,
    ModelEndpointPoolSnapshot,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodEvent,
    MethodEvidenceStatus,
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.providers import DirectoryEventMethodEvidence
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from research.benchmarks.gsm8k import (
    GSM8KMaterializedTask,
    GSM8KTaskRecord,
    build_gsm8k_task_set,
)
from research.reproductions.self_consistency_gsm8k import (
    SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM,
    build_self_consistency_gsm8k_study,
    extract_gsm8k_sample_answer,
    SelfConsistencyGSM8KModelBinding,
    run_self_consistency_gsm8k_episode,
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
            value=f"Reasoning path {self.calls}. The answer is {answer}.",
            events=(MethodEvent("model.invocation", {"sample_index": self.calls - 1}),),
        )


def test_self_consistency_samples_40_paths_and_marginalizes_answers(tmp_path) -> None:
    sampler = _Sampler()
    result = UniversalMethodMachine(max_steps=128).run(
        SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            ExecutionContext("sc-run", "trace", "span", task_id="gsm8k:test:00000"),
            agent_loop=sampler,
            evidence=DirectoryEventMethodEvidence(tmp_path / "evidence"),
        ),
        initial_state=self_consistency_gsm8k_initial_state(
            task_id="gsm8k:test:00000",
            question="Janet's ducks lay 16 eggs...",
        ),
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.evidence_status is MethodEvidenceStatus.COMPLETE
    assert sampler.calls == 40
    assert result.value["reasoning_path_count"] == 40
    assert result.value["selected_answer"] == "9"
    assert result.value["selected_vote_count"] == 25
    assert sum(event.kind == "self-consistency.reasoning-paths" for event in result.events) == 40
    assert sum(event.kind == "self-consistency.answer-histogram" for event in result.events) == 1


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


class _DispatchPool:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request, body):
        index = self.calls
        self.calls += 1
        physical = ModelEndpointRequest(
            request=request,
            deployment_id="test-replica",
            deployment_generation="d" * 64,
            body=body,
        )
        response = ModelEndpointResponse(
            request_id=request.request_id,
            deployment_id="test-replica",
            text=f"Reasoning path {index}. The answer is 9.",
            finish_reason="stop",
            input_tokens=10,
            output_tokens=5,
        )
        return ModelEndpointDispatchResult(
            request=physical,
            response=response,
            replica_set_digest="e" * 64,
            selection_policy_digest="f" * 64,
            selection_sequence=index + 1,
        )

    def snapshot(self):
        return ModelEndpointPoolSnapshot(
            replica_set_digest="e" * 64,
            selection_policy_digest="f" * 64,
            selection_sequence=self.calls,
            replicas=(),
        )


def test_episode_helper_executes_full_40_path_runtime_and_evidence(tmp_path) -> None:
    task = GSM8KMaterializedTask(
        GSM8KTaskRecord(
            "test", 0, "1" * 64, "2" * 64, "3" * 64
        ),
        "Janet's ducks lay 16 eggs...",
        "reasoning #### 9",
        "9",
    )
    pool = _DispatchPool()
    binding = SelfConsistencyGSM8KModelBinding(
        served_model_name="qwen",
        model=ImmutableModelIdentity(
            "test", "test/model", "a" * 64, "vllm", "0.8.5",
            "bfloat16", None, 8192, "b" * 64,
        ),
        prompt_generation_id="cot.gsm8k.neurips2022.appendix-table20",
    )
    episode = run_self_consistency_gsm8k_episode(
        task,
        endpoint_pool=pool,
        binding=binding,
        run_id="episode-helper-test",
        state_root=tmp_path / "machine",
        evidence=DirectoryEventMethodEvidence(tmp_path / "evidence"),
        recorder=build_directory_model_request_recorder(tmp_path / "model-requests"),
        runtime_binding_digest="f" * 64,
    )
    assert pool.calls == 40
    assert len(episode.invocations) == 40
    assert episode.method_result.status is MethodRunStatus.SUCCEEDED
    assert episode.method_result.evidence_status is MethodEvidenceStatus.COMPLETE
    assert episode.method_result.value["selected_answer"] == "9"
    request_files = tuple((tmp_path / "model-requests" / "requests").glob("*.json"))
    assert len(request_files) == 40
    blob_files = tuple((tmp_path / "model-requests" / "blobs").rglob("*"))
    assert any(path.is_file() for path in blob_files)
