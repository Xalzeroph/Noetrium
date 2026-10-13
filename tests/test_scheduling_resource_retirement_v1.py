"""Retiring a local admission group must not cancel other global permits."""

from __future__ import annotations

from noetrium_platform.foundation.kernel.concurrency.api import ExecutionLaneKind
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
    UnifiedSchedulingAuthority, DurableUnifiedSchedulingAuthority,
)
from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget, AdmissionIdentity,
)
from noetrium_platform.research.execution.policy.runtime import HierarchicalAdmissionAuthority


def test_resource_retirement_defers_while_other_group_holds_permit():
    scheduler = UnifiedSchedulingAuthority()
    first = HierarchicalAdmissionAuthority(
        budget=AdmissionBudget(max_total_in_flight=2),
        scheduling_authority=scheduler,
    )
    second = HierarchicalAdmissionAuthority(
        budget=AdmissionBudget(max_total_in_flight=2),
        scheduling_authority=scheduler,
    )
    identity = AdmissionIdentity(tenant_id="paper", resource_id="workload-dag:shared")
    first.register_group("first", identity=identity)
    second.register_group("second", identity=identity)
    lease = first.acquire(
        "first", ExecutionLaneKind.BLOCKING_IO, deadline=None, cancellation=None,
    )
    # The second process/domain owns no local permits, but the global
    # resource still owns the first domain's permit.
    second.unregister_group("second")
    state = scheduler._resource_states[scheduler._resource_key("paper", "workload-dag:shared")]
    assert state.retire_requested is True
    assert state.in_flight == 1
    lease.release()
    assert state.in_flight == 0
    first.unregister_group("first")
    assert state.retire_requested is True
    first.close()
    second.close()


def test_durable_resource_retirement_survives_replay_with_live_other_flow(tmp_path):
    db = tmp_path / "global-scheduling.sqlite3"
    first = DurableUnifiedSchedulingAuthority(db)
    first.record_grant(
        tenant_id="paper", resource_id="workload-dag:shared", flow_id="running",
    )
    other = DurableUnifiedSchedulingAuthority(db)
    other.release_resource(tenant_id="paper", resource_id="workload-dag:shared")
    first.record_completion(
        tenant_id="paper", resource_id="workload-dag:shared",
        flow_id="running", service_quanta=1,
    )
    restarted = DurableUnifiedSchedulingAuthority(db)
    restarted.record_grant(
        tenant_id="paper", resource_id="workload-dag:shared", flow_id="next",
    )
    state = restarted._resource_states[restarted._resource_key("paper", "workload-dag:shared")]
    assert state.in_flight == 1
    assert state.retire_requested is False
    restarted.record_completion(
        tenant_id="paper", resource_id="workload-dag:shared",
        flow_id="next", service_quanta=1,
    )
