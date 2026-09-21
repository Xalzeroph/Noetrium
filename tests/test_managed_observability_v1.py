from __future__ import annotations

from noetrium_platform.composition.managed_observability import (
    build_managed_observability,
)
from noetrium_platform.composition.platform_meta import build_in_memory_platform_meta
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool


def test_managed_observability_builds_durable_default_authorities(tmp_path) -> None:
    pool = ResearchExecutionPool()
    group = pool.open_orchestration_group("observability-test")
    meta = build_in_memory_platform_meta()
    managed = build_managed_observability(
        tmp_path / "observability",
        task_group=group,
        systems=meta.systems,
        planner=meta.capability_composition,
    )
    try:
        assert managed.telemetry.registry.names()
        assert managed.telemetry.count() == 0
        assert managed.raw.health().accepted == 0
        assert managed.logging.logging is not None
        assert (tmp_path / "observability" / "telemetry.sqlite").is_file()
        assert managed.logging.plan.digest
        assert managed.logging.offer.offer_id == (
            "observability.logging.structured-logging-system"
        )
    finally:
        managed.close()
        pool.close_orchestration_group(group, cancel_pending=True)
        pool.close()


def test_managed_observability_close_is_idempotent(tmp_path) -> None:
    pool = ResearchExecutionPool()
    group = pool.open_orchestration_group("observability-close-test")
    meta = build_in_memory_platform_meta()
    managed = build_managed_observability(
        tmp_path / "observability",
        task_group=group,
        systems=meta.systems,
        planner=meta.capability_composition,
    )
    managed.close()
    managed.close()
    pool.close_orchestration_group(group, cancel_pending=True)
    pool.close()
