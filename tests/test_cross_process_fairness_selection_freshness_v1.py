"""An unchanged local admission queue must follow foreign service commits."""
from __future__ import annotations

import subprocess
import sys

from noetrium_platform.foundation.kernel.concurrency.api import ExecutionLaneKind
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
    DurableUnifiedSchedulingAuthority,
)
from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget, AdmissionIdentity, AdmissionIntent,
)
from noetrium_platform.research.execution.policy.runtime.authority import (
    HierarchicalAdmissionAuthority, _Waiter,
)


def test_foreign_service_invalidates_local_cached_waiter_order(tmp_path) -> None:
    ledger = tmp_path / "authority.sqlite"
    scheduler = DurableUnifiedSchedulingAuthority(ledger)
    admission = HierarchicalAdmissionAuthority(
        budget=AdmissionBudget(
            max_total_in_flight=2,
            max_in_flight_per_group=1,
            max_blocking_io_in_flight=2,
        ),
        scheduling_authority=scheduler,
    )
    for group, tenant in (("flow-a", "paper-a"), ("flow-b", "paper-b")):
        admission.register_group(group, identity=AdmissionIdentity(tenant_id=tenant))
    with admission._condition:
        for ticket, group in ((1, "flow-a"), (2, "flow-b")):
            admission._enqueue_waiter(_Waiter(
                ticket=ticket,
                group_id=group,
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
                permit_count=1,
                intent=AdmissionIntent(),
                enqueued_monotonic=1.0,
            ))
        assert admission._selected_waiter().ticket == 1
        queue_version_before = admission._queue_version

    script = """
import sys
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import DurableUnifiedSchedulingAuthority
scheduler=DurableUnifiedSchedulingAuthority(sys.argv[1])
scheduler.record_grant(tenant_id="paper-a",flow_id="foreign-work",reserved_service_quanta=500)
scheduler.record_completion(tenant_id="paper-a",flow_id="foreign-work",service_quanta=500,reserved_service_quanta=500)
"""
    subprocess.run(
        [sys.executable, "-c", script, str(ledger)],
        check=True, timeout=20, capture_output=True, text=True,
    )
    with admission._condition:
        # No local queue mutation occurred. Only the durable scheduling
        # authority's committed history can cause this selection to change.
        assert len(admission._waiters) == 2
        assert admission._queue_version == queue_version_before
        assert admission._selected_waiter().ticket == 2
        assert admission._queue_version > queue_version_before
