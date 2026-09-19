from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkSourceKind,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskPackageSpec,
    TaskSetSplit,
    TaskVerifierIsolation,
)

MGSM_BENCHMARK_ID = "mgsm"
MGSM_DATASET_LOCATOR = "https://huggingface.co/datasets/juletxara/mgsm"
MGSM_ADAS_SOURCE_COMMIT = "2702bee8fefda42255efc5be9f60e3bd3db96ae4"
MGSM_TASK_SCHEMA_ID = "mgsm.multilingual-math-task.v1"
MGSM_LANGUAGES = ("bn", "de", "en", "es", "fr", "ja", "ru", "sw", "te", "th", "zh")
MGSM_TASKS_PER_LANGUAGE = 250
MGSM_TOTAL_TASK_COUNT = len(MGSM_LANGUAGES) * MGSM_TASKS_PER_LANGUAGE
MGSM_ADAS_VALID_SPLIT = "adas_search_valid_128"
MGSM_ADAS_TEST_SPLIT = "adas_search_test_800"
MGSM_ADAS_VALID_SIZE = 128
MGSM_ADAS_TEST_SIZE = 800
MGSM_ADAS_SHUFFLE_SEED = 0


@dataclass(frozen=True, slots=True, order=True)
class MGSMTaskRecord:
    language: str
    index: int
    question: str
    answer: str
    content_digest: str

    def __post_init__(self) -> None:
        if self.language not in MGSM_LANGUAGES:
            raise ValueError(f"unsupported MGSM language: {self.language!r}")
        if type(self.index) is not int or not 0 <= self.index < MGSM_TASKS_PER_LANGUAGE:
            raise ValueError("MGSM index must be in [0, 250)")
        if type(self.question) is not str or not self.question.strip():
            raise ValueError("MGSM question must be non-empty")
        if type(self.answer) is not str or not self.answer.strip():
            raise ValueError("MGSM answer must be non-empty")
        require_sha256(self.content_digest, "MGSM task content_digest")

    @property
    def task_id(self) -> str:
        return f"mgsm:{self.language}:{self.index:03d}"


def mgsm_adas_revision(dataset_revision: str) -> str:
    if type(dataset_revision) is not str or not dataset_revision.strip():
        raise ValueError("MGSM dataset_revision must be non-empty")
    return (
        f"mgsm@dataset:{dataset_revision.strip()}:"
        f"adas:{MGSM_ADAS_SOURCE_COMMIT}"
    )


def build_mgsm_source(
    *,
    dataset_revision: str,
    dataset_content_sha256: str,
) -> BenchmarkSourceSpec:
    require_sha256(dataset_content_sha256, "MGSM dataset_content_sha256")
    return BenchmarkSourceSpec(
        source_id=MGSM_BENCHMARK_ID,
        kind=BenchmarkSourceKind.HUGGINGFACE,
        revision_id=mgsm_adas_revision(dataset_revision),
        locator=MGSM_DATASET_LOCATOR,
        content_digest=dataset_content_sha256,
        metadata={
            "paper_task_count": str(MGSM_TOTAL_TASK_COUNT),
            "languages": ",".join(MGSM_LANGUAGES),
            "adas_source_commit": MGSM_ADAS_SOURCE_COMMIT,
            "adas_shuffle_seed": str(MGSM_ADAS_SHUFFLE_SEED),
        },
    )


