import pytest

from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkCutSpec,
    BenchmarkSourceKind,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    InMemoryBenchmarkSource,
    TaskDefinition,
    TaskSetSplit,
)


SHA = "a" * 64


def source() -> BenchmarkSourceSpec:
    return BenchmarkSourceSpec(
        "benchmark-source",
        BenchmarkSourceKind.CUSTOM,
        "revision-1",
        "adapter://benchmark",
        SHA,
        license="Apache-2.0",
        metadata={"owner": "research"},
    )


def task_set() -> BenchmarkTaskSet:
    return BenchmarkTaskSet(
        "benchmark", "revision-1", SHA, "task.v1",
        (TaskDefinition("task-1", "revision-1", "generic", "task.v1", SHA),),
    )


def test_external_source_resolves_an_immutable_cut() -> None:
    registry = InMemoryBenchmarkSource()
    resolved = registry.register(source(), task_set())

    assert resolved.cut_digest == task_set().cut_digest
    assert registry.resolve(source()) == resolved
    assert resolved.resolution_digest


def test_source_revision_or_content_drift_is_rejected() -> None:
    registry = InMemoryBenchmarkSource()
    with pytest.raises(ValueError, match="content digest"):
        registry.register(BenchmarkSourceSpec(
            "benchmark-source", BenchmarkSourceKind.CUSTOM, "revision-1",
            "adapter://benchmark", "b" * 64,
        ), task_set())
    registry.register(source(), task_set())
    with pytest.raises(KeyError, match="not registered"):
        registry.resolve(BenchmarkSourceSpec(
            "benchmark-source", BenchmarkSourceKind.CUSTOM, "revision-2",
            "adapter://benchmark", SHA,
        ))


def test_benchmark_cut_spec_canonicalizes_author_input_order() -> None:
    spec = BenchmarkCutSpec("benchmark", "revision-1", SHA, "task.v1")
    task_a = TaskDefinition("task-a", "revision-1", "generic", "task.v1", SHA)
    task_b = TaskDefinition("task-b", "revision-1", "generic", "task.v1", "b" * 64)

    left = spec.build(
        (task_b, task_a),
        splits=(
            TaskSetSplit("z", ("task-b",)),
            TaskSetSplit("a", ("task-a",)),
        ),
        selection_policy={"selection": "explicit"},
    )
    right = spec.build(
        (task_a, task_b),
        splits=(
            TaskSetSplit("a", ("task-a",)),
            TaskSetSplit("z", ("task-b",)),
        ),
        selection_policy={"selection": "explicit"},
    )

    assert tuple(row.task_id for row in left.tasks) == ("task-a", "task-b")
    assert tuple(row.split_id for row in left.splits) == ("a", "z")
    assert left == right
    assert left.cut_digest == right.cut_digest


def test_benchmark_cut_spec_keeps_selection_identity_explicit() -> None:
    spec = BenchmarkCutSpec("benchmark", "revision-1", SHA, "task.v1")
    tasks = (TaskDefinition("task-a", "revision-1", "generic", "task.v1", SHA),)

    with pytest.raises(ValueError, match="selection_policy or selection_policy_digest"):
        spec.build(
            tasks,
            selection_policy={"selection": "explicit"},
            selection_policy_digest="c" * 64,
        )
