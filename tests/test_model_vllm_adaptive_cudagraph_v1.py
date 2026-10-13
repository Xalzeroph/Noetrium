from __future__ import annotations

import hashlib
from dataclasses import replace
import json
from types import SimpleNamespace

from noetrium_platform.capabilities.model.stack.api import (
    ModelArtifactClosure,
    FrozenModelStack,
    RuntimeBuildIdentity,
    parse_vllm_engine_resource_args,
)
import noetrium_platform.composition.model_runtime_bootstrap as model_bootstrap
from noetrium_platform.composition.model_runtime_bootstrap import (
    _rewrite_vllm_cudagraph_capture_sizes,
    _positive_engine_integer_option,
    _warm_materialized_stack_candidate,
    _warm_stack_concurrency_hint,
    qualification_source_stack_digest,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity
from noetrium_platform.capabilities.model.deployment.api import (
    ModelDesiredDeployment,
    ModelDesiredState,
    ModelRuntimeState,
)
from noetrium_platform.capabilities.model.deployment.composition import (
    ModelReplicaPoolRequest,
)
from noetrium_platform.composition.model_stack_materialization import (
    MaterializedModelStack,
    ModelPlacementObservation,
)
from noetrium_platform.substrate.api import (
    ComputeRequirement,
    GpuDeviceStatus,
    GpuRuntimeSnapshot,
    PLATFORM_SCOPE,
)
from noetrium_platform.foundation.kernel.truth import TruthModality
from noetrium_platform.infrastructure.resources.authority import (
    AuthoritySnapshot,
    resource_claim,
)
from noetrium_platform.capabilities.model.serving.api import (
    PerformanceSample,
    QualificationEvidence,
    QualificationPolicy,
    ResourceQualificationMeasurements,
    RoleCanaryResult,
)
from noetrium_platform.capabilities.model.serving.composition import (
    issue_measured_qualification_certificate,
)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _stack(args: tuple[str, ...]) -> FrozenModelStack:
    return FrozenModelStack(
        ImmutableModelIdentity(
            "qwen", "qwen3-8b", "revision", "vllm", "0.8.5",
            "bfloat16", None, 40960,
        ),
        ModelArtifactClosure(_h("weights"), _h("tokenizer"), _h("config")),
        RuntimeBuildIdentity(
            _h("container"), _h("engine"), _h("lock"),
            "cuda", "nccl", "torch", _h("kernels"),
        ),
        1, 1, 1, 1, None, None, None, None, "default", args,
    )


def _certificate(*, safe: int, preferred: int):
    return SimpleNamespace(
        resource_envelope=SimpleNamespace(
            max_qualified_concurrency=safe,
            preferred_operating_concurrency=preferred,
        )
    )


def test_qualification_source_identity_ignores_engine_admission_ceiling() -> None:
    source = _stack((
        "--disable-uvicorn-access-log",
        "--compilation-config",
        '{"cudagraph_capture_sizes":[1,2,4,8,16,32]}',
        "--max-num-seqs",
        "112",
    ))
    changed_ceiling = replace(
        source,
        engine_args=(
            "--disable-uvicorn-access-log",
            "--compilation-config",
            '{"cudagraph_capture_sizes":[1,2,4,8,16,32]}',
            "--max-num-seqs",
            "32",
        ),
    )
    assert (
        qualification_source_stack_digest(source)
        == qualification_source_stack_digest(changed_ceiling)
    )
    assert _warm_stack_concurrency_hint(source) == 112


def test_capture_rewrite_preserves_other_compilation_semantics() -> None:
    args = (
        "--compilation-config",
        '{"cudagraph_capture_sizes":[1,2,4],"level":3}',
    )
    stripped = _rewrite_vllm_cudagraph_capture_sizes(args, None)
    assert stripped == ("--compilation-config", '{"level":3}')
    rewritten = _rewrite_vllm_cudagraph_capture_sizes(stripped, (1, 2, 8))
    assert json.loads(rewritten[1]) == {
        "cudagraph_capture_sizes": [1, 2, 8],
        "level": 3,
    }


def test_historical_preferred_reuses_physical_stack_source_identity(
    monkeypatch,
    tmp_path,
) -> None:
    from noetrium_platform.composition import model_runtime_bootstrap as bootstrap

    source = _stack((
        "--disable-uvicorn-access-log",
        "--compilation-config",
        '{"cudagraph_capture_sizes":[1,2,4,8,16,32]}',
        "--max-num-seqs",
        "112",
    ))
    deployment = SimpleNamespace(
        stack=source,
        host_identity_digest="host-a",
        certificate=_certificate(safe=32, preferred=16),
    )
    monkeypatch.setattr(
        bootstrap,
        "load_qualified_model_deployment_closure",
        lambda *_args, **_kwargs: SimpleNamespace(deployments=(deployment,)),
    )
    path = tmp_path / "qualified-model-closure.json"
    path.write_text("{}", encoding="utf-8")
    assert bootstrap._historical_preferred_concurrency(
        path,
        qualification_source_digest=qualification_source_stack_digest(source),
        host_identity_digest="host-a",
    ) == 16


def test_positive_engine_integer_option_recovers_applied_warm_context() -> None:
    assert _positive_engine_integer_option(
        (
            "vllm",
            "serve",
            "/model",
            "--max-model-len",
            "39145",
            "--max-num-seqs=352",
        ),
        name="--max-model-len",
    ) == 39145
    assert _positive_engine_integer_option(
        ("--max-model-len=40960",),
        name="--max-model-len",
    ) == 40960
    assert _positive_engine_integer_option(
        ("--max-num-seqs", "352"),
        name="--max-model-len",
    ) is None


def test_stronger_warm_context_dominates_weaker_new_requirement(tmp_path) -> None:
    source = _stack((
        "--disable-uvicorn-access-log",
        "--compilation-config",
        '{"cudagraph_capture_sizes":[1,2,4,8,16,32]}',
    ))
    source = replace(
        source,
        identity=replace(source.identity, context_length=39145),
    )
    tuned = replace(
        source,
        engine_args=(*source.engine_args, "--max-num-seqs", "352"),
    )
    compute = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=1024,
        gpu_count=1,
        minimum_gpu_memory_bytes=1,
    )
    base = MaterializedModelStack(
        stack=source,
        compute=compute,
        image_source="image",
        fingerprint_ref="fingerprint",
    )
    probe = ModelReplicaPoolRequest(
        pool_id="warm-probe",
        scope=PLATFORM_SCOPE,
        model_id="qwen3-8b",
        engine="vllm",
        cwd=tmp_path / "runtime",
        compute=compute,
        model_stack=tuned,
        replica_count=1,
        endpoint_host="127.0.0.1",
    )

    class Materializer:
        contexts: list[int | None] = []

        def materialize_for_tensor_parallel(
            self,
            model_id,
            tensor_parallel,
            *,
            context_length=None,
        ):
            assert model_id == "qwen3-8b"
            assert tensor_parallel == 1
            self.contexts.append(context_length)
            assert context_length == 39145
            return base

    spec = SimpleNamespace(
        deployment_id="warm-deployment",
        model_id="qwen3-8b",
        desired_state=ModelDesiredState.RUNNING,
        gpu_devices=("GPU-a",),
        container_digest=source.runtime.container_digest,
        argv=(
            "vllm",
            "serve",
            "/model",
            "--max-model-len",
            "39145",
            "--max-num-seqs",
            "352",
        ),
        tags=(
            f"model-stack:{tuned.digest()}",
            f"runtime-identity:{probe.runtime_identity_digest}",
            "resource-key:service:warm",
        ),
    )
    resources = SimpleNamespace(
        snapshot=lambda: SimpleNamespace(
            deployments=(
                SimpleNamespace(
                    deployment_id="warm-deployment",
                    runtime_state=ModelRuntimeState.RUNNING,
                ),
            ),
            deployment_specs=(spec,),
        )
    )
    materializer = Materializer()

    candidate, rejected = _warm_materialized_stack_candidate(
        model_id="qwen3-8b",
        materializer=materializer,
        model_resources=resources,
        deployment_runtime=object(),
        runtime_workdir=tmp_path / "runtime",
        minimum_context_tokens=12041,
    )

    assert rejected is None
    assert candidate is not None
    assert candidate.stack.digest() == tuned.digest()
    assert candidate.stack.identity.context_length == 39145
    assert materializer.contexts == [39145]


