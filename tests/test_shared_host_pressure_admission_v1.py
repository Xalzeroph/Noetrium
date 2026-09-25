from __future__ import annotations

from threading import Event, Thread
import time

import pytest

from noetrium_platform.composition.shared_host_pressure import (
    ResourceCompetitionAdmissionGate,
    ResourceCompetitionClass,
    ResourceCompetitionPolicy,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    HostRuntimeSnapshot,
    HostRuntimeStatus,
)
from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget,
    AdmissionIdentity,
    AdmissionIntent,
    AdmissionMode,
    AdmissionRejected,
    ExecutionPriority,
)
from noetrium_platform.research.execution.policy.composition import (
    build_admission_scheduling_policy,
    build_execution_admission,
)


class _MutableHostObserver:
    def __init__(self, status: HostRuntimeStatus | None) -> None:
        self.status = status

    def snapshot(self) -> HostRuntimeSnapshot:
        if self.status is None:
            return HostRuntimeSnapshot(False, detail="simulated-unavailable")
        return HostRuntimeSnapshot(True, (self.status,))


def _status(
    *,
    load: float = 1.0,
    memory_bytes: int = 8 * 1024**3,
    cpu_pressure: float | None = 0.0,
    memory_pressure: float | None = 0.0,
    io_pressure: float | None = 0.0,
    available_pids: int | None = 256,
    available_fds: int | None = 1024,
) -> HostRuntimeStatus:
    return HostRuntimeStatus(
        "shared-node",
        True,
        effective_cpu_cores=8.0,
        cpu_load_1m=load,
        available_memory_bytes=memory_bytes,
        cpu_pressure_some_avg10_percent=cpu_pressure,
        memory_pressure_some_avg10_percent=memory_pressure,
        io_pressure_some_avg10_percent=io_pressure,
        available_pids=available_pids,
        available_fds=available_fds,
    )


def _gate(
    observer: _MutableHostObserver,
    *,
    mode: AdmissionMode = AdmissionMode.BLOCK,
    priority: ExecutionPriority = ExecutionPriority.NORMAL,
) -> ResourceCompetitionAdmissionGate:
    admission = build_execution_admission(
        budget=AdmissionBudget(max_total_in_flight=8),
        scheduling=build_admission_scheduling_policy(priority_aging_seconds=0.01),
    )
    gate = ResourceCompetitionAdmissionGate(
        admission,
        observer,
        policy=ResourceCompetitionPolicy(
            min_available_memory_bytes=1024**3,
            min_available_pids=16,
            max_cpu_pressure_some_avg10_percent=90.0,
            max_memory_pressure_some_avg10_percent=5.0,
            max_io_pressure_some_avg10_percent=40.0,
            poll_interval_seconds=0.01,
        ),
    )
    gate.register_group(
        "g",
        identity=AdmissionIdentity(),
        intent=AdmissionIntent(priority=priority, mode=mode),
    )
    return gate


