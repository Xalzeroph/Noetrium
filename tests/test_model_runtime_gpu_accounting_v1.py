from __future__ import annotations

import pytest

from noetrium_platform.composition.model_runtime_bootstrap import (
    _gpu_memory_bytes,
    _managed_container_id,
)
from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandResult
from noetrium_platform.infrastructure.resources.compute.api import (
    GpuDeviceStatus,
    GpuProcessStatus,
    GpuRuntimeSnapshot,
)


class _Runner:
    def __init__(self, *, top_output: str = "PID\n") -> None:
        self.top_output = top_output

    def run(self, argv, *, cwd=None, environment=None, timeout_seconds=None):
        args = tuple(argv)
        if args[:2] == ("docker", "top"):
            return LocalCommandResult(args, 0, self.top_output, "")
        raise AssertionError(args)


class _Resources:
    def __init__(self, snapshot: GpuRuntimeSnapshot) -> None:
        self.snapshot_value = snapshot

    def gpu_runtime(self) -> GpuRuntimeSnapshot:
        return self.snapshot_value


def _snapshot(*, complete: bool = True, include_second_gpu: bool = True) -> GpuRuntimeSnapshot:
    processes = [
        GpuProcessStatus(101, "GPU-a", 6000, "model-worker"),
        GpuProcessStatus(102, "GPU-a", 2000, "model-worker"),
        GpuProcessStatus(999, "GPU-a", 30000, "foreign-worker"),
    ]
    if include_second_gpu:
        processes.append(GpuProcessStatus(103, "GPU-b", 7000, "model-worker"))
    return GpuRuntimeSnapshot(
        True,
        devices=(
            GpuDeviceStatus("0", "GPU-a", "gpu", 49140, 45000, 4140, 99),
            GpuDeviceStatus("1", "GPU-b", "gpu", 49140, 40000, 9140, 50),
        ),
        processes=tuple(processes),
        processes_complete=complete,
    )


def test_gpu_qualification_counts_only_container_owned_process_memory() -> None:
    runner = _Runner(top_output="PID\n100\n101\n102\n103\n")
    observed = _gpu_memory_bytes(
        _Resources(_snapshot()),
        ("GPU-a", "GPU-b"),
        runner,
        "container-a",
    )
    assert observed == 8000 * 1024 * 1024


def test_gpu_qualification_fails_closed_on_incomplete_process_inventory() -> None:
    runner = _Runner(top_output="PID\n100\n101\n102\n103\n")
    with pytest.raises(RuntimeError, match="incomplete"):
        _gpu_memory_bytes(
            _Resources(_snapshot(complete=False)),
            ("GPU-a", "GPU-b"),
            runner,
            "container-a",
        )


def test_gpu_qualification_requires_process_coverage_for_every_placed_gpu() -> None:
    runner = _Runner(top_output="PID\n100\n101\n102\n")
    with pytest.raises(RuntimeError, match="GPU-b"):
        _gpu_memory_bytes(
            _Resources(_snapshot(include_second_gpu=False)),
            ("GPU-a", "GPU-b"),
            runner,
            "container-a",
        )


def test_managed_container_resolution_uses_exact_applied_host_pid() -> None:
    class Runner:
        def run(self, argv, *, cwd=None, environment=None, timeout_seconds=None):
            args = tuple(argv)
            if args[:2] == ("docker", "ps"):
                return LocalCommandResult(args, 0, "container-a\ncontainer-b\n", "")
            if args[:2] == ("docker", "inspect"):
                return LocalCommandResult(args, 0, "sha-a 77\nsha-b 88\n", "")
            raise AssertionError(args)

    assert _managed_container_id(Runner(), 88) == "sha-b"


def test_gpu_memory_accounting_evidence_ref_is_digest_bound():
    from noetrium_platform.composition.model_runtime_bootstrap import (
        GPU_MEMORY_ACCOUNTING_EVIDENCE_REF,
    )

    prefix = "gpu-memory-accounting:sha256:"
    assert GPU_MEMORY_ACCOUNTING_EVIDENCE_REF.startswith(prefix)
    digest = GPU_MEMORY_ACCOUNTING_EVIDENCE_REF[len(prefix):]
    assert len(digest) == 64
    assert all(ch in "0123456789abcdef" for ch in digest)
