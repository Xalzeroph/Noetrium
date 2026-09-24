from __future__ import annotations

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_os_local import compose_local_research_os


def test_local_research_os_borrows_injected_execution_pool(tmp_path) -> None:
    pool = ResearchExecutionPool()
    composition = compose_local_research_os(
        tmp_path / "research-os",
        execution_pool=pool,
    )
    assert composition.execution_pool is pool

    composition.close()

    group = pool.open_orchestration_group("after-research-os-close")
    pool.close_orchestration_group(group)
    pool.close()