def test_cpu_load_does_not_force_yield() -> None:
    observer = _MutableHostObserver(_status(load=80.0))
    gate = _gate(observer, mode=AdmissionMode.REJECT)

    lease = gate.acquire(
        "g",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    lease.release()


def test_default_policy_keeps_competing_at_soft_pressure_saturation() -> None:
    admission = build_execution_admission(
        budget=AdmissionBudget(max_total_in_flight=8),
        scheduling=build_admission_scheduling_policy(priority_aging_seconds=0.01),
    )
    gate = ResourceCompetitionAdmissionGate(
        admission,
        _MutableHostObserver(
            _status(
                load=80.0,
                cpu_pressure=100.0,
                memory_pressure=100.0,
                io_pressure=100.0,
            )
        ),
        policy=ResourceCompetitionPolicy(),
    )
    gate.register_group(
        "aggressive",
        identity=AdmissionIdentity(),
        intent=AdmissionIntent(mode=AdmissionMode.REJECT),
    )

    cpu = gate.acquire(
        "aggressive",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    cpu.release()
    io = gate.acquire(
        "aggressive",
        ExecutionLaneKind.BLOCKING_IO,
        deadline=None,
        cancellation=None,
    )
    io.release()


def test_hard_memory_headroom_still_blocks_expansion() -> None:
    observer = _MutableHostObserver(_status(memory_bytes=128 * 1024**2))
    gate = _gate(observer, mode=AdmissionMode.REJECT)

    with pytest.raises(AdmissionRejected, match="memory-headroom"):
        gate.acquire(
            "g",
            ExecutionLaneKind.CPU,
            deadline=None,
            cancellation=None,
        )


def test_pressure_clearance_resumes_blocked_work_without_external_mutation() -> None:
    observer = _MutableHostObserver(_status(memory_pressure=50.0))
    gate = _gate(observer)
    admitted = Event()
    errors: list[BaseException] = []

    def acquire() -> None:
        try:
            lease = gate.acquire(
                "g",
                ExecutionLaneKind.CPU,
                deadline=Deadline.after(1.0),
                cancellation=None,
            )
            admitted.set()
            lease.release()
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=acquire)
    thread.start()
    time.sleep(0.05)
    assert not admitted.is_set()

    observer.status = _status(memory_pressure=0.0)
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert errors == []
    assert admitted.is_set()


def test_io_pressure_gates_io_without_wasting_idle_cpu() -> None:
    observer = _MutableHostObserver(_status(load=1.0, io_pressure=75.0))
    gate = _gate(observer, mode=AdmissionMode.REJECT)

    cpu = gate.acquire(
        "g",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    cpu.release()

    with pytest.raises(AdmissionRejected, match="io-pressure"):
        gate.acquire(
            "g",
            ExecutionLaneKind.BLOCKING_IO,
            deadline=None,
            cancellation=None,
        )


def test_competition_decision_classifies_hard_safety_separately_from_soft_contention() -> None:
    hard = _gate(
        _MutableHostObserver(_status(memory_bytes=128 * 1024**2)),
        mode=AdmissionMode.REJECT,
    )
    hard_decision = hard.decision("g", ExecutionLaneKind.CPU)
    assert not hard_decision.admitted
    assert hard_decision.reason == "memory-headroom"
    assert hard_decision.competition_class is ResourceCompetitionClass.HARD_SAFETY

    soft = _gate(
        _MutableHostObserver(_status(cpu_pressure=99.0)),
        mode=AdmissionMode.REJECT,
    )
    soft_decision = soft.decision("g", ExecutionLaneKind.CPU)
    assert not soft_decision.admitted
    assert soft_decision.reason == "cpu-pressure"
    assert soft_decision.competition_class is ResourceCompetitionClass.SOFT_CONTENTION


def test_default_competition_decision_admits_soft_contention() -> None:
    admission = build_execution_admission(
        budget=AdmissionBudget(max_total_in_flight=8),
        scheduling=build_admission_scheduling_policy(priority_aging_seconds=0.01),
    )
    gate = ResourceCompetitionAdmissionGate(
        admission,
        _MutableHostObserver(
            _status(
                cpu_pressure=100.0,
                memory_pressure=100.0,
                io_pressure=100.0,
            )
        ),
        policy=ResourceCompetitionPolicy(),
    )
    gate.register_group(
        "aggressive",
        identity=AdmissionIdentity(),
        intent=AdmissionIntent(mode=AdmissionMode.REJECT),
    )
    decision = gate.decision("aggressive", ExecutionLaneKind.CPU)
    assert decision.admitted
    assert decision.reason is None
    assert decision.competition_class is None


def test_pid_headroom_blocks_expansion_before_cgroup_exhaustion() -> None:
    observer = _MutableHostObserver(_status(available_pids=8))
    gate = _gate(observer, mode=AdmissionMode.REJECT)

    with pytest.raises(AdmissionRejected, match="pid-headroom"):
        gate.acquire(
            "g",
            ExecutionLaneKind.ASYNC_IO,
            deadline=None,
            cancellation=None,
        )


def test_fd_headroom_gates_io_but_not_cpu_only_work() -> None:
    observer = _MutableHostObserver(_status(available_fds=8))
    gate = _gate(observer, mode=AdmissionMode.REJECT)

    cpu = gate.acquire(
        "g",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    cpu.release()

    with pytest.raises(AdmissionRejected, match="fd-headroom"):
        gate.acquire(
            "g",
            ExecutionLaneKind.ASYNC_IO,
            deadline=None,
            cancellation=None,
        )


@pytest.mark.parametrize(
    ("status", "lane", "reason"),
    (
        (
            _status(available_pids=None),
            ExecutionLaneKind.CPU,
            "pid-runtime-unavailable",
        ),
        (
            _status(memory_pressure=None),
            ExecutionLaneKind.CPU,
            "memory-pressure-runtime-unavailable",
        ),
        (
            _status(cpu_pressure=None),
            ExecutionLaneKind.CPU,
            "cpu-pressure-runtime-unavailable",
        ),
        (
            _status(available_fds=None),
            ExecutionLaneKind.ASYNC_IO,
            "fd-runtime-unavailable",
        ),
        (
            _status(io_pressure=None),
            ExecutionLaneKind.BLOCKING_IO,
            "io-pressure-runtime-unavailable",
        ),
    ),
)
def test_resource_specific_unknown_pressure_fails_closed(
    status: HostRuntimeStatus,
    lane: ExecutionLaneKind,
    reason: str,
) -> None:
    gate = _gate(_MutableHostObserver(status), mode=AdmissionMode.REJECT)
    with pytest.raises(AdmissionRejected, match=reason):
        gate.acquire(
            "g",
            lane,
            deadline=None,
            cancellation=None,
        )


def test_runtime_observation_failure_is_fail_closed_for_workload() -> None:
    observer = _MutableHostObserver(None)
    gate = _gate(observer, mode=AdmissionMode.REJECT)

    with pytest.raises(AdmissionRejected, match="host-runtime-unavailable"):
        gate.acquire(
            "g",
            ExecutionLaneKind.CPU,
            deadline=None,
            cancellation=None,
        )


def test_critical_control_bypasses_shared_host_pressure_gate() -> None:
    observer = _MutableHostObserver(
        _status(
            load=100.0,
            memory_bytes=0,
            cpu_pressure=100.0,
            memory_pressure=100.0,
            io_pressure=100.0,
            available_pids=0,
        )
    )
    gate = _gate(
        observer,
        mode=AdmissionMode.REJECT,
        priority=ExecutionPriority.CRITICAL,
    )

    lease = gate.acquire(
        "g",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    lease.release()


def test_blocked_pressure_respects_deadline() -> None:
    observer = _MutableHostObserver(_status(memory_pressure=50.0))
    gate = _gate(observer)

    with pytest.raises(TimeoutError, match="resource competition admission deadline expired"):
        gate.acquire(
            "g",
            ExecutionLaneKind.CPU,
            deadline=Deadline.after(0.03),
            cancellation=None,
        )
