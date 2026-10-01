from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from noetrium_platform.composition import model_runtime_refresh
from noetrium_platform.composition.model_runtime_bootstrap import RequiredModelRuntime
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputePlacementUnavailable,
    GpuSharingMode,
)
from noetrium_platform.composition.model_runtime_bootstrap import (
    GPU_MEMORY_ACCOUNTING_EVIDENCE_REF,
)


def test_refresh_materializes_missing_authority_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_root = tmp_path / "state" / "authorities"
    project_root = tmp_path / "project"
    project_root.mkdir()

    def bootstrap(**kwargs):
        assert kwargs["authority_root"] == authority_root
        assert authority_root.is_dir()
        return "bootstrap-receipt"

    monkeypatch.setattr(
        model_runtime_refresh,
        "bootstrap_required_qualified_model_runtime",
        bootstrap,
    )

    receipts = model_runtime_refresh.refresh_required_qualified_model_runtimes(
        authority_root=authority_root,
        project_root=project_root,
        required_models=(RequiredModelRuntime(model_id="qwen3-8b", role="agent"),),
        assets=None,
        compute_scheduler=None,
        model_resources=None,
        state_root=tmp_path / "model",
        runtime_workdir=(tmp_path / "model") / "physical-runtime-workdir",
        model_replica_pool=object(),
        deployment_runtime=None,
        compute_inventory=None,
        execution_pool=None,
    )

    assert receipts == ("bootstrap-receipt",)
    assert authority_root.is_dir()


def test_refresh_rejects_symlink_authority_root(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    authority_root = tmp_path / "authorities"
    authority_root.symlink_to(real_root, target_is_directory=True)
    project_root = tmp_path / "project"
    project_root.mkdir()

    with pytest.raises(RuntimeError, match="must be a real directory"):
        model_runtime_refresh.refresh_required_qualified_model_runtimes(
            authority_root=authority_root,
            project_root=project_root,
            required_models=(RequiredModelRuntime(model_id="qwen3-8b", role="agent"),),
            assets=None,
            compute_scheduler=None,
            model_resources=None,
            state_root=tmp_path / "model",
            runtime_workdir=(tmp_path / "model") / "physical-runtime-workdir",
            model_replica_pool=object(),
            deployment_runtime=None,
            compute_inventory=None,
            execution_pool=None,
        )

def _source(*, peak_gpu: int = 10 * 1024**3):
    return SimpleNamespace(
        deployment_id="deployment-old",
        stack=SimpleNamespace(
            identity=SimpleNamespace(model_id="qwen3-8b", engine="vllm"),
            tensor_parallel=2,
            pipeline_parallel=1,
            digest=lambda: "a" * 64,
        ),
        certificate=SimpleNamespace(
            target_host_identity_digest="host-a",
            resource_envelope=SimpleNamespace(
                peak_gpu_memory_bytes_per_device=peak_gpu,
                peak_host_memory_bytes=3 * 1024**3,
            ),
        ),
    )


class _ReceiptStore:
    def __init__(self, *refs: str) -> None:
        self.refs = tuple(refs)

    def load(self, runtime_manifest_digest: str, deployment_id: str):
        return SimpleNamespace(evidence_refs=self.refs)


def test_refresh_requirement_preserves_shared_gpu_semantics() -> None:
    requirement = model_runtime_refresh._refresh_compute_requirement(_source())
    assert requirement.gpu_count == 2
    assert requirement.required_gpu_free_memory_bytes == 10 * 1024**3
    assert requirement.max_gpu_utilization_percent == 100
    assert requirement.gpu_sharing_mode is GpuSharingMode.PREFER_IDLE_ALLOW_SHARED
    assert requirement.gpu_admission_headroom_fraction == pytest.approx(0.05)


def test_refresh_rejects_legacy_gpu_memory_accounting() -> None:
    source = _source()
    legacy = SimpleNamespace(
        deployments=(source,),
        runtime_manifest_digest="b" * 64,
        runtime_qualifications=_ReceiptStore("heartbeat:sha256:" + "c" * 64),
    )
    current = SimpleNamespace(
        deployments=(source,),
        runtime_manifest_digest="b" * 64,
        runtime_qualifications=_ReceiptStore(GPU_MEMORY_ACCOUNTING_EVIDENCE_REF),
    )
    assert not model_runtime_refresh._uses_current_gpu_memory_accounting(legacy)
    assert model_runtime_refresh._uses_current_gpu_memory_accounting(current)


def test_unplaceable_refresh_rematerializes_current_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_root = tmp_path / "authorities"
    closure_path = authority_root / "models" / "qwen3-8b" / "qualified-model-closure.json"
    closure_path.parent.mkdir(parents=True)
    closure_path.write_text("{}", encoding="utf-8")
    project_root = tmp_path / "project"
    project_root.mkdir()
    source = _source(peak_gpu=40 * 1024**3)
    closure = SimpleNamespace(
        deployments=(source,),
        runtime_manifest_digest="b" * 64,
        runtime_qualifications=_ReceiptStore(GPU_MEMORY_ACCOUNTING_EVIDENCE_REF),
    )
    monkeypatch.setattr(model_runtime_refresh, "_load_strict", lambda path: closure)
    monkeypatch.setattr(
        model_runtime_refresh,
        "ModelReplicaPoolRequest",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        model_runtime_refresh,
        "_desired_stack_materializations",
        lambda model_topologies, **kwargs: {
            topology: SimpleNamespace(
                stack=SimpleNamespace(digest=lambda: "a" * 64),
                compute=model_runtime_refresh._refresh_compute_requirement(source),
            )
            for topology in model_topologies
        },
    )
    monkeypatch.setattr(
        model_runtime_refresh,
        "qualification_source_stack_digest",
        lambda stack: stack.digest(),
    )

    captured = []

    class Pool:
        def ensure(self, request):
            captured.append(request)
            raise ComputePlacementUnavailable(request.compute)

        def reclaim_one_stale_warm_realization(self):
            return None

    class Inventory:
        def host(self, host_id: str):
            assert host_id == "host-a"
            return object()

    bootstraps = []

    def bootstrap(**kwargs):
        bootstraps.append(kwargs["requirements"])
        return "bootstrap-receipt"

    monkeypatch.setattr(
        model_runtime_refresh,
        "bootstrap_required_qualified_model_runtime",
        bootstrap,
    )
    required = (RequiredModelRuntime(model_id="qwen3-8b", role="planner"),)
    receipts = model_runtime_refresh.refresh_required_qualified_model_runtimes(
        authority_root=authority_root,
        project_root=project_root,
        required_models=required,
        assets=object(),
        compute_scheduler=object(),
        model_resources=object(),
        state_root=tmp_path / "model",
        runtime_workdir=(tmp_path / "model") / "physical-runtime-workdir",
        model_replica_pool=Pool(),
        deployment_runtime=object(),
        compute_inventory=Inventory(),
        execution_pool=object(),
    )
    assert receipts == ("bootstrap-receipt",)
    assert bootstraps == [required]
    assert len(captured) == 1
    assert captured[0].compute.gpu_sharing_mode is GpuSharingMode.PREFER_IDLE_ALLOW_SHARED
