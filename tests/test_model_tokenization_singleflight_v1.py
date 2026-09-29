from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
import time

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    JsonHttpResponse,
    ModelEndpointError,
    QualifiedModelEndpointBinding,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    ExactModelTokenizationCache,
    QualifiedEndpointTokenizationProvider,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity


def _binding() -> QualifiedModelEndpointBinding:
    model = ImmutableModelIdentity(
        "qwen3-8b",
        "Qwen/Qwen3-8B",
        "a" * 64,
        "vllm",
        "1",
        "bfloat16",
        None,
        4096,
        "tokenizer-revision",
    )
    return QualifiedModelEndpointBinding(
        role="planner",
        capability_id="generation",
        input_schema_id="model.generation.request.v1",
        output_schema_id="model.generation.response.v1",
        deployment_id="dep",
        deployment_generation="b" * 64,
        base_url="http://127.0.0.1:18080",
        model=model,
        model_stack_digest="c" * 64,
        qualification_certificate_digest="d" * 64,
        runtime_qualification_digest="e" * 64,
        host_identity_digest="f" * 64,
        prompt_generation="prompt-v1",
        max_admitted_concurrency=8,
        runtime_canary_evidence_digests=("1" * 64,),
        tokenizer_sha256="2" * 64,
        chat_template_sha256="3" * 64,
        verified_capabilities=("chat", "generation"),
    )


class _TokenizeTransport:
    def __init__(self, *, block: bool = False, fail_first: bool = False) -> None:
        self.calls = 0
        self._lock = Lock()
        self.entered = Event()
        self.release = Event()
        self._block = block
        self._fail_first = fail_first

    def post_json(self, url, body, *, timeout_s, headers=()):
        with self._lock:
            self.calls += 1
            call = self.calls
        self.entered.set()
        if self._block and not self.release.wait(5):
            raise TimeoutError("tokenization test gate did not open")
        if self._fail_first and call == 1:
            raise ModelEndpointError(
                "synthetic tokenization failure",
                failure_kind="transient",
                retryable=True,
            )
        return JsonHttpResponse(
            status_code=200,
            body={"count": 17, "max_model_len": 4096},
            raw_body=b'{"count":17,"max_model_len":4096}',
            request_body=body,
            http_version="HTTP/2",
        )

    def close(self) -> None:
        return None


def _tokenization(transport: _TokenizeTransport, cache: ExactModelTokenizationCache):
    binding = _binding()
    return QualifiedEndpointTokenizationProvider(
        binding,
        transport=transport,
        cache=cache,
    ).bind(
        model=binding.model,
        model_stack_digest=binding.model_stack_digest,
        tokenizer_sha256=binding.tokenizer_sha256 or "",
        chat_template_sha256=binding.chat_template_sha256,
    )


def _body():
    return {
        "model": "qwen3-8b",
        "messages": (
            {"role": "system", "content": "stable experiment prefix"},
            {"role": "user", "content": "question"},
        ),
        "max_tokens": 32,
    }


def test_concurrent_identical_tokenization_cache_miss_single_flights_one_wire_call():
    transport = _TokenizeTransport(block=True)
    tokenization = _tokenization(transport, ExactModelTokenizationCache(128))

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [
            executor.submit(
                tokenization.inspect,
                _body(),
                context_length=4096,
            )
            for _ in range(16)
        ]
        assert transport.entered.wait(3)
        time.sleep(0.1)
        assert transport.calls == 1
        transport.release.set()
        budgets = [future.result(timeout=3) for future in futures]

    assert transport.calls == 1
    assert all(row.input_tokens == 17 for row in budgets)
    assert all(row.requested_output_tokens == 32 for row in budgets)


def test_tokenization_failure_is_not_cached_and_retry_can_succeed():
    transport = _TokenizeTransport(fail_first=True)
    tokenization = _tokenization(transport, ExactModelTokenizationCache(128))

    try:
        tokenization.inspect(_body(), context_length=4096)
    except RuntimeError as exc:
        assert "tokenization request failed" in str(exc)
    else:
        raise AssertionError("synthetic first tokenization failure was not propagated")

    budget = tokenization.inspect(_body(), context_length=4096)
    assert budget.input_tokens == 17
    assert transport.calls == 2


def test_frozen_json_response_mapping_is_accepted_and_cached():
    transport = _TokenizeTransport()
    tokenization = _tokenization(transport, ExactModelTokenizationCache(128))

    first = tokenization.inspect(_body(), context_length=4096)
    second = tokenization.inspect(_body(), context_length=4096)

    assert first.input_tokens == second.input_tokens == 17
    assert transport.calls == 1