def test_warm_candidate_prefers_lower_external_gpu_pressure(
    tmp_path,
    monkeypatch,
) -> None:
    compute = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=1024,
        gpu_count=1,
        minimum_gpu_memory_bytes=1,
    )
    sources = {}
    tuned = {}
    bases = {}
    probes = {}
    for context in (12041, 39145):
        source = replace(
            _stack(("--disable-uvicorn-access-log",)),
            identity=replace(_stack(()).identity, context_length=context),
        )
        candidate = replace(
            source,
            engine_args=(*source.engine_args, "--max-num-seqs", "352"),
        )
        sources[context] = source
        tuned[context] = candidate
        bases[context] = MaterializedModelStack(
            stack=source,
            compute=compute,
            image_source="image",
            fingerprint_ref=f"fingerprint-{context}",
        )
        probes[context] = ModelReplicaPoolRequest(
            pool_id=f"probe-{context}",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            cwd=tmp_path / "runtime",
            compute=compute,
            model_stack=candidate,
            replica_count=1,
            endpoint_host="127.0.0.1",
        )

    def spec(context: int, deployment_id: str, gpu_id: str, service_key: str):
        return ModelDesiredDeployment(
            deployment_id=deployment_id,
            scope=PLATFORM_SCOPE,
            service_id="model:" + deployment_id,
            model_id="qwen3-8b",
            engine="vllm",
            container_digest=sources[context].runtime.container_digest,
            executable="/usr/local/bin/vllm",
            argv=(
                "/usr/local/bin/vllm",
                "serve",
                "/model",
                "--max-model-len",
                str(context),
                "--max-num-seqs",
                "352",
            ),
            cwd=tmp_path,
            gpu_devices=(gpu_id,),
            gpu_memory_reservation_bytes=(20 * 1024**3,),
            desired_state=ModelDesiredState.RUNNING,
            tags=(
                f"model-stack:{tuned[context].digest()}",
                f"runtime-identity:{probes[context].runtime_identity_digest}",
                f"resource-key:{service_key}",
            ),
        )

    short = spec(12041, "warm-short", "GPU-a", "service:short")
    long = spec(39145, "warm-long", "GPU-b", "service:long")
    claims = (
        resource_claim(
            "compute-short",
            "compute:short",
            "holder",
            1,
            owner_scope=PLATFORM_SCOPE,
            scope_generation=1,
            scope_lease_id=None,
            owner_lease_id=None,
            attributes={
                "kind": "compute",
                "consumer_resource_key": "service:short",
            },
            modality=TruthModality.AUTHORIZED,
        ),
        resource_claim(
            "compute-long",
            "compute:long",
            "holder",
            1,
            owner_scope=PLATFORM_SCOPE,
            scope_generation=1,
            scope_lease_id=None,
            owner_lease_id=None,
            attributes={
                "kind": "compute",
                "consumer_resource_key": "service:long",
            },
            modality=TruthModality.AUTHORIZED,
        ),
    )
    observation = ModelPlacementObservation(
        AuthoritySnapshot((), claims, (), (), ()),
        GpuRuntimeSnapshot(
            True,
            devices=(
                GpuDeviceStatus(
                    "0", "GPU-a", "RTX", 49140, 35000, 14140, 0
                ),
                GpuDeviceStatus(
                    "1", "GPU-b", "RTX", 49140, 25000, 24140, 0
                ),
            ),
        ),
        None,
    )

    class Materializer:
        observation_calls = 0

        def materialize_for_tensor_parallel(
            self,
            model_id,
            tensor_parallel,
            *,
            context_length=None,
        ):
            assert model_id == "qwen3-8b"
            assert tensor_parallel == 1
            return bases[context_length]

        def placement_observation(self):
            self.observation_calls += 1
            return observation

    resources = SimpleNamespace(
        snapshot=lambda: SimpleNamespace(
            deployments=(
                SimpleNamespace(
                    deployment_id="warm-short",
                    runtime_state=ModelRuntimeState.RUNNING,
                ),
                SimpleNamespace(
                    deployment_id="warm-long",
                    runtime_state=ModelRuntimeState.RUNNING,
                ),
            ),
            deployment_specs=(short, long),
        )
    )

    import noetrium_platform.composition.model_runtime_bootstrap as bootstrap

    def forbidden_candidate_projection(*_args, **_kwargs):
        raise AssertionError(
            "TP=1 warm pressure scoring must use the shared pressure index"
        )

    monkeypatch.setattr(
        bootstrap,
        "_placement_observation_without_warm_deployment",
        forbidden_candidate_projection,
    )
    materializer = Materializer()
    candidate, rejected = _warm_materialized_stack_candidate(
        model_id="qwen3-8b",
        materializer=materializer,
        model_resources=resources,
        deployment_runtime=object(),
        runtime_workdir=tmp_path / "runtime",
        minimum_context_tokens=8000,
    )
    assert rejected is None
    assert candidate is not None
    assert candidate.stack.identity.context_length == 39145
    assert materializer.observation_calls == 1


