from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from noetrium_platform.composition import model_runtime_refresh
from noetrium_platform.composition.model_runtime_bootstrap import (
    GPU_MEMORY_ACCOUNTING_EVIDENCE_REF,
    RequiredModelRuntime,
    STATIC_QUALIFICATION_PROTOCOL_EVIDENCE_REF,
)
from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputePlacementUnavailable,
    ComputeRequirement,
    GpuSharingMode,
)


class _ReceiptStore:
    def __init__(self, *refs: str) -> None:
        self.refs = tuple(refs)

    def load(self, runtime_manifest_digest: str, deployment_id: str):
        return SimpleNamespace(evidence_refs=self.refs)


def _source():
    stack = SimpleNamespace(
        identity=SimpleNamespace(model_id="qwen3-8b", engine="vllm", context_length=39145),
        tensor_parallel=2,
        pipeline_parallel=1,
        engine_args=(),
        digest=lambda: "a" * 64,
    )
    return SimpleNamespace(
        deployment_id="deployment-old",
        stack=stack,
        certificate=SimpleNamespace(target_host_identity_digest="host-a"),
    )


class _NoopPool:
    def reclaim_dominated_warm_realizations(self):
        return ()


def _refresh_kwargs(tmp_path: Path, *, pool=None):
    if pool is None:
        pool = _NoopPool()
    return dict(
        authority_root=tmp_path / "authorities",
        required_models=(RequiredModelRuntime(model_id="qwen3-8b", role="agent"),),
        assets=object(),
        resource_authority=UniversalResourceAuthority(tmp_path / "resources.sqlite"),
        model_resources=object(),
        state_root=tmp_path / "model",
        runtime_workdir=tmp_path / "model" / "physical-runtime-workdir",
        model_replica_pool=pool,
        deployment_runtime=object(),
        compute_inventory=object(),
        gpu_runtime_observer=None,
        host_runtime_observer=None,
        execution_pool=object(),
    )


def test_refresh_materializes_missing_authority_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = _refresh_kwargs(tmp_path)
    captured = []

    def bootstrap(**rows):
        captured.append(rows)
        assert rows["resource_authority"] is kwargs["resource_authority"]
        return "bootstrap-receipt"

    monkeypatch.setattr(
        model_runtime_refresh,
        "bootstrap_required_qualified_model_runtime",
        bootstrap,
    )
    receipts = model_runtime_refresh.refresh_required_qualified_model_runtimes(**kwargs)
    assert receipts == ("bootstrap-receipt",)
    assert kwargs["authority_root"].is_dir()
    assert len(captured) == 1
    assert "compute_scheduler" not in captured[0]


def test_refresh_rejects_symlink_authority_root(tmp_path: Path) -> None:
    kwargs = _refresh_kwargs(tmp_path)
    real_root = tmp_path / "real"
    real_root.mkdir()
    kwargs["authority_root"].symlink_to(real_root, target_is_directory=True)
    with pytest.raises(RuntimeError, match="must be a real directory"):
        model_runtime_refresh.refresh_required_qualified_model_runtimes(**kwargs)


def test_refresh_requires_current_model_qualification_protocol() -> None:
    source = _source()
    legacy = SimpleNamespace(
        deployments=(source,),
        runtime_manifest_digest="b" * 64,
        runtime_qualifications=_ReceiptStore("heartbeat:sha256:" + "c" * 64),
    )
    gpu_only = SimpleNamespace(
        deployments=(source,),
        runtime_manifest_digest="b" * 64,
        runtime_qualifications=_ReceiptStore(GPU_MEMORY_ACCOUNTING_EVIDENCE_REF),
    )
    current = SimpleNamespace(
        deployments=(source,),
        runtime_manifest_digest="b" * 64,
        runtime_qualifications=_ReceiptStore(
            GPU_MEMORY_ACCOUNTING_EVIDENCE_REF,
            STATIC_QUALIFICATION_PROTOCOL_EVIDENCE_REF,
        ),
    )
    assert not model_runtime_refresh._uses_current_model_qualification_protocol(legacy)
    assert not model_runtime_refresh._uses_current_model_qualification_protocol(gpu_only)
    assert model_runtime_refresh._uses_current_model_qualification_protocol(current)


