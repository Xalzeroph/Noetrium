from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import ExecutionLaneKind
from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget,
    AdmissionIdentity,
    AdmissionIntent,
    AdmissionRejected,
)
from noetrium_platform.research.execution.policy.composition import (
    build_admission_scheduling_policy,
    build_execution_admission,
)


def _authority(*, queue_wait_timeout_seconds: float | None = 0.0):
    authority = build_execution_admission(
        budget=AdmissionBudget(
            max_total_in_flight=4,
            max_in_flight_per_group=4,
            max_in_flight_per_tenant=3,
            max_in_flight_per_resource=3,
            max_blocking_io_in_flight=4,
            max_async_io_in_flight=4,
            max_cpu_in_flight=4,
            max_serial_in_flight=4,
        ),
        scheduling=build_admission_scheduling_policy(),
    )
    authority.register_group(
        "batch",
        identity=AdmissionIdentity(
            tenant_id="tenant-a",
            resource_id="resource-a",
        ),
        intent=AdmissionIntent(queue_wait_timeout_seconds=queue_wait_timeout_seconds),
    )
    return authority


def test_atomic_batch_admission_never_partially_grants_on_rejection() -> None:
    authority = _authority()
    leases = authority.acquire_many(
        "batch",
        ExecutionLaneKind.BLOCKING_IO,
        permit_count=3,
        deadline=None,
        cancellation=None,
    )
    assert len(leases) == 3
    snapshot = authority.snapshot()
    assert snapshot.in_flight == 3
    assert snapshot.admitted_total == 3
    assert snapshot.groups[0].in_flight == 3
    assert snapshot.tenants[0].in_flight == 3
    assert snapshot.resources[0].in_flight == 3

    with pytest.raises(AdmissionRejected):
        authority.acquire_many(
            "batch",
            ExecutionLaneKind.BLOCKING_IO,
            permit_count=2,
            deadline=None,
            cancellation=None,
        )

    rejected = authority.snapshot()
    assert rejected.in_flight == 3
    assert rejected.admitted_total == 3
    assert rejected.rejected_total == 2

    leases[0].release()
    assert authority.snapshot().in_flight == 2
    replacement = authority.acquire(
        "batch",
        ExecutionLaneKind.BLOCKING_IO,
        deadline=None,
        cancellation=None,
    )
    assert authority.snapshot().in_flight == 3

    replacement.release()
    for lease in leases[1:]:
        lease.release()
    assert authority.snapshot().in_flight == 0
    authority.unregister_group("batch")
    authority.close()


def test_atomic_batch_larger_than_static_scope_capacity_fails_immediately() -> None:
    authority = _authority(queue_wait_timeout_seconds=None)

    with pytest.raises(
        AdmissionRejected,
        match="batch exceeds configured capacity",
    ):
        authority.acquire_many(
            "batch",
            ExecutionLaneKind.BLOCKING_IO,
            permit_count=4,
            deadline=None,
            cancellation=None,
        )

    snapshot = authority.snapshot()
    assert snapshot.in_flight == 0
    assert snapshot.waiting == 0
    assert snapshot.queued_total == 0
    assert snapshot.admitted_total == 0
    authority.unregister_group("batch")
    authority.close()


def test_atomic_batch_rejects_invalid_cardinality_fail_closed() -> None:
    authority = _authority()

    for value in (0, -1, True):
        with pytest.raises(ValueError):
            authority.acquire_many(
                "batch",
                ExecutionLaneKind.BLOCKING_IO,
                permit_count=value,
                deadline=None,
                cancellation=None,
            )

    assert authority.snapshot().in_flight == 0
    authority.unregister_group("batch")
    authority.close()
