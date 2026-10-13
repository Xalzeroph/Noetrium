from __future__ import annotations

from resource_test_support import make_execution_pool

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_runtime_local import compose_local_research_runtime


def test_local_research_borrows_injected_execution_pool(tmp_path) -> None:
    pool = make_execution_pool()
    composition = compose_local_research_runtime(
        tmp_path / "research",
        execution_pool=pool,
    )
    assert composition.execution_pool is pool

    composition.close()

    group = pool.open_orchestration_group("after-research-close")
    pool.close_orchestration_group(group)
    pool.close()
