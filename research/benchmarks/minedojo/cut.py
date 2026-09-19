from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    require_sha256,
)
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkSourceKind,
    BenchmarkSourceResolution,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskPackageSpec,
    TaskSetSplit,
    TaskVerifierIsolation,
)

from .authority import (
    MINEDOJO_AUDITED_COMMIT,
    MINEDOJO_BENCHMARK_TASK_COUNT,
    MINEDOJO_CREATIVE_TASK_COUNT,
    MINEDOJO_PLAYTHROUGH_TASK_COUNT,
    MINEDOJO_PROGRAMMATIC_FAMILIES,
    MINEDOJO_PROGRAMMATIC_SUCCESS_AGGREGATION,
    MINEDOJO_PROGRAMMATIC_TASK_COUNT,
    MINEDOJO_TASK_CATEGORIES,
)


MINEDOJO_BENCHMARK_ID = "minedojo"
MINEDOJO_TASK_SCHEMA_ID = "minedojo.task.v1"
MINEDOJO_REVISION_ID = (
    f"minedojo@{MINEDOJO_AUDITED_COMMIT}:paper-consistent-suite"
)
MINEDOJO_ALL_SPLIT = "all"
MINEDOJO_REPOSITORY = "https://github.com/MineDojo/MineDojo"


@dataclass(frozen=True, slots=True, order=True)
class MineDojoTaskRecord:
    """One immutable task declaration from the paper-consistent MineDojo suite."""

    task_id: str
    category: str
    family: str
    prompt: str
    content_digest: str
    guidance_digest: str | None = None

    def __post_init__(self) -> None:
        if type(self.task_id) is not str or not self.task_id.strip():
            raise ValueError("MineDojo task_id must be non-empty")
        if self.category not in MINEDOJO_TASK_CATEGORIES:
            raise ValueError("MineDojo task category is invalid")
        if type(self.family) is not str or not self.family.strip():
            raise ValueError("MineDojo task family must be non-empty")
        if self.category == "programmatic":
            if self.family not in MINEDOJO_PROGRAMMATIC_FAMILIES:
                raise ValueError(
                    "MineDojo programmatic task family is invalid"
                )
        elif self.family != self.category:
            raise ValueError(
                "MineDojo creative/playthrough family must equal category"
            )
        if type(self.prompt) is not str or not self.prompt.strip():
            raise ValueError("MineDojo task prompt must be non-empty")
        require_sha256(
            self.content_digest,
            "MineDojo task content_digest",
        )
        if self.guidance_digest is not None:
            require_sha256(
                self.guidance_digest,
                "MineDojo task guidance_digest",
            )


def minedojo_selection_policy_digest(
    records: tuple[MineDojoTaskRecord, ...],
) -> str:
    return canonical_digest({
        "benchmark_id": MINEDOJO_BENCHMARK_ID,
        "revision_id": MINEDOJO_REVISION_ID,
        "source_commit": MINEDOJO_AUDITED_COMMIT,
        "selection": "all-paper-consistent-suite-tasks",
        "task_ids": tuple(row.task_id for row in records),
        "task_content_digests": tuple(
            row.content_digest for row in records
        ),
        "success_aggregation": (
            MINEDOJO_PROGRAMMATIC_SUCCESS_AGGREGATION
        ),
    })


def build_minedojo_source(
    *,
    content_digest: str,
) -> BenchmarkSourceSpec:
    require_sha256(content_digest, "MineDojo source content_digest")
    return BenchmarkSourceSpec(
        source_id=MINEDOJO_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=MINEDOJO_REVISION_ID,
        locator=MINEDOJO_REPOSITORY,
        content_digest=content_digest,
        metadata={
            "commit": MINEDOJO_AUDITED_COMMIT,
            "task_count": str(
                MINEDOJO_BENCHMARK_TASK_COUNT
            ),
            "programmatic_task_count": str(
                MINEDOJO_PROGRAMMATIC_TASK_COUNT
            ),
            "creative_task_count": str(
                MINEDOJO_CREATIVE_TASK_COUNT
            ),
            "playthrough_task_count": str(
                MINEDOJO_PLAYTHROUGH_TASK_COUNT
            ),
            "programmatic_success_aggregation": "any",
        },
    )


