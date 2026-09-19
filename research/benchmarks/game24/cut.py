from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)

GAME24_BENCHMARK_ID = "game24"
GAME24_PAPER_REVISION = "tree-of-thought-llm@8050e67d"
GAME24_PAPER_SPLIT = "paper_eval_900_999"
GAME24_TASK_SCHEMA_ID = "game24.puzzle.v1"
GAME24_PAPER_START_INDEX = 900
GAME24_PAPER_END_INDEX = 1000
GAME24_PAPER_TASK_COUNT = GAME24_PAPER_END_INDEX - GAME24_PAPER_START_INDEX
GAME24_SELECTION_POLICY_DIGEST = canonical_digest(
    {
        "benchmark_id": GAME24_BENCHMARK_ID,
        "revision": GAME24_PAPER_REVISION,
        "source_artifact": "src/tot/data/24/24.csv",
        "start_index": GAME24_PAPER_START_INDEX,
        "end_index_exclusive": GAME24_PAPER_END_INDEX,
        "selection": "contiguous_csv_index_range",
    }
)


@dataclass(frozen=True, slots=True)
class Game24TaskRecord:
    index: int
    puzzle: str
    content_digest: str

    def __post_init__(self) -> None:
        if type(self.index) is not int or not GAME24_PAPER_START_INDEX <= self.index < GAME24_PAPER_END_INDEX:
            raise ValueError("Game24 paper task index must be in [900, 1000)")
        if type(self.puzzle) is not str or not self.puzzle.strip():
            raise ValueError("Game24 puzzle must be non-empty")
        require_sha256(self.content_digest, "Game24 task content_digest")

    @property
    def task_id(self) -> str:
        return f"game24:{self.index:04d}"


def build_game24_paper_task_set(
    records: tuple[Game24TaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    """Freeze the exact 100-puzzle ToT Game24 evaluation range."""

    if type(records) is not tuple or any(type(row) is not Game24TaskRecord for row in records):
        raise TypeError("Game24 records must be a tuple of Game24TaskRecord")
    require_sha256(source_digest, "Game24 source_digest")
    expected_indices = tuple(range(GAME24_PAPER_START_INDEX, GAME24_PAPER_END_INDEX))
    by_index = {row.index: row for row in records}
    if len(records) != GAME24_PAPER_TASK_COUNT or tuple(sorted(by_index)) != expected_indices:
        raise ValueError("ToT Game24 matched cut requires exactly indices 900 through 999")

    ordered = tuple(by_index[index] for index in expected_indices)
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=GAME24_PAPER_REVISION,
            family="game24",
            schema_id=GAME24_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(f"csv-index:{row.index}",),
        )
        for row in ordered
    )
    return BenchmarkTaskSet(
        benchmark_id=GAME24_BENCHMARK_ID,
        revision_id=GAME24_PAPER_REVISION,
        source_digest=source_digest,
        task_schema_id=GAME24_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(GAME24_PAPER_SPLIT, tuple(row.task_id for row in ordered)),),
        selection_policy_digest=GAME24_SELECTION_POLICY_DIGEST,
    )


__all__ = [
    "GAME24_BENCHMARK_ID",
    "GAME24_PAPER_END_INDEX",
    "GAME24_PAPER_REVISION",
    "GAME24_PAPER_SPLIT",
    "GAME24_PAPER_START_INDEX",
    "GAME24_PAPER_TASK_COUNT",
    "GAME24_SELECTION_POLICY_DIGEST",
    "GAME24_TASK_SCHEMA_ID",
    "Game24TaskRecord",
    "build_game24_paper_task_set",
]
