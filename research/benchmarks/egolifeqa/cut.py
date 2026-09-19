from __future__ import annotations

from dataclasses import dataclass, field

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


EGOLIFEQA_BENCHMARK_ID = "egolifeqa"
EGOLIFEQA_SOURCE_URI = (
    "https://huggingface.co/datasets/lmms-lab/EgoLife"
)
EGOLIFEQA_PAPER_URI = (
    "https://openaccess.thecvf.com/content/CVPR2025/html/"
    "Yang_EgoLife_Towards_Egocentric_Life_Assistant_"
    "CVPR_2025_paper.html"
)
EGOLIFEQA_SCHEMA_ID = "egolifeqa.long-context-life-mcq.v1"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True, order=True)
class EgoLifeQATaskRecord:
    subject_id: str
    question_id: str
    query_type: str
    question: str
    choices: tuple[tuple[str, str], ...]
    answer_label: str
    query_time: int
    target_time_ranges: tuple[tuple[int, int], ...] = ()
    record_digest: str = field(init=False, compare=False)

    def __post_init__(self) -> None:
        for name in (
            "subject_id",
            "question_id",
            "query_type",
            "question",
            "answer_label",
        ):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), f"EgoLifeQA {name}"),
            )
        if type(self.choices) is not tuple or not 2 <= len(self.choices) <= 8:
            raise ValueError(
                "EgoLifeQA choices must contain 2-8 labeled choices"
            )
        labels: list[str] = []
        for row in self.choices:
            if type(row) is not tuple or len(row) != 2:
                raise TypeError(
                    "EgoLifeQA choices must be (label, text) tuples"
                )
            label = _text(row[0], "EgoLifeQA choice label")
            _text(row[1], "EgoLifeQA choice text")
            labels.append(label)
        if len(labels) != len(set(labels)):
            raise ValueError("EgoLifeQA choice labels must be unique")
        if self.answer_label not in set(labels):
            raise ValueError(
                "EgoLifeQA answer_label must identify one choice"
            )
        if type(self.query_time) is not int or self.query_time < 1:
            raise ValueError("EgoLifeQA query_time must be positive")
        if type(self.target_time_ranges) is not tuple:
            raise TypeError(
                "EgoLifeQA target_time_ranges must be a tuple"
            )
        for row in self.target_time_ranges:
            if (
                type(row) is not tuple
                or len(row) != 2
                or type(row[0]) is not int
                or type(row[1]) is not int
                or row[0] < 1
                or row[1] < row[0]
            ):
                raise ValueError(
                    "EgoLifeQA target ranges must be positive ordered pairs"
                )
        object.__setattr__(
            self,
            "record_digest",
            canonical_digest({
                "subject_id": self.subject_id,
                "question_id": self.question_id,
                "query_type": self.query_type,
                "question": self.question,
                "choices": self.choices,
                "answer_label": self.answer_label,
                "query_time": self.query_time,
                "target_time_ranges": self.target_time_ranges,
            }),
        )


def build_egolifeqa_source(
    *,
    question_file_content_sha256: str,
    subject_id: str,
) -> BenchmarkSourceSpec:
    digest = require_sha256(
        question_file_content_sha256,
        "EgoLifeQA question file content digest",
    )
    subject_id = _text(subject_id, "EgoLifeQA subject_id")
    return BenchmarkSourceSpec(
        source_id=EGOLIFEQA_BENCHMARK_ID,
        kind=BenchmarkSourceKind.HTTP,
        revision_id=f"egolifeqa:{subject_id}:{digest}",
        locator=EGOLIFEQA_SOURCE_URI,
        content_digest=digest,
        metadata={
            "subject_id": subject_id,
            "paper": EGOLIFEQA_PAPER_URI,
            "source_file": f"EgoLifeQA/EgoLifeQA_{subject_id}.json",
            "publication": "CVPR 2025",
            "answer_format": "multiple-choice",
        },
    )


