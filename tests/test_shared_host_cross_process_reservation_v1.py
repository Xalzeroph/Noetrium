from __future__ import annotations

from noetrium_platform.composition.concurrency import build_scheduling_authority

import multiprocessing as mp
import os
from pathlib import Path
import time
from uuid import uuid4

from noetrium_platform.composition.shared_host_pressure import (
    ResourceCompetitionAdmissionGate,
    ResourceCompetitionDemand,
    ResourceCompetitionPolicy,
    ResourceCompetitionReservations,
    _default_resource_competition_directory,
)
from noetrium_platform.composition.runtime_coordination import (
    runtime_coordination_root,
    runtime_fabric_root,
)
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionLaneKind
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority
from noetrium_platform.infrastructure.resources.compute.api import (
    HostRuntimeSnapshot,
    HostRuntimeStatus,
)
from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget,
    AdmissionIdentity,
    AdmissionIntent,
    AdmissionRejected,
)
from noetrium_platform.research.execution.policy.composition import (
    build_execution_admission,
)


def test_reservation_linearization_prefers_explicit_runtime_coordination_root(
    monkeypatch, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("NOETRIUM_RUNTIME_COORDINATION_ROOT", str(runtime_root))
    resolved = _default_resource_competition_directory()
    assert resolved.is_relative_to(runtime_root / "resource-competition")


def test_reservation_linearization_uses_xdg_runtime_when_unbound(
    monkeypatch, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "xdg"
    runtime_root.mkdir()
    monkeypatch.delenv("NOETRIUM_RUNTIME_COORDINATION_ROOT", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_root))
    assert runtime_coordination_root() == runtime_root / "noetrium"


def test_runtime_fabric_and_ephemeral_linearization_use_distinct_roots(
    monkeypatch, tmp_path: Path
) -> None:
    coordination_root = tmp_path / "runtime"
    fabric_root = tmp_path / "fabric"
    monkeypatch.setenv("NOETRIUM_RUNTIME_COORDINATION_ROOT", str(coordination_root))
    monkeypatch.setenv("NOETRIUM_RUNTIME_FABRIC_ROOT", str(fabric_root))
    assert runtime_fabric_root().is_relative_to(fabric_root)
    assert _default_resource_competition_directory().is_relative_to(
        coordination_root / "resource-competition"
    )


def test_reservation_linearization_rejects_relative_explicit_root(monkeypatch) -> None:
    monkeypatch.setenv("NOETRIUM_RUNTIME_COORDINATION_ROOT", "relative/runtime")
    try:
        runtime_coordination_root()
    except ValueError as exc:
        assert "absolute path" in str(exc)
    else:
        raise AssertionError("relative runtime coordination root was accepted")


class _FixedHostObserver:
    def snapshot(self) -> HostRuntimeSnapshot:
        return HostRuntimeSnapshot(
            True,
            (
                HostRuntimeStatus(
                    "cross-process-host",
                    True,
                    effective_cpu_cores=8.0,
                    cpu_load_1m=0.0,
                    available_memory_bytes=100,
                    cpu_pressure_some_avg10_percent=0.0,
                    memory_pressure_some_avg10_percent=0.0,
                    io_pressure_some_avg10_percent=0.0,
                    available_pids=100,
                    available_fds=100,
                ),
            ),
        )


def _gate(root: str, *, ttl_seconds: float):
    base = Path(root)
    authority = UniversalResourceAuthority(base / "platform-resources.sqlite")
    owner = uuid4().hex
    lease = authority.acquire_ttl_lease(
        lease_id="cross-process-owner:" + owner,
        resource_key="cross-process-owner:" + owner,
        holder_key="cross-process-owner:" + owner,
        owner_scope=PLATFORM_SCOPE,
        ttl_seconds=ttl_seconds,
        metadata={"kind": "cross-process-test-owner"},
    )
    reservations = ResourceCompetitionReservations(
        authority,
        lease,
        coordination_directory=base / "coordination",
    )
    admission = build_execution_admission(
        budget=AdmissionBudget(max_total_in_flight=1, max_waiting=2),
        scheduling_authority=build_scheduling_authority(),
    )
    gate = ResourceCompetitionAdmissionGate(
        admission,
        _FixedHostObserver(),
        policy=ResourceCompetitionPolicy(
            min_available_memory_bytes=0,
            min_available_pids=0,
            min_available_fds=0,
            min_storage_free_bytes=0,
            min_storage_free_inodes=0,
            min_storage_free_fraction=0.0,
        ),
        reservations=reservations,
    )
    gate.register_group(
        "g",
        identity=AdmissionIdentity(),
        intent=AdmissionIntent(queue_wait_timeout_seconds=0.0),
    )
    gate.set_group_demand(
        "g",
        ResourceCompetitionDemand(memory_bytes_per_permit=60),
    )
    return gate, authority, lease, reservations


def _race_worker(root: str, barrier, release_event, results) -> None:
    gate, authority, owner_lease, reservations = _gate(root, ttl_seconds=20.0)
    barrier.wait(timeout=10.0)
    try:
        lease = gate.acquire(
            "g", ExecutionLaneKind.CPU, deadline=None, cancellation=None
        )
    except AdmissionRejected:
        results.put("rejected")
    else:
        results.put("admitted")
        release_event.wait(timeout=10.0)
        lease.release()
    finally:
        reservations.close()
        authority.release_lease(owner_lease)


def _crash_worker(root: str, marker: str) -> None:
    gate, _authority, _owner_lease, _reservations = _gate(
        root, ttl_seconds=0.5
    )
    gate.acquire("g", ExecutionLaneKind.CPU, deadline=None, cancellation=None)
    Path(marker).write_text("admitted")
    os._exit(0)


def test_authority_backed_reservations_fence_parallel_processes(tmp_path) -> None:
    ctx = mp.get_context("spawn")
    root = str(tmp_path / "authority")
    barrier = ctx.Barrier(2)
    release_event = ctx.Event()
    results = ctx.Queue()
    processes = tuple(
        ctx.Process(target=_race_worker, args=(root, barrier, release_event, results))
        for _ in range(2)
    )
    for process in processes:
        process.start()
    observed = sorted(results.get(timeout=15.0) for _ in range(2))
    assert observed == ["admitted", "rejected"]
    release_event.set()
    for process in processes:
        process.join(timeout=15.0)
        assert process.exitcode == 0


def test_owner_ttl_expiry_reclaims_reservation_after_process_crash(tmp_path) -> None:
    ctx = mp.get_context("spawn")
    root = tmp_path / "authority"
    marker = tmp_path / "crash-admitted"
    process = ctx.Process(target=_crash_worker, args=(str(root), str(marker)))
    process.start()
    deadline = time.monotonic() + 15.0
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists()
    process.join(timeout=15.0)
    assert process.exitcode == 0

    # The dead process has no owner lock. Authority TTL + orphan reconciliation
    # is the sole crash proof, so wait only for its explicit lease expiry.
    time.sleep(0.65)
    gate, authority, owner_lease, reservations = _gate(
        str(root), ttl_seconds=20.0
    )
    lease = gate.acquire("g", ExecutionLaneKind.CPU, deadline=None, cancellation=None)
    lease.release()
    reservations.close()
    authority.release_lease(owner_lease)

    assert not list((root / "coordination").glob("owner-*"))
