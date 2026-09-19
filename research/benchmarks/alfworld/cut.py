from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkSourceKind,
    BenchmarkSourceResolution,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)

ALFWORLD_BENCHMARK_ID = "alfworld"
ALFWORLD_TASK_SCHEMA_ID = "alfworld.task.v1"
ALFWORLD_TASK_FAMILIES = (
    "pick_and_place",
    "pick_clean_then_place",
    "pick_heat_then_place",
    "pick_cool_then_place",
    "look_at_obj",
    "pick_two_obj",
)

ALFWORLD_PAPER_EVAL_REVISION = "json_2.1.1"
ALFWORLD_PAPER_EVAL_SPLIT = "eval_out_of_distribution"
ALFWORLD_PAPER_EVAL_DATASET_PATH = "json_2.1.1/valid_unseen"
ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT = 134
ALFWORLD_PAPER_EVAL_SELECTION_POLICY_DIGEST = canonical_digest(
    {
        "benchmark_id": ALFWORLD_BENCHMARK_ID,
        "revision_id": ALFWORLD_PAPER_EVAL_REVISION,
        "split_id": ALFWORLD_PAPER_EVAL_SPLIT,
        "dataset_path": ALFWORLD_PAPER_EVAL_DATASET_PATH,
        "selection": "all_tasks_in_provider_reset_order",
        "expected_task_count": ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT,
    }
)

ALFWORLD_QLASS_DEV_SOURCE_COMMIT = "df8e6a3b840d1ea994114f13fc2d5ccd63b7a8e9"
ALFWORLD_QLASS_DEV_REVISION = f"qlass@{ALFWORLD_QLASS_DEV_SOURCE_COMMIT}:alfworld-dev"
ALFWORLD_QLASS_DEV_LAUNCHER_SPLIT = "dev"
ALFWORLD_QLASS_DEV_SPLIT = "eval_in_distribution"
ALFWORLD_QLASS_DEV_EXPECTED_TASK_COUNT = 140
ALFWORLD_QLASS_DEV_SELECTION_POLICY_DIGEST = canonical_digest(
    {
        "benchmark_id": ALFWORLD_BENCHMARK_ID,
        "revision_id": ALFWORLD_QLASS_DEV_REVISION,
        "launcher_split": ALFWORLD_QLASS_DEV_LAUNCHER_SPLIT,
        "provider_split": ALFWORLD_QLASS_DEV_SPLIT,
        "selection": "all_tasks_in_provider_reset_order",
        "expected_task_count": ALFWORLD_QLASS_DEV_EXPECTED_TASK_COUNT,
        "partitioning": "released_launcher_four_slices_preserve_one_logical_task_set",
    }
)


@dataclass(frozen=True, slots=True)
class AlfworldTaskRecord:
    """One dataset-relative ALFWorld task identity used to materialize a typed cut."""

    gamefile: str
    family: str
    content_digest: str

    def __post_init__(self) -> None:
        if type(self.gamefile) is not str or not self.gamefile.strip():
            raise ValueError("ALFWorld gamefile must be a non-empty dataset-relative path")
        normalized = self.gamefile.replace("\\", "/").strip("/")
        if not normalized or normalized.startswith("../") or "/../" in normalized:
            raise ValueError("ALFWorld gamefile must stay within the frozen dataset cut")
        if type(self.family) is not str or self.family not in ALFWORLD_TASK_FAMILIES:
            raise ValueError("ALFWorld task family is not recognized")
        require_sha256(self.content_digest, "ALFWorld task content_digest")
        object.__setattr__(self, "gamefile", normalized)

    @property
    def task_id(self) -> str:
        return f"alfworld:{self.gamefile}"


def _build_task_set(
    records: tuple[AlfworldTaskRecord, ...],
    *,
    source_digest: str,
    revision_id: str,
    split_id: str,
    expected_task_count: int,
    selection_policy_digest: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or any(type(row) is not AlfworldTaskRecord for row in records):
        raise TypeError("ALFWorld benchmark records must be a tuple of AlfworldTaskRecord")
    if len(records) != expected_task_count:
        raise ValueError(f"ALFWorld cut requires exactly {expected_task_count} tasks")
    require_sha256(source_digest, "ALFWorld benchmark source_digest")
    if set(row.family for row in records) != set(ALFWORLD_TASK_FAMILIES):
        raise ValueError("ALFWorld cut must cover all six task families")

    split_task_ids = tuple(row.task_id for row in records)
    if len(split_task_ids) != len(set(split_task_ids)):
        raise ValueError("ALFWorld benchmark gamefile identities must be unique")

    tasks = tuple(
        sorted(
            (
                TaskDefinition(
                    task_id=row.task_id,
                    revision_id=revision_id,
                    family=row.family,
                    schema_id=ALFWORLD_TASK_SCHEMA_ID,
                    content_digest=row.content_digest,
                    lineage_refs=(f"gamefile:{row.gamefile}",),
                )
                for row in records
            ),
            key=lambda row: row.task_id,
        )
    )
    return BenchmarkTaskSet(
        benchmark_id=ALFWORLD_BENCHMARK_ID,
        revision_id=revision_id,
        source_digest=source_digest,
        task_schema_id=ALFWORLD_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(split_id, split_task_ids),),
        selection_policy_digest=selection_policy_digest,
    )


