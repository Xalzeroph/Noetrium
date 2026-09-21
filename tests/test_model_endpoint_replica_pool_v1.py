from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
import time

import pytest

from noetrium_platform.capabilities.model.api import (
    ModelCapabilityRequirement,
    ModelProviderProfile,
)
from noetrium_platform.capabilities.model.providers.project import QualifiedModelProjectProvider
from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointResponse,
    ModelEndpointRoute,
    QualifiedModelEndpointBinding,
    QualifiedModelEndpointReplicaSet,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    AdaptiveQualifiedModelEndpointPool,
)
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    ImmutableModelIdentity,
    canonical_bytes,
    canonical_digest,
)
from tests._model_tokenization_support import FixedModelRequestTokenizationProvider


def _model() -> ImmutableModelIdentity:
    return ImmutableModelIdentity(
        "qwen3-8b",
        "Qwen3-8B",
        "a" * 64,
        "vllm",
        "0.8.5",
        "bfloat16",
        None,
        8192,
        "b" * 64,
    )


def _binding(index: int, *, capacity: int = 2) -> QualifiedModelEndpointBinding:
    return QualifiedModelEndpointBinding(
        role="reasoner",
        deployment_id=f"replica-{index}",
        deployment_generation=f"{index + 1:064x}",
        base_url=f"http://127.0.0.1:{18000 + index}",
        model=_model(),
        model_stack_digest="c" * 64,
        qualification_certificate_digest=f"{100 + index:064x}",
        runtime_qualification_digest=f"{200 + index:064x}",
        host_identity_digest="d" * 64,
        prompt_generation="prompt-v1",
        max_admitted_concurrency=capacity,
        runtime_canary_evidence_digests=(f"{300 + index:064x}",),
        tokenizer_sha256="e" * 64,
        chat_template_sha256="f" * 64,
    )


def _envelope(index: int = 0) -> ModelRequestEnvelope:
    body = canonical_bytes({"model": "qwen", "messages": [{"role": "user", "content": "x"}]})
    return ModelRequestEnvelope(
        schema_version="model-request.v1",
        request_id=f"request-{index}",
        context=ExecutionContext(f"run-{index}", f"trace-{index}", f"span-{index}"),
        role="reasoner",
        model=_model(),
        prompt_generation_id="prompt-v1",
        prompt_id="prompt",
        prompt_digest="1" * 64,
        request_body=ArtifactBlobRef(canonical_digest({"body": index}), len(body), "application/json"),
    )


class _GateEndpoint:
    def __init__(self, binding, gate: Event, entered: list[str], lock: Lock) -> None:
        self._route = ModelEndpointRoute(
            binding.deployment_id,
            binding.deployment_generation,
            binding.base_url,
        )
        self._gate = gate
        self._entered = entered
        self._lock = lock

    @property
    def route(self):
        return self._route

    def complete(self, request):
        with self._lock:
            self._entered.append(request.deployment_id)
        if not self._gate.wait(5):
            raise TimeoutError("test gate did not open")
        return ModelEndpointResponse(
            request_id=request.request.request_id,
            deployment_id=request.deployment_id,
            text="ok",
        )


class _FailingEndpoint:
    def __init__(self, binding, fail: bool) -> None:
        self._route = ModelEndpointRoute(
            binding.deployment_id,
            binding.deployment_generation,
            binding.base_url,
        )
        self._fail = fail
        self.calls = 0

    @property
    def route(self):
        return self._route

    def complete(self, request):
        self.calls += 1
        if self._fail:
            raise RuntimeError("replica failed")
        return ModelEndpointResponse(
            request_id=request.request.request_id,
            deployment_id=request.deployment_id,
            text="ok",
        )


def test_replica_set_rejects_scientific_model_drift() -> None:
    first = _binding(0)
    second = _binding(1)
    drifted = QualifiedModelEndpointBinding(
        role=second.role,
        deployment_id=second.deployment_id,
        deployment_generation=second.deployment_generation,
        base_url=second.base_url,
        model=ImmutableModelIdentity(
            "other", "Other", "a" * 64, "vllm", "0.8.5",
            "bfloat16", None, 8192, "b" * 64,
        ),
        model_stack_digest=second.model_stack_digest,
        qualification_certificate_digest=second.qualification_certificate_digest,
        runtime_qualification_digest=second.runtime_qualification_digest,
        host_identity_digest=second.host_identity_digest,
        prompt_generation=second.prompt_generation,
        max_admitted_concurrency=second.max_admitted_concurrency,
        runtime_canary_evidence_digests=second.runtime_canary_evidence_digests,
        tokenizer_sha256=second.tokenizer_sha256,
        chat_template_sha256=second.chat_template_sha256,
    )
    with pytest.raises(ValueError, match="same immutable model"):
        QualifiedModelEndpointReplicaSet((first, drifted))