def test_static_qualification_probe_volume_is_fixed_budget(monkeypatch) -> None:
    calls: list[int] = []

    def fake_probe(**kwargs):
        concurrency = int(kwargs["concurrency"])
        calls.append(concurrency)
        if concurrency > 16:
            return None, ()
        return (
            PerformanceSample(
                concurrency=concurrency,
                ttft_p50=0.01,
                ttft_p99=0.02,
                tpot_p50=0.01,
                tpot_p99=0.02,
                output_tokens_per_second=float(concurrency),
                error_rate=0.0,
            ),
            (),
        )

    monkeypatch.setattr(model_bootstrap, "_run_concurrency_probe", fake_probe)
    monkeypatch.setattr(model_bootstrap, "_gpu_memory_bytes", lambda *_args: 1)
    monkeypatch.setattr(model_bootstrap, "_container_memory_bytes", lambda *_args: 1)

    samples, qualified, peak_gpu, peak_host = (
        model_bootstrap._measure_static_concurrency_capacity(
            probe_namespace="fixed-budget",
            probe_payload=b"{}",
            completion_url="http://unused",
            http_transport=object(),
            task_group=object(),
            max_concurrency=64,
            preferred_concurrency_hint=8,
            resources=object(),
            gpu_ids=("GPU-0",),
            command_runner=object(),
            container_id="container",
        )
    )

    assert qualified == 16
    assert tuple(row.concurrency for row in samples) == (1, 4, 8, 16)
    assert calls == [1, 4, 8, 16, 32]
    assert sum(calls) <= model_bootstrap._STATIC_QUALIFICATION_REQUEST_BUDGET
    assert peak_gpu == 1
    assert peak_host == 1


