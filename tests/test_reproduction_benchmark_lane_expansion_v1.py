from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)

from research.reproductions.adaptagent_acl2025.definition import REPRODUCTION
from research.reproductions.research_os import (
    ReproductionResearchOSCompileError,
    expand_reproduction_benchmark_lanes,
    materialize_reproduction_study,
)


def _task(task_id: str) -> TaskDefinition:
    return TaskDefinition(
        task_id,
        "mind2web.paper-cut",
        "web-navigation",
        "mind2web.task.v1",
        canonical_digest({"task_id": task_id}),
    )


def _benchmark(*, with_splits: bool = True) -> BenchmarkTaskSet:
    tasks = (_task("task-a"), _task("task-b"))
    return BenchmarkTaskSet(
        benchmark_id="mind2web",
        revision_id="paper-cut",
        source_digest=canonical_digest({"benchmark": "mind2web", "revision": "paper-cut"}),
        task_schema_id="mind2web.task.v1",
        tasks=tasks,
        splits=(
            (
                TaskSetSplit("dev", ("task-a",)),
                TaskSetSplit("test", ("task-b",)),
            )
            if with_splits
            else ()
        ),
    )


def test_platform_expands_benchmark_splits_into_exact_reproduction_lanes() -> None:
    benchmark = _benchmark()
    bindings = expand_reproduction_benchmark_lanes(
        REPRODUCTION,
        study_factory="build_adaptagent_study",
        benchmark=benchmark,
        values={},
    )

    assert tuple(row.benchmark_split_id for row in bindings) == ("dev", "test")
    assert len({row.binding_id for row in bindings}) == 2
    assert len({row.binding_digest for row in bindings}) == 2
    assert all(row.values == {} for row in bindings)
    assert all(row.requirement_digests == () for row in bindings)

    studies = tuple(
        materialize_reproduction_study(REPRODUCTION, binding, benchmark)
        for binding in bindings
    )
    assert tuple(row.benchmark_split_id for row in studies) == ("dev", "test")
    assert tuple(row.benchmark.cut_digest for row in studies) == (
        benchmark.cut_digest,
        benchmark.cut_digest,
    )


def test_split_aware_reproduction_fails_closed_without_benchmark_split_authority() -> None:
    with pytest.raises(
        ReproductionResearchOSCompileError,
        match="without declared TaskSetSplit",
    ):
        expand_reproduction_benchmark_lanes(
            REPRODUCTION,
            study_factory="build_adaptagent_study",
            benchmark=_benchmark(with_splits=False),
            values={},
        )
