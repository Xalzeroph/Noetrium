from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    BenchmarkResolutionRegistration,
    BenchmarkResolutionRegistry,
    BenchmarkSourceKind,
    BenchmarkSourceResolution,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
)


def _resolution(revision: str) -> BenchmarkSourceResolution:
    source_digest = canonical_digest({"benchmark": "fixture", "revision": revision})
    source = BenchmarkSourceSpec(
        source_id="fixture",
        kind=BenchmarkSourceKind.CUSTOM,
        revision_id=revision,
        locator=f"fixture://{revision}",
        content_digest=source_digest,
    )
    task = TaskDefinition(
        task_id=f"task-{revision}",
        revision_id=revision,
        family="fixture",
        schema_id="fixture.task.v1",
        content_digest=canonical_digest({"task": revision}),
    )
    task_set = BenchmarkTaskSet(
        benchmark_id="fixture",
        revision_id=revision,
        source_digest=source_digest,
        task_schema_id="fixture.task.v1",
        tasks=(task,),
    )
    return BenchmarkSourceResolution(source, task_set)


def test_registry_resolves_one_exact_materialized_cut() -> None:
    registration = BenchmarkResolutionRegistration(
        _resolution("r1"),
        canonical_digest({"proof": "r1"}),
    )
    registry = BenchmarkResolutionRegistry((registration,))

    assert registry.benchmark_ids == ("fixture",)
    assert registry.resolve_exact("fixture") == registration
    assert len(registry.identity_digest) == 64


def test_registry_fails_closed_when_benchmark_is_missing() -> None:
    registry = BenchmarkResolutionRegistry()
    with pytest.raises(LookupError, match="no registered materialized cut"):
        registry.resolve_exact("fixture")


def test_registry_fails_closed_when_multiple_exact_cuts_exist() -> None:
    registry = BenchmarkResolutionRegistry(
        (
            BenchmarkResolutionRegistration(
                _resolution("r1"),
                canonical_digest({"proof": "r1"}),
            ),
            BenchmarkResolutionRegistration(
                _resolution("r2"),
                canonical_digest({"proof": "r2"}),
            ),
        )
    )
    with pytest.raises(LookupError, match="ambiguous materialized cuts"):
        registry.resolve_exact("fixture")
