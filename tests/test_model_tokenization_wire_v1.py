from __future__ import annotations

from model_admission_test_support import make_model_admission_controller

import json

from noetrium_platform.capabilities.model.api import ModelRequestTokenizationIdentity
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    JsonHttpResponse,
    QualifiedModelEndpointBinding,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers.tokenization import (
    OpenAICompatibleQualifiedTokenization,
)
from noetrium_platform.capabilities.model.serving.runtime.admission import ModelAdmissionController
from noetrium_platform.foundation.kernel.kernel import (
    ImmutableModelIdentity,
    freeze_json,
)


class _Transport:
    def __init__(self) -> None:
        self.seen = {}
        self.closed = False

    def post_json(self, url, body, *, timeout_s, headers=()):
        self.seen["url"] = url
        self.seen["timeout"] = timeout_s
        self.seen["body"] = json.loads(body.decode("utf-8"))
        self.seen["headers"] = headers
        return JsonHttpResponse(
            200,
            {"count": 17, "max_model_len": 8192, "tokens": list(range(17))},
            request_body=body,
        )

    def close(self) -> None:
        self.closed = True


def _model() -> ImmutableModelIdentity:
    return ImmutableModelIdentity(
        logical_name="Qwen3-8B",
        model_id="Qwen3-8B",
        revision="r" * 64,
        engine="vllm",
        engine_version="0.28.0",
        dtype="bfloat16",
        quantization=None,
        context_length=8192,
        tokenizer_revision="tok-rev",
    )


def _binding(model: ImmutableModelIdentity) -> QualifiedModelEndpointBinding:
    return QualifiedModelEndpointBinding(
        role="planner",
        capability_id="generation",
        input_schema_id="model.generation.request.v1",
        output_schema_id="model.generation.response.v1",
        deployment_id="deployment-1",
        deployment_generation="a" * 64,
        base_url="http://127.0.0.1:18081",
        model=model,
        model_stack_digest="b" * 64,
        qualification_certificate_digest="c" * 64,
        runtime_qualification_digest="d" * 64,
        host_identity_digest="e" * 64,
        prompt_generation="prompt-v1",
        max_admitted_concurrency=4,
        latency_isolation_concurrency=1,
        preemptive_latency_isolation=False,
        preemptive_return_ttft_p99_seconds=None,
        preemptive_return_tpot_p99_seconds=None,
        max_prefill_queued_tokens=4096,
        prefill_input_tokens_per_second=1_000_000_000.0,
        minimum_output_tokens_per_second=1_000_000_000.0,
        runtime_canary_evidence_digests=("f" * 64,),
        tokenizer_sha256="1" * 64,
        chat_template_sha256="2" * 64,
        verified_capabilities=("structured_output",),
    )


def test_qualified_tokenization_materializes_deeply_frozen_json_before_wire() -> None:
    model = _model()
    binding = _binding(model)
    identity = ModelRequestTokenizationIdentity(
        model=model,
        model_stack_digest=binding.model_stack_digest,
        tokenizer_sha256=binding.tokenizer_sha256,
        chat_template_sha256=binding.chat_template_sha256,
        implementation_digest="3" * 64,
        request_protocol="vllm.openai.tokenize.v1",
    )
    transport = _Transport()

    tokenization = OpenAICompatibleQualifiedTokenization(
        binding,
        identity,
        transport,
        make_model_admission_controller(binding.max_admitted_concurrency),
    )
    frozen = freeze_json(
        {
            "model": "Qwen3-8B",
            "messages": [
                {
                    "role": "system",
                    "content": "Return JSON.",
                    "metadata": {"nested": {"proof": True}},
                },
                {
                    "role": "user",
                    "content": "hello",
                },
            ],
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_object",
                "schema": {"type": "object"},
            },
            "max_tokens": 32,
        }
    )

    budget = tokenization.inspect(frozen, context_length=8192)

    assert budget.input_tokens == 17
    assert budget.requested_output_tokens == 32
    assert transport.seen["timeout"] == 8192 / 1_000_000_000.0
    assert budget.input_token_ids == tuple(range(17))
    assert transport.seen["body"] == {
        "add_generation_prompt": True,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {
                "content": "Return JSON.",
                "metadata": {"nested": {"proof": True}},
                "role": "system",
            },
            {"content": "hello", "role": "user"},
        ],
        "model": "Qwen3-8B",
    }
