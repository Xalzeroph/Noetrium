from __future__ import annotations
from noetrium_platform.composition.method_runtime import bind_standard_method_runtime

from noetrium_platform.composition.model_requests import (
    build_directory_model_request_recorder,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointDispatchResult,
    ModelEndpointPoolSnapshot,
    ModelEndpointRequest,
    ModelEndpointResponse,
    ModelEndpointRoute,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    ExecutionContext,
    ImmutableModelIdentity,
)
from noetrium_platform.research.execution.workflow.api import MethodAgentRequest
from noetrium_platform.research.execution.workflow.composition import (
    DispatchPoolBackedMethodAgentLoop,
    EndpointBackedMethodAgentLoop,
    MethodModelEndpointBinding,
    PromptViewChatRequestFactory,
)


class _Endpoint:
    def __init__(self) -> None:
        self.route = ModelEndpointRoute(
            "external-qwen",
            "a" * 64,
            "http://127.0.0.1:8001",
        )
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return ModelEndpointResponse(
            request_id=request.request.request_id,
            deployment_id=request.deployment_id,
            text="The answer is 18.",
            finish_reason="stop",
            input_tokens=100,
            output_tokens=8,
            usage={"prompt_tokens": 100, "completion_tokens": 8},
        )


def _model() -> ImmutableModelIdentity:
    return ImmutableModelIdentity(
        logical_name="reasoner",
        model_id="Qwen/Qwen3-8B",
        revision="checkpoint-digest",
        engine="vllm",
        engine_version="0.8.5",
        dtype="bfloat16",
        quantization=None,
        context_length=8192,
        tokenizer_revision="checkpoint-digest",
    )


def _request() -> MethodAgentRequest:
    return MethodAgentRequest(
        agent_id="cot.reasoner",
        goal=None,
        view={
            "prompt": "Q: How many?\nA:",
            "prompt_digest": "b" * 64,
        },
        input_value=None,
        previous_value=None,
        context=ExecutionContext(
            "run-1",
            "trace-1",
            "span-1",
            task_id="gsm8k:test:00000",
            operation_id="method:run-1:program:reason:0",
        ),
    )


