from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

from noetrium_platform.capabilities.model.stack.api import (
    ModelArtifactClosure,
    ModelStackSpec,
    RuntimeBuildIdentity,
    parse_vllm_engine_resource_args,
)
from noetrium_platform.composition.model_runtime_bootstrap import (
    _rewrite_vllm_cudagraph_capture_sizes,
    _tuned_vllm_stack_candidate,
    qualification_source_stack_digest,
)
from noetrium_platform.composition.model_stack_materialization import (
    vllm_cudagraph_capture_sizes_for_capacity,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _stack(args: tuple[str, ...]) -> ModelStackSpec:
    return ModelStackSpec(
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


def test_cudagraph_surface_is_bounded_by_measured_capacity_and_knee() -> None:
    assert vllm_cudagraph_capture_sizes_for_capacity(
        352, preferred_concurrency=176
    ) == (1, 2, 4, 8, 16, 32, 64, 128, 176, 256, 352)
    assert vllm_cudagraph_capture_sizes_for_capacity(3) == (1, 2, 3)
    assert vllm_cudagraph_capture_sizes_for_capacity(
        1000, preferred_concurrency=700
    ) == (1, 2, 4, 8, 16, 32, 64, 128, 256, 512)


def test_tuned_stack_freezes_measured_admission_and_graph_surface() -> None:
    source = _stack((
        "--disable-uvicorn-access-log",
        "--compilation-config",
        '{"cudagraph_capture_sizes":[1,2,4,8,16,32]}',
    ))
    tuned = _tuned_vllm_stack_candidate(
        source,
        _certificate(safe=352, preferred=176),
    )
    intent = parse_vllm_engine_resource_args(tuned.engine_args)
    assert intent.max_num_seqs == 352
    index = tuned.engine_args.index("--compilation-config")
    document = json.loads(tuned.engine_args[index + 1])
    assert document["cudagraph_capture_sizes"] == [
        1, 2, 4, 8, 16, 32, 64, 128, 176, 256, 352
    ]


def test_measured_graph_surface_does_not_change_qualification_source_identity() -> None:
    source = _stack((
        "--disable-uvicorn-access-log",
        "--compilation-config",
        '{"cudagraph_capture_sizes":[1,2,4,8,16,32]}',
    ))
    tuned = _tuned_vllm_stack_candidate(
        source,
        _certificate(safe=352, preferred=176),
    )
    assert qualification_source_stack_digest(source) == qualification_source_stack_digest(tuned)


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


def test_historical_preferred_reuses_tuned_stack_by_source_identity(
    monkeypatch,
    tmp_path,
) -> None:
    from noetrium_platform.composition import model_runtime_bootstrap as bootstrap

    source = _stack((
        "--disable-uvicorn-access-log",
        "--compilation-config",
        '{"cudagraph_capture_sizes":[1,2,4,8,16,32]}',
    ))
    tuned = _tuned_vllm_stack_candidate(
        source,
        _certificate(safe=352, preferred=176),
    )
    deployment = SimpleNamespace(
        stack=tuned,
        host_identity_digest="host-a",
        certificate=_certificate(safe=352, preferred=176),
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
    ) == 176