def test_refresh_replica_source_groups_preserve_exact_stack_replica_count() -> None:
    stack = _source().stack
    certificate = SimpleNamespace(
        target_host_identity_digest="host-a",
        digest=lambda: "c" * 64,
    )
    sources = tuple(
        SimpleNamespace(
            deployment_id=f"deployment-{ordinal}",
            stack=stack,
            certificate=certificate,
        )
        for ordinal in (2, 1)
    )
    closure = SimpleNamespace(deployments=sources)

    groups = model_runtime_refresh._refresh_replica_source_groups(
        closure,
        required_model_ids=frozenset({"qwen3-8b"}),
    )

    assert len(groups) == 1
    assert tuple(row.deployment_id for row in groups[0]) == (
        "deployment-1",
        "deployment-2",
    )


def test_refresh_replica_source_groups_fail_closed_on_certificate_drift() -> None:
    stack = _source().stack
    closure = SimpleNamespace(
        deployments=(
            SimpleNamespace(
                deployment_id="deployment-1",
                stack=stack,
                certificate=SimpleNamespace(
                    target_host_identity_digest="host-a",
                    digest=lambda: "c" * 64,
                ),
            ),
            SimpleNamespace(
                deployment_id="deployment-2",
                stack=stack,
                certificate=SimpleNamespace(
                    target_host_identity_digest="host-a",
                    digest=lambda: "d" * 64,
                ),
            ),
        )
    )

    with pytest.raises(ValueError, match="conflicting certificates"):
        model_runtime_refresh._refresh_replica_source_groups(
            closure,
            required_model_ids=frozenset({"qwen3-8b"}),
        )


def test_unplaceable_refresh_bootstraps_current_model_from_authority_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    authority_root = tmp_path / "authorities"
    closure_path = authority_root / "models" / "qwen3-8b" / "qualified-model-closure.json"
    closure_path.parent.mkdir(parents=True)
    closure_path.write_text("{}", encoding="utf-8")
    closure = SimpleNamespace(
        deployments=(source,),
        role_manifest=SimpleNamespace(
            assignments=(
                SimpleNamespace(
                    role="agent",
                    capability_id="generation",
                    input_schema_id="model.generation.request.v1",
                    output_schema_id="model.generation.response.v1",
                    deployment_id=source.deployment_id,
                ),
            )
        ),
        runtime_canary_evidence=(
            SimpleNamespace(
                role="agent",
                capability_id="generation",
                input_schema_id="model.generation.request.v1",
                output_schema_id="model.generation.response.v1",
                deployment_id=source.deployment_id,
                passed=True,
                verified_capabilities=("generation",),
            ),
        ),
        runtime_manifest_digest="b" * 64,
        runtime_qualifications=_ReceiptStore(
            GPU_MEMORY_ACCOUNTING_EVIDENCE_REF,
            STATIC_QUALIFICATION_PROTOCOL_EVIDENCE_REF,
        ),
    )
    requirement = ComputeRequirement(
        cpu_cores=4,
        memory_bytes=8 * 1024**3,
        gpu_count=2,
        required_gpu_free_memory_bytes=40 * 1024**3,
        gpu_admission_headroom_fraction=0.05,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )
    materialized_stack = SimpleNamespace(stack=source.stack, compute=requirement)

    monkeypatch.setattr(model_runtime_refresh, "_load_strict", lambda _path: closure)
    observed_topologies = []
    def materializations(model_topologies, **_kwargs):
        observed_topologies.extend(model_topologies)
        return {
            topology: materialized_stack for topology in model_topologies
        }
    monkeypatch.setattr(
        model_runtime_refresh,
        "_desired_stack_materializations",
        materializations,
    )
    monkeypatch.setattr(
        model_runtime_refresh,
        "qualification_source_stack_digest",
        lambda stack: stack.digest(),
    )
    monkeypatch.setattr(
        model_runtime_refresh,
        "ModelReplicaPoolRequest",
        lambda **rows: SimpleNamespace(**rows),
    )

    captured = []

    class Pool:
        def ensure(self, request):
            captured.append(request)
            raise ComputePlacementUnavailable(request.compute)

        def reclaim_one_stale_warm_realization(self):
            return None

        def reclaim_dominated_warm_realizations(self):
            return ()

    class Inventory:
        def host(self, host_id: str):
            assert host_id == "host-a"
            return object()

    bootstraps = []

    def bootstrap(**rows):
        bootstraps.append(rows)
        return "bootstrap-receipt"

    monkeypatch.setattr(
        model_runtime_refresh,
        "bootstrap_required_qualified_model_runtime",
        bootstrap,
    )
    kwargs = _refresh_kwargs(tmp_path, pool=Pool())
    kwargs["authority_root"] = authority_root
    kwargs["compute_inventory"] = Inventory()
    receipts = model_runtime_refresh.refresh_required_qualified_model_runtimes(**kwargs)

    assert receipts == ("bootstrap-receipt",)
    assert observed_topologies == [("qwen3-8b", 2, 39145, 0)]
    assert len(captured) == 1
    assert captured[0].compute is requirement
    assert len(bootstraps) == 1
    assert bootstraps[0]["resource_authority"] is kwargs["resource_authority"]
    assert "compute_scheduler" not in bootstraps[0]

