from __future__ import annotations

from model_admission_test_support import make_model_admission_controller

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
from noetrium_platform.capabilities.model.serving.runtime.admission import ModelAdmissionController
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
        latency_isolation_concurrency=1,
        preemptive_latency_isolation=False,
        preemptive_return_ttft_p99_seconds=None,
        preemptive_return_tpot_p99_seconds=None,
        max_prefill_queued_tokens=4096,
        prefill_input_tokens_per_second=1_000_000_000.0,
        minimum_output_tokens_per_second=1_000_000_000.0,
        runtime_canary_evidence_digests=("1" * 64,),
        tokenizer_sha256="2" * 64,
        chat_template_sha256="3" * 64,
        verified_capabilities=("chat", "generation"),
    )


class _TokenizeTransport:
    def __init__(self, *, block: bool = False, fail_first: bool = False) -> None:
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self._lock = Lock()
        self.entered = Event()
        self.release = Event()
        self._block = block
        self._fail_first = fail_first
        self.timeouts = []

    def post_json(self, url, body, *, timeout_s, headers=()):
        with self._lock:
            self.calls += 1
            self.timeouts.append(timeout_s)
            call = self.calls
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.entered.set()
        try:
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
                body={"count": 17, "max_model_len": 4096, "tokens": list(range(17))},
                raw_body=b'{"count":17,"max_model_len":4096,"tokens":[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16]}',
                request_body=body,
                http_version="HTTP/2",
            )
        finally:
            with self._lock:
                self.active -= 1

    def close(self) -> None:
        return None


def _tokenization(transport: _TokenizeTransport, cache: ExactModelTokenizationCache):
    binding = _binding()
    return QualifiedEndpointTokenizationProvider(
        binding,
        transport=transport,
        admission=make_model_admission_controller(binding.max_admitted_concurrency),
        cache=cache,
    ).bind(
        model=binding.model,
        model_stack_digest=binding.model_stack_digest,
        tokenizer_sha256=binding.tokenizer_sha256 or "",
        chat_template_sha256=binding.chat_template_sha256,
    )


def _tokenization_with_admission(
    transport: _TokenizeTransport,
    cache: ExactModelTokenizationCache,
    admission: ModelAdmissionController,
):
    binding = _binding()
    return QualifiedEndpointTokenizationProvider(
        binding,
        transport=transport,
        admission=admission,
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


def test_tokenization_cache_miss_uses_qualification_derived_physical_timeout():
    transport = _TokenizeTransport()
    tokenization = _tokenization(transport, ExactModelTokenizationCache(128))

    tokenization.inspect(_body(), context_length=4096)

    assert transport.timeouts == [4096 / 1_000_000_000.0]
    assert transport.timeouts[0] > 0.0


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
    assert all(row.input_token_ids == tuple(range(17)) for row in budgets)


def test_unique_tokenization_cache_misses_share_qualified_admission_capacity():
    transport = _TokenizeTransport(block=True)
    admission = make_model_admission_controller(8)
    tokenization = _tokenization_with_admission(
        transport,
        ExactModelTokenizationCache(128),
        admission,
    )

    def body(index: int):
        return {
            "model": "qwen3-8b",
            "messages": (
                {"role": "system", "content": "stable experiment prefix"},
                {"role": "user", "content": f"question-{index}"},
            ),
            "max_tokens": 32,
        }

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [
            executor.submit(tokenization.inspect, body(index), context_length=4096)
            for index in range(16)
        ]
        assert transport.entered.wait(3)
        deadline = time.monotonic() + 3
        while transport.calls < 8 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert transport.calls == 8
        assert transport.max_active == 8
        transport.release.set()
        budgets = [future.result(timeout=3) for future in futures]

    assert transport.calls == 16
    assert transport.max_active == 8
    assert all(row.input_tokens == 17 for row in budgets)


def test_transient_tokenization_disconnect_retries_within_one_cache_miss():
    transport = _TokenizeTransport(fail_first=True)
    tokenization = _tokenization(transport, ExactModelTokenizationCache(128))

    budget = tokenization.inspect(_body(), context_length=4096)
    assert budget.input_tokens == 17
    assert transport.calls == 2
    reused = tokenization.inspect(_body(), context_length=4096)
    assert reused.input_token_ids is budget.input_token_ids
    assert transport.calls == 2


def test_tokenization_fails_closed_after_bounded_transient_retries():
    class UnavailableTokenizeTransport(_TokenizeTransport):
        def post_json(self, url, body, *, timeout_s, headers=()):
            self.calls += 1
            raise ModelEndpointError(
                "synthetic repeated disconnect",
                failure_kind="transient",
                retryable=True,
                affects_replica_health=True,
            )

    transport = UnavailableTokenizeTransport()
    tokenization = _tokenization(transport, ExactModelTokenizationCache(128))
    try:
        tokenization.inspect(_body(), context_length=4096)
    except ModelEndpointError as exc:
        assert exc.failure_kind == "transient"
        assert exc.retryable is True
    else:
        raise AssertionError("unavailable tokenization endpoint was accepted")
    assert transport.calls == 3


def test_frozen_json_response_mapping_is_accepted_and_cached():
    transport = _TokenizeTransport()
    tokenization = _tokenization(transport, ExactModelTokenizationCache(128))

    first = tokenization.inspect(_body(), context_length=4096)
    second = tokenization.inspect(_body(), context_length=4096)

    assert first.input_tokens == second.input_tokens == 17
    assert transport.calls == 1


def test_cached_tokenization_reuses_proven_input_when_output_reservation_changes():
    transport = _TokenizeTransport()
    tokenization = _tokenization(transport, ExactModelTokenizationCache(128))
    first_body = _body()
    second_body = dict(first_body)
    second_body["max_tokens"] = 64

    first = tokenization.inspect(first_body, context_length=4096)
    second = tokenization.inspect(second_body, context_length=4096)

    assert transport.calls == 1
    assert first.input_tokens == second.input_tokens == 17
    assert first.input_token_ids is second.input_token_ids
    assert first.requested_output_tokens == 32
    assert second.requested_output_tokens == 64