def _package(row: MineDojoTaskRecord) -> TaskPackageSpec:
    if row.category == "creative":
        verifier_requirement_id = None
    elif row.category == "playthrough":
        verifier_requirement_id = (
            "benchmark.minedojo.playthrough-state.verifier"
        )
    else:
        verifier_requirement_id = (
            "benchmark.minedojo.programmatic-state.verifier"
        )

    return TaskPackageSpec(
        package_schema_id="minedojo.minecraft-task-package.v1",
        instruction_digest=row.content_digest,
        environment_requirement_id=(
            "benchmark.minedojo.minecraft-paper-environment"
        ),
        verifier_requirement_id=verifier_requirement_id,
        verifier_isolation=TaskVerifierIsolation.SEPARATE,
    )


def build_minedojo_task_set(
    records: tuple[MineDojoTaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    """Materialize the complete paper-consistent 3,142-task benchmark cut."""

    if type(records) is not tuple or any(
        type(row) is not MineDojoTaskRecord for row in records
    ):
        raise TypeError(
            "MineDojo records must be a tuple of MineDojoTaskRecord"
        )
    expected = MINEDOJO_BENCHMARK_TASK_COUNT
    if len(records) != expected:
        raise ValueError(
            f"MineDojo cut requires exactly {expected} tasks"
        )
    require_sha256(source_digest, "MineDojo benchmark source_digest")

    ordered = tuple(sorted(records, key=lambda row: row.task_id))
    task_ids = tuple(row.task_id for row in ordered)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("MineDojo task ids must be unique")

    counts = Counter(row.category for row in ordered)
    expected_counts = {
        "programmatic": (
            MINEDOJO_PROGRAMMATIC_TASK_COUNT
        ),
        "creative": MINEDOJO_CREATIVE_TASK_COUNT,
        "playthrough": MINEDOJO_PLAYTHROUGH_TASK_COUNT,
    }
    if dict(counts) != expected_counts:
        raise ValueError(
            "MineDojo category counts do not match paper-consistent cut"
        )

    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=MINEDOJO_REVISION_ID,
            family=row.family,
            schema_id=MINEDOJO_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=tuple(
                item
                for item in (
                    f"category:{row.category}",
                    f"family:{row.family}",
                    (
                        None
                        if row.guidance_digest is None
                        else f"guidance:{row.guidance_digest}"
                    ),
                )
                if item is not None
            ),
            package=_package(row),
        )
        for row in ordered
    )

    splits = (
        TaskSetSplit(MINEDOJO_ALL_SPLIT, task_ids),
        *tuple(
            TaskSetSplit(
                f"category:{category}",
                tuple(
                    row.task_id
                    for row in ordered
                    if row.category == category
                ),
            )
            for category in sorted(MINEDOJO_TASK_CATEGORIES)
        ),
    )

    return BenchmarkTaskSet(
        benchmark_id=MINEDOJO_BENCHMARK_ID,
        revision_id=MINEDOJO_REVISION_ID,
        source_digest=source_digest,
        task_schema_id=MINEDOJO_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=splits,
        selection_policy_digest=minedojo_selection_policy_digest(
            ordered
        ),
    )


def bind_minedojo_cut(
    records: tuple[MineDojoTaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkSourceResolution:
    return BenchmarkSourceResolution(
        source=build_minedojo_source(content_digest=source_digest),
        task_set=build_minedojo_task_set(
            records,
            source_digest=source_digest,
        ),
    )


__all__ = [
    "MINEDOJO_ALL_SPLIT",
    "MINEDOJO_BENCHMARK_ID",
    "MINEDOJO_REPOSITORY",
    "MINEDOJO_REVISION_ID",
    "MINEDOJO_TASK_SCHEMA_ID",
    "MineDojoTaskRecord",
    "bind_minedojo_cut",
    "build_minedojo_source",
    "build_minedojo_task_set",
    "minedojo_selection_policy_digest",
]