def test_closure_role_coverage_rejects_same_model_with_missing_role() -> None:
    source = _source()
    closure = SimpleNamespace(
        deployments=(source,),
        role_manifest=SimpleNamespace(
            assignments=(
                SimpleNamespace(
                    role="planner",
                    capability_id="generation",
                    input_schema_id="model.generation.request.v1",
                    output_schema_id="model.generation.response.v1",
                    deployment_id=source.deployment_id,
                ),
            )
        ),
        runtime_canary_evidence=(
            SimpleNamespace(
                role="planner",
                capability_id="generation",
                input_schema_id="model.generation.request.v1",
                output_schema_id="model.generation.response.v1",
                deployment_id=source.deployment_id,
                passed=True,
                verified_capabilities=("generation", "structured_output"),
            ),
        ),
    )
    rows = (
        RequiredModelRuntime(model_id="qwen3-8b", role="planner"),
        RequiredModelRuntime(model_id="qwen3-8b", role="meta_architect"),
    )
    assert not model_runtime_refresh._closure_covers_required_model_rows(
        closure, model_id="qwen3-8b", rows=rows
    )
    assert model_runtime_refresh._closure_covers_required_model_rows(
        closure, model_id="qwen3-8b", rows=(rows[0],)
    )


def test_refresh_single_flight_serializes_same_model_without_global_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = Event()
    release = Event()
    guard = Lock()
    order: list[str] = []
    calls = 0

    def unfenced(**_kwargs):
        nonlocal calls
        with guard:
            calls += 1
            ordinal = calls
            order.append(f"enter-{ordinal}")
        if ordinal == 1:
            entered.set()
            if not release.wait(5):
                raise TimeoutError("same-model refresh release gate did not open")
            with guard:
                order.append("exit-1")
        return (f"receipt-{ordinal}",)

    monkeypatch.setattr(
        model_runtime_refresh,
        "_refresh_required_qualified_model_runtimes_unfenced",
        unfenced,
    )
    kwargs = _refresh_kwargs(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            model_runtime_refresh.refresh_required_qualified_model_runtimes,
            **kwargs,
        )
        assert entered.wait(3)
        second = executor.submit(
            model_runtime_refresh.refresh_required_qualified_model_runtimes,
            **kwargs,
        )
        time.sleep(0.1)
        with guard:
            assert order == ["enter-1"]
        release.set()
        assert first.result(timeout=3) == ("receipt-1",)
        assert second.result(timeout=3) == ("receipt-2",)

    assert order == ["enter-1", "exit-1", "enter-2"]


def test_refresh_single_flight_preserves_concurrency_for_distinct_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    both_entered = Event()
    release = Event()
    guard = Lock()
    entered: set[str] = set()

    def unfenced(**kwargs):
        model_id = kwargs["required_models"][0].model_id
        with guard:
            entered.add(model_id)
            if len(entered) == 2:
                both_entered.set()
        if not release.wait(5):
            raise TimeoutError("distinct-model refresh release gate did not open")
        return (model_id,)

    monkeypatch.setattr(
        model_runtime_refresh,
        "_refresh_required_qualified_model_runtimes_unfenced",
        unfenced,
    )
    first_kwargs = _refresh_kwargs(tmp_path)
    second_kwargs = dict(first_kwargs)
    second_kwargs["required_models"] = (
        RequiredModelRuntime(model_id="other-model", role="agent"),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            model_runtime_refresh.refresh_required_qualified_model_runtimes,
            **first_kwargs,
        )
        second = executor.submit(
            model_runtime_refresh.refresh_required_qualified_model_runtimes,
            **second_kwargs,
        )
        assert both_entered.wait(3)
        release.set()
        assert first.result(timeout=3) == ("qwen3-8b",)
        assert second.result(timeout=3) == ("other-model",)
