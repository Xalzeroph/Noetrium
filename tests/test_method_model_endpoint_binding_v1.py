from __future__ import annotations
from noetrium_platform.composition.method_runtime import bind_standard_method_runtime

from noetrium_platform.composition.model_requests import (
    build_model_request_recorder,
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
    canonical_digest,
)
from noetrium_platform.research.execution.policy.api import ExecutionBudgetPolicy
from noetrium_platform.research.execution.policy.runtime import SQLiteExecutionBudgetAuthority
from tests._model_tokenization_support import FixedModelRequestTokenizationProvider
from noetrium_platform.research.execution.workflow.api import MethodAgentRequest
from noetrium_platform.research.execution.workflow.composition import (
    MethodModelAgentLoop,
    MethodModelAgentLoop,
    MethodModelEndpointBinding,
    MethodViewChatRequestFactory,
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
            replay_level="observational",
            trial_budget={
                "max_tokens": 4096,
                "max_turns": 10,
                "max_messages": 100,
                "max_model_calls": 10,
            },
            lifetime_id="assignment-1",
            task_id="gsm8k:test:00000",
            operation_id="method:run-1:program:reason:0",
        ),
    )


def _runtime_dependencies(tmp_path):
    tokenization = FixedModelRequestTokenizationProvider(input_tokens=9).bind(
        model=_model(),
        model_stack_digest="c" * 64,
        tokenizer_sha256="d" * 64,
        chat_template_sha256=None,
    )
    budget = SQLiteExecutionBudgetAuthority(
        tmp_path / "model-budget.sqlite",
        resource_policy_digest="e" * 64,
        checkpoint_replay_proof_digest="f" * 64,
    )
    budget.open_scope(
        ExecutionBudgetPolicy(
            scope_id="assignment-1",
            budget_id="test-budget",
            budget_digest=canonical_digest({"budget": "test"}),
            replay_level="observational",
            max_tokens=4096,
            max_turns=10,
            max_messages=100,
            max_model_calls=10,
        )
    )
    return tokenization, budget


def test_endpoint_backed_method_agent_records_request_usage_and_effect(tmp_path) -> None:
    factory = MethodViewChatRequestFactory(
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
        request_factory_digest=factory.digest,
    )
    recorder = build_model_request_recorder(tmp_path / "model-requests")
    tokenization, budget = _runtime_dependencies(tmp_path)
    loop = MethodModelAgentLoop(
        binding=binding,
        pool=_Pool(),
        recorder=recorder,
        request_factory=factory,
        tokenization=tokenization,
        execution_budget=budget,
    )

    try:
        result = loop.run(_request())
    finally:
        budget.close()

    assert result.value == "pooled answer"
    sent = loop.pool.requests[0]
    assert sent.body["model"] == "qwen"
    assert sent.body["messages"][0]["content"] == "Q: How many?\nA:"
    assert sent.body["temperature"] == 0
    envelope = recorder._ledger.get(sent.request.request_id)
    assert envelope.prompt_digest == "b" * 64
    reconstructed = recorder.reconstruct(envelope)
    assert reconstructed.compiled_prompt_text == (
        '[{"content":"Q: How many?\\nA:","role":"user"}]'
    )
    assert result.effect_receipts[0].effect_class is EffectClass.RECONCILABLE
    assert (
        result.effect_receipts[0].certainty
        is EffectCertainty.EFFECT_CONFIRMED
    )
    assert result.effect_receipts[0].provider_receipt
    assert result.events[0].kind == "model.invocation"
    assert result.events[0].payload["input_tokens"] == 9
    assert result.events[0].payload["output_tokens"] == 3


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

    def stream(self, request, body, on_event, *, stream_idle_timeout_s=30.0):
        raise AssertionError("streaming is not exercised by this test pool")

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
    factory = MethodViewChatRequestFactory(
        "qwen",
        {"temperature": 0, "max_tokens": 64},
    )
    binding = MethodModelEndpointBinding(
        agent_id="cot.reasoner",
        role="reasoner",
        model=_model(),
        request_factory_digest=factory.digest,
    )
    pool = _Pool()
    recorder = build_model_request_recorder(tmp_path / "pool-requests")
    tokenization, budget = _runtime_dependencies(tmp_path)
    loop = MethodModelAgentLoop(
        binding=binding,
        pool=pool,
        recorder=recorder,
        request_factory=factory,
        tokenization=tokenization,
        execution_budget=budget,
    )

    try:
        result = loop.run(_request())
    finally:
        budget.close()

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
    assert recorder.reconstruct(envelope).compiled_prompt_text == (
        '[{"content":"Q: How many?\\nA:","role":"user"}]'
    )