def test_endpoint_backed_method_agent_records_request_usage_and_effect(tmp_path) -> None:
    factory = PromptViewChatRequestFactory(
        "qwen",
        {
            "temperature": 0,
            "max_tokens": 512,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    binding = MethodModelEndpointBinding(
        agent_id="cot.reasoner",
        role="reasoner",
        model=_model(),
        prompt_generation_id="cot.gsm8k.neurips2022.appendix-table20",
        prompt_id="cot.gsm8k.neurips2022.appendix-table20",
        prompt_digest="b" * 64,
        request_factory_digest=factory.digest,
    )
    endpoint = _Endpoint()
    recorder = build_directory_model_request_recorder(tmp_path / "model-requests")
    loop = EndpointBackedMethodAgentLoop(
        binding=binding,
        endpoint=endpoint,
        recorder=recorder,
        request_factory=factory,
    )

    result = loop.run(_request())

    assert result.value == "The answer is 18."
    assert len(endpoint.requests) == 1
    sent = endpoint.requests[0]
    assert sent.body["model"] == "qwen"
    assert sent.body["messages"][0]["content"] == "Q: How many?\nA:"
    assert sent.body["temperature"] == 0
    envelope = recorder._ledger.get(sent.request.request_id)
    assert envelope.prompt_digest == "b" * 64
    reconstructed = recorder.reconstruct(envelope)
    assert reconstructed.compiled_prompt_text == "Q: How many?\nA:"
    assert result.effect_receipts[0].effect_class is EffectClass.RECONCILABLE
    assert (
        result.effect_receipts[0].certainty
        is EffectCertainty.EFFECT_CONFIRMED
    )
    assert result.effect_receipts[0].provider_receipt
    assert result.events[0].kind == "model.invocation"
    assert result.events[0].payload["input_tokens"] == 100
    assert result.events[0].payload["output_tokens"] == 8


def test_endpoint_agent_closes_machine_journal_and_method_evidence(tmp_path) -> None:
    from noetrium_platform.research.execution.workflow.api import (
        MethodEvidenceStatus,
        MethodRuntimeContext,
    )
    from noetrium_platform.composition.method_runtime import (
        bind_standard_method_runtime,
    )
    from noetrium_platform.research.execution.workflow.providers import (
        DirectoryEventMethodEvidence,
    )
    from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
    from research.reproductions.chain_of_thought_gsm8k import (
        CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM,
        COT_GSM8K_PROMPT_BUNDLE_ID,
        COT_GSM8K_PROMPT_DIGEST,
        chain_of_thought_gsm8k_initial_state,
    )

    factory = PromptViewChatRequestFactory(
        "qwen",
        {"temperature": 0, "max_tokens": 512},
    )
    binding = MethodModelEndpointBinding(
        agent_id="cot.reasoner",
        role="reasoner",
        model=_model(),
        prompt_generation_id=COT_GSM8K_PROMPT_BUNDLE_ID,
        prompt_id=COT_GSM8K_PROMPT_BUNDLE_ID,
        prompt_digest=COT_GSM8K_PROMPT_DIGEST,
        request_factory_digest=factory.digest,
    )
    loop = EndpointBackedMethodAgentLoop(
        binding=binding,
        endpoint=_Endpoint(),
        recorder=build_directory_model_request_recorder(tmp_path / "requests"),
        request_factory=factory,
    )
    runtime = MethodRuntimeContext(
        ExecutionContext(
            "cot-real-shape-run",
            "trace",
            "root",
            task_id="gsm8k:test:00000",
        ),
        agent_loop=loop,
        evidence=DirectoryEventMethodEvidence(tmp_path / "evidence"),
        binding_plan_digest=binding.digest,
    )
    runtime = bind_standard_method_runtime(
        CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM,
        runtime,
        state_root=tmp_path / "machine",
    )

    result = UniversalMethodMachine(max_steps=8).run(
        CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM,
        runtime=runtime,
        initial_state=chain_of_thought_gsm8k_initial_state(
            task_id="gsm8k:test:00000",
            question="How much does Janet make?",
        ),
    )

    assert result.evidence_status is MethodEvidenceStatus.COMPLETE
    assert len(result.effect_receipts) == 1
    assert {event.kind for event in result.events} >= {
        "model.invocation",
        "cot.reasoning-completion",
    }
    assert any(path.is_file() for path in (tmp_path / "machine" / "journal").rglob("*"))
    assert list((tmp_path / "evidence" / "results").glob("*.json"))


class _Pool:
    def __init__(self) -> None:
        self.requests = []
        self.replica_set_digest = "d" * 64

    def snapshot(self):
        return ModelEndpointPoolSnapshot(
            replica_set_digest=self.replica_set_digest,
            selection_policy_digest="f" * 64,
            selection_sequence=len(self.requests),
            replicas=(),
        )

    def complete(self, request, body):
        physical = ModelEndpointRequest(
            request=request,
            deployment_id="pool-qwen-a",
            deployment_generation="e" * 64,
            body=body,
        )
        self.requests.append(physical)
        response = ModelEndpointResponse(
            request_id=request.request_id,
            deployment_id="pool-qwen-a",
            text="pooled answer",
            finish_reason="stop",
            input_tokens=9,
            output_tokens=3,
            usage={"prompt_tokens": 9, "completion_tokens": 3},
        )
        return ModelEndpointDispatchResult(
            request=physical,
            response=response,
            replica_set_digest=self.replica_set_digest,
            selection_policy_digest="f" * 64,
            selection_sequence=len(self.requests),
        )


def test_dispatch_pool_backed_method_agent_records_selected_replica(tmp_path) -> None:
    factory = PromptViewChatRequestFactory(
        "qwen",
        {"temperature": 0, "max_tokens": 64},
    )
    binding = MethodModelEndpointBinding(
        agent_id="cot.reasoner",
        role="reasoner",
        model=_model(),
        prompt_generation_id="pooled-pressure-v1",
        prompt_id="pooled-pressure",
        prompt_digest="c" * 64,
        request_factory_digest=factory.digest,
    )
    pool = _Pool()
    recorder = build_directory_model_request_recorder(tmp_path / "pool-requests")
    loop = DispatchPoolBackedMethodAgentLoop(
        binding=binding,
        pool=pool,
        recorder=recorder,
        request_factory=factory,
    )

    result = loop.run(_request())

    assert result.value == "pooled answer"
    assert len(pool.requests) == 1
    assert result.effect_receipts[0].provider_instance_id == "pool-qwen-a"
    event = result.events[0]
    assert event.kind == "model.invocation"
    assert event.payload["deployment_id"] == "pool-qwen-a"
    assert event.payload["deployment_generation"] == "e" * 64
    assert event.payload["replica_set_digest"] == "d" * 64
    assert event.payload["selection_policy_digest"] == "f" * 64
    assert event.payload["selection_sequence"] == 1
    assert len(loop.identity_digest) == 64
    envelope = recorder._ledger.get(pool.requests[0].request.request_id)
    assert recorder.reconstruct(envelope).compiled_prompt_text == "Q: How many?\nA:"
