"""Process-local scheduler writer is owned by the execution pool lifetime."""
from __future__ import annotations

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
    DurableUnifiedSchedulingAuthority,
)
from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority


def test_execution_pool_closes_scheduler_writer_after_domain_convergence(tmp_path):
    resource = UniversalResourceAuthority(tmp_path / "resource.sqlite")
    pool = ResearchExecutionPool(resource_authority=resource)
    scheduler = pool.scheduling_authority
    assert isinstance(scheduler, DurableUnifiedSchedulingAuthority)
    assert scheduler._writers.open_count == 0
    scheduler.record_grant(tenant_id="paper", flow_id="warm")
    scheduler.record_completion(
        tenant_id="paper", flow_id="warm", service_quanta=1,
    )
    assert scheduler._writers.open_count == 1

    pool.close()
    assert scheduler._closed
    assert scheduler._writers._closed
    pool.close()