def test_pool_spreads_parallel_pressure_across_all_qualified_replicas() -> None:
    bindings = tuple(_binding(index, capacity=2) for index in range(4))
    replica_set = QualifiedModelEndpointReplicaSet(bindings)
    gate = Event()
    lock = Lock()
    entered: list[str] = []
    endpoints = {}

    def factory(binding):
        endpoint = _GateEndpoint(binding, gate, entered, lock)
        endpoints[binding.deployment_id] = endpoint
        return endpoint

    pool = AdaptiveQualifiedModelEndpointPool(replica_set, factory)

    def invoke(index: int):
        return pool.complete(
            _envelope(index),
            {"model": "qwen", "messages": ({"role": "user", "content": "x"},)},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(invoke, index) for index in range(8)]
        deadline = time.monotonic() + 3
        while len(entered) < 8 and time.monotonic() < deadline:
            time.sleep(0.01)
        snapshot = pool.snapshot()
        assert [row.in_flight for row in snapshot.replicas] == [2, 2, 2, 2]
        assert [row.selections for row in snapshot.replicas] == [2, 2, 2, 2]
        gate.set()
        results = [future.result(timeout=3) for future in futures]

    assert {row.response.deployment_id for row in results} == {
        "replica-0", "replica-1", "replica-2", "replica-3"
    }
    final = pool.snapshot()
    assert [row.completed for row in final.replicas] == [2, 2, 2, 2]
    assert [row.in_flight for row in final.replicas] == [0, 0, 0, 0]


def test_pool_quarantines_failed_replica_without_replaying_uncertain_request() -> None:
    bindings = tuple(_binding(index, capacity=1) for index in range(2))
    replica_set = QualifiedModelEndpointReplicaSet(bindings)
    endpoints = {}

    def factory(binding):
        endpoint = _FailingEndpoint(binding, fail=binding.deployment_id == "replica-0")
        endpoints[binding.deployment_id] = endpoint
        return endpoint

    pool = AdaptiveQualifiedModelEndpointPool(
        replica_set,
        factory,
        failure_cooldown_seconds=60,
        max_failure_cooldown_seconds=60,
    )
    with pytest.raises(RuntimeError, match="replica failed"):
        pool.complete(_envelope(0), {"model": "qwen"})
    # The failed request was invoked exactly once and was not replayed.
    assert endpoints["replica-0"].calls == 1
    assert endpoints["replica-1"].calls == 0

    result = pool.complete(_envelope(1), {"model": "qwen"})
    assert result.response.deployment_id == "replica-1"
    snapshot = pool.snapshot()
    first, second = snapshot.replicas
    assert first.failures == 1 and first.cooling_down is True
    assert second.completed == 1


class _ReplicaBindings:
    def __init__(self, replica_set: QualifiedModelEndpointReplicaSet) -> None:
        self.replica_set = replica_set

    def binding_for(self, *, role: str, prompt_generation: str):
        assert role == self.replica_set.role
        assert prompt_generation == self.replica_set.prompt_generation
        return self.replica_set.bindings[0]

    def replica_set_for(self, *, role: str, prompt_generation: str):
        assert role == self.replica_set.role
        assert prompt_generation == self.replica_set.prompt_generation
        return self.replica_set


def test_project_provider_materializes_replica_pool_instead_of_single_endpoint() -> None:
    replica_set = QualifiedModelEndpointReplicaSet((_binding(0), _binding(1)))
    materialized: list[QualifiedModelEndpointReplicaSet] = []

    def single_endpoint_factory(binding):
        raise AssertionError(f"single endpoint fallback used for {binding.deployment_id}")

    def replica_pool_factory(value: QualifiedModelEndpointReplicaSet):
        materialized.append(value)
        return object()

    provider = QualifiedModelProjectProvider(
        ModelProviderProfile("replicated", ("chat",)),
        _ReplicaBindings(replica_set),
        single_endpoint_factory,
        object(),  # request recorder is exercised only by complete(), not bind().
        FixedModelRequestTokenizationProvider(),
        replica_pool_factory=replica_pool_factory,
    )
    requirement = ModelCapabilityRequirement(
        role="reasoner",
        prompt_generation_id="prompt-v1",
        prompt_id="prompt",
        prompt_digest="1" * 64,
        required_capabilities=("chat",),
    )

    client = provider.bind(requirement)

    assert materialized == [replica_set]
    assert client.binding.deployment_id == replica_set.bindings[0].deployment_id
    assert provider.bind(requirement) is client