def build_mgsm_adas_task_set(
    records: tuple[MGSMTaskRecord, ...],
    *,
    dataset_revision: str,
    dataset_content_sha256: str,
    paper_shuffle_task_ids: tuple[str, ...],
) -> BenchmarkTaskSet:
    """Freeze the MGSM cut and exact ADAS search/evaluation permutation.

    The caller supplies the task order emitted by the paper-era seeded shuffle.
    This avoids silently depending on the host Python version's shuffle
    implementation. The exact order becomes part of the selection-policy digest.
    """

    if type(records) is not tuple or any(type(row) is not MGSMTaskRecord for row in records):
        raise TypeError("MGSM records must be a tuple of MGSMTaskRecord")
    require_sha256(dataset_content_sha256, "MGSM dataset_content_sha256")

    by_key = {(row.language, row.index): row for row in records}
    expected = {
        (language, index)
        for language in MGSM_LANGUAGES
        for index in range(MGSM_TASKS_PER_LANGUAGE)
    }
    if len(records) != MGSM_TOTAL_TASK_COUNT or set(by_key) != expected:
        raise ValueError("MGSM matched cut requires exactly 250 tasks for each of 11 languages")

    canonical_rows = tuple(
        by_key[(language, index)]
        for language in MGSM_LANGUAGES
        for index in range(MGSM_TASKS_PER_LANGUAGE)
    )
    canonical_ids = tuple(row.task_id for row in canonical_rows)
    if (
        type(paper_shuffle_task_ids) is not tuple
        or len(paper_shuffle_task_ids) != MGSM_TOTAL_TASK_COUNT
        or len(set(paper_shuffle_task_ids)) != MGSM_TOTAL_TASK_COUNT
        or set(paper_shuffle_task_ids) != set(canonical_ids)
    ):
        raise ValueError("MGSM paper shuffle ids must be an exact task permutation")

    revision = mgsm_adas_revision(dataset_revision)
    tasks = tuple(
        sorted(
            (
                TaskDefinition(
                    task_id=row.task_id,
                    revision_id=revision,
                    family=row.language,
                    schema_id=MGSM_TASK_SCHEMA_ID,
                    content_digest=row.content_digest,
                    lineage_refs=(
                        f"language:{row.language}",
                        f"source-index:{row.index}",
                    ),
                    package=TaskPackageSpec(
                        package_schema_id="mgsm.numeric-answer-package.v1",
                        instruction_digest=row.content_digest,
                        verifier_requirement_id="benchmark.mgsm.numeric-answer.verifier",
                        verifier_isolation=TaskVerifierIsolation.SEPARATE,
                    ),
                )
                for row in canonical_rows
            ),
            key=lambda row: row.task_id,
        )
    )
    valid_ids = paper_shuffle_task_ids[:MGSM_ADAS_VALID_SIZE]
    test_start = MGSM_ADAS_VALID_SIZE
    test_ids = paper_shuffle_task_ids[
        test_start : test_start + MGSM_ADAS_TEST_SIZE
    ]
    return BenchmarkTaskSet(
        benchmark_id=MGSM_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id=MGSM_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(
            TaskSetSplit(MGSM_ADAS_TEST_SPLIT, test_ids),
            TaskSetSplit(MGSM_ADAS_VALID_SPLIT, valid_ids),
        ),
        selection_policy_digest=canonical_digest(
            {
                "source_order_languages": MGSM_LANGUAGES,
                "tasks_per_language": MGSM_TASKS_PER_LANGUAGE,
                "shuffle_seed": MGSM_ADAS_SHUFFLE_SEED,
                "paper_shuffle_task_ids": paper_shuffle_task_ids,
                "valid_size": MGSM_ADAS_VALID_SIZE,
                "test_size": MGSM_ADAS_TEST_SIZE,
                "source_commit": MGSM_ADAS_SOURCE_COMMIT,
            }
        ),
    )


__all__ = [
    "MGSM_ADAS_SHUFFLE_SEED",
    "MGSM_ADAS_SOURCE_COMMIT",
    "MGSM_ADAS_TEST_SIZE",
    "MGSM_ADAS_TEST_SPLIT",
    "MGSM_ADAS_VALID_SIZE",
    "MGSM_ADAS_VALID_SPLIT",
    "MGSM_BENCHMARK_ID",
    "MGSM_DATASET_LOCATOR",
    "MGSM_LANGUAGES",
    "MGSM_TASKS_PER_LANGUAGE",
    "MGSM_TASK_SCHEMA_ID",
    "MGSM_TOTAL_TASK_COUNT",
    "MGSMTaskRecord",
    "build_mgsm_adas_task_set",
    "build_mgsm_source",
    "mgsm_adas_revision",
]