def bind_egolifeqa_subject_cut(
    records: tuple[EgoLifeQATaskRecord, ...],
    *,
    question_file_content_sha256: str,
    subject_id: str,
) -> BenchmarkSourceResolution:
    if type(records) is not tuple or any(
        not isinstance(row, EgoLifeQATaskRecord) for row in records
    ):
        raise TypeError(
            "EgoLifeQA records must be EgoLifeQATaskRecord tuple"
        )
    if not records:
        raise ValueError("EgoLifeQA subject cut requires records")
    subject_id = _text(subject_id, "EgoLifeQA subject_id")
    if any(row.subject_id != subject_id for row in records):
        raise ValueError(
            "EgoLifeQA subject cut cannot mix participant identities"
        )
    ordered = tuple(
        sorted(records, key=lambda row: row.question_id)
    )
    ids = tuple(row.question_id for row in ordered)
    if len(ids) != len(set(ids)):
        raise ValueError(
            "EgoLifeQA question IDs must be unique within subject"
        )
    source = build_egolifeqa_source(
        question_file_content_sha256=(
            question_file_content_sha256
        ),
        subject_id=subject_id,
    )
    revision = source.revision_id
    tasks: list[TaskDefinition] = []
    for row in ordered:
        task_digest = canonical_digest({
            "benchmark_source_digest": source.content_digest,
            "record_digest": row.record_digest,
            "evaluation": "worldmm-compatible-multiple-choice",
        })
        tasks.append(
            TaskDefinition(
                task_id=(
                    f"egolifeqa:{subject_id}:{row.question_id}"
                ),
                revision_id=revision,
                family=f"egolifeqa_{row.query_type}",
                schema_id=EGOLIFEQA_SCHEMA_ID,
                content_digest=task_digest,
                lineage_refs=(
                    f"subject:{subject_id}",
                    f"question-id:{row.question_id}",
                    f"query-type:{row.query_type}",
                    f"query-time:{row.query_time}",
                    (
                        "target-time-ranges:"
                        f"{canonical_digest(row.target_time_ranges)}"
                    ),
                    (
                        "choices:"
                        f"{canonical_digest(row.choices)}"
                    ),
                    f"answer-label:{row.answer_label}",
                ),
                package=TaskPackageSpec(
                    package_schema_id=(
                        "egolifeqa.long-context-life-mcq-package.v1"
                    ),
                    instruction_digest=task_digest,
                    environment_requirement_id=(
                        "benchmark.egolife.long-context-multimodal"
                    ),
                    verifier_requirement_id=(
                        "benchmark.egolifeqa.choice-answer"
                    ),
                    verifier_isolation=TaskVerifierIsolation.SEPARATE,
                ),
            )
        )
    task_ids = tuple(task.task_id for task in tasks)
    split_id = f"subject:{subject_id}"
    task_set = BenchmarkTaskSet(
        benchmark_id=EGOLIFEQA_BENCHMARK_ID,
        revision_id=revision,
        source_digest=source.content_digest,
        task_schema_id=EGOLIFEQA_SCHEMA_ID,
        tasks=tuple(tasks),
        splits=(
            TaskSetSplit("all", task_ids),
            TaskSetSplit(split_id, task_ids),
        ),
        selection_policy_digest=canonical_digest({
            "benchmark_id": EGOLIFEQA_BENCHMARK_ID,
            "subject_id": subject_id,
            "source_digest": source.content_digest,
            "record_digests": tuple(
                row.record_digest for row in ordered
            ),
            "task_ids": task_ids,
            "count_is_content_derived": True,
        }),
    )
    return BenchmarkSourceResolution(
        source=source,
        task_set=task_set,
    )


__all__ = [
    "EGOLIFEQA_BENCHMARK_ID",
    "EGOLIFEQA_PAPER_URI",
    "EGOLIFEQA_SCHEMA_ID",
    "EGOLIFEQA_SOURCE_URI",
    "EgoLifeQATaskRecord",
    "bind_egolifeqa_subject_cut",
    "build_egolifeqa_source",
]