def build_alfworld_paper_eval_source(*, locator: str, content_digest: str) -> BenchmarkSourceSpec:
    """Bind a materialized ALFWorld json_2.1.1/valid_unseen source cut."""

    if type(locator) is not str or not locator.strip():
        raise ValueError("ALFWorld benchmark source locator must be non-empty")
    require_sha256(content_digest, "ALFWorld benchmark source content_digest")
    return BenchmarkSourceSpec(
        source_id=ALFWORLD_BENCHMARK_ID,
        kind=BenchmarkSourceKind.LOCAL_FILE,
        revision_id=ALFWORLD_PAPER_EVAL_REVISION,
        locator=locator,
        content_digest=content_digest,
        metadata={
            "dataset_path": ALFWORLD_PAPER_EVAL_DATASET_PATH,
            "paper_environment_split": ALFWORLD_PAPER_EVAL_SPLIT,
            "expected_task_count": str(ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT),
        },
    )


def build_alfworld_paper_eval_task_set(
    records: tuple[AlfworldTaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    """Materialize the shared ReAct/Reflexion OOD evaluation cut."""

    return _build_task_set(
        records,
        source_digest=source_digest,
        revision_id=ALFWORLD_PAPER_EVAL_REVISION,
        split_id=ALFWORLD_PAPER_EVAL_SPLIT,
        expected_task_count=ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT,
        selection_policy_digest=ALFWORLD_PAPER_EVAL_SELECTION_POLICY_DIGEST,
    )


def build_alfworld_qlass_dev_task_set(
    records: tuple[AlfworldTaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    """Materialize QLASS later-released ALFWorld dev/eval-in-distribution cut.

    The released launcher uses split dev. Its source-bound task loader maps that
    author-facing split to ALFWorld eval_in_distribution with 140 tasks. Four
    launcher slices are execution partitioning, not four benchmark cuts.
    """

    return _build_task_set(
        records,
        source_digest=source_digest,
        revision_id=ALFWORLD_QLASS_DEV_REVISION,
        split_id=ALFWORLD_QLASS_DEV_SPLIT,
        expected_task_count=ALFWORLD_QLASS_DEV_EXPECTED_TASK_COUNT,
        selection_policy_digest=ALFWORLD_QLASS_DEV_SELECTION_POLICY_DIGEST,
    )


def bind_alfworld_paper_eval_cut(
    records: tuple[AlfworldTaskRecord, ...],
    *,
    locator: str,
    source_digest: str,
) -> BenchmarkSourceResolution:
    source = build_alfworld_paper_eval_source(locator=locator, content_digest=source_digest)
    task_set = build_alfworld_paper_eval_task_set(records, source_digest=source_digest)
    return BenchmarkSourceResolution(source=source, task_set=task_set)


__all__ = [
    "ALFWORLD_BENCHMARK_ID",
    "ALFWORLD_PAPER_EVAL_DATASET_PATH",
    "ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT",
    "ALFWORLD_PAPER_EVAL_REVISION",
    "ALFWORLD_PAPER_EVAL_SELECTION_POLICY_DIGEST",
    "ALFWORLD_PAPER_EVAL_SPLIT",
    "ALFWORLD_QLASS_DEV_EXPECTED_TASK_COUNT",
    "ALFWORLD_QLASS_DEV_LAUNCHER_SPLIT",
    "ALFWORLD_QLASS_DEV_REVISION",
    "ALFWORLD_QLASS_DEV_SELECTION_POLICY_DIGEST",
    "ALFWORLD_QLASS_DEV_SOURCE_COMMIT",
    "ALFWORLD_QLASS_DEV_SPLIT",
    "ALFWORLD_TASK_FAMILIES",
    "ALFWORLD_TASK_SCHEMA_ID",
    "AlfworldTaskRecord",
    "bind_alfworld_paper_eval_cut",
    "build_alfworld_paper_eval_source",
    "build_alfworld_paper_eval_task_set",
    "build_alfworld_qlass_dev_task_set",
]