def test_static_qualification_cold_scout_is_constant_bounded() -> None:
    scout = model_bootstrap._static_qualification_scout_concurrencies(
        max_concurrency=1_000_000,
        preferred_concurrency_hint=None,
    )
    assert scout == (1, 2, 4, 8, 16, 32)
    assert sum(scout) == model_bootstrap._STATIC_QUALIFICATION_REQUEST_BUDGET
    assert max(scout) == 32


def test_qualification_request_ceiling_is_kv_bounded(
    monkeypatch,
    tmp_path,
) -> None:
    per_token = 256
    token_window = 40960
    monkeypatch.setattr(
        model_bootstrap,
        "model_kv_cache_bytes_per_token",
        lambda *_args, **_kwargs: per_token,
    )
    monkeypatch.setattr(
        model_bootstrap,
        "model_kv_cache_budget_bytes",
        lambda *_args, **_kwargs: per_token * token_window,
    )

    class Identity:
        dtype = "bfloat16"
        context_length = token_window

    class Stack:
        identity = Identity()
        tensor_parallel = 1

    assert model_bootstrap._estimated_qualification_concurrency_ceiling(
        asset_path=tmp_path,
        stack=Stack(),
        transport_ceiling=524288,
        observed_prompt_tokens=512,
        output_token_budget=32,
    ) == token_window // (512 + 32)


def test_qualified_prefill_window_is_authority_kv_bound(
    monkeypatch,
    tmp_path,
) -> None:
    per_token = 256
    token_window = 40960
    monkeypatch.setattr(
        model_bootstrap,
        "model_kv_cache_bytes_per_token",
        lambda *_args, **_kwargs: per_token,
    )
    monkeypatch.setattr(
        model_bootstrap,
        "model_kv_cache_budget_bytes",
        lambda *_args, **_kwargs: per_token * token_window,
    )

    assert model_bootstrap._qualified_kv_token_window(
        asset_path=tmp_path,
        stack=_stack(()),
    ) == token_window
