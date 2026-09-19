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


EGOSCHEMA_BENCHMARK_ID = "egoschema"
EGOSCHEMA_SOURCE_REPOSITORY = "https://github.com/egoschema/EgoSchema"
EGOSCHEMA_SOURCE_COMMIT = "505c787376b5e066d0ae406d0e0d41245cebba15"
EGOSCHEMA_PUBLIC_SPLIT = "public-500"
EGOSCHEMA_FULL_SPLIT = "full-5031"
EGOSCHEMA_PUBLIC_COUNT = 500
EGOSCHEMA_FULL_COUNT = 5031
EGOSCHEMA_SCHEMA_ID = "egoschema.long-form-video-mcq.v1"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True, order=True)
class EgoSchemaTaskRecord:
    q_uid: str
    question: str
    options: tuple[str, ...]
    video_content_sha256: str
    answer_index: int | None = None
    record_digest: str = field(init=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "q_uid",
            _text(self.q_uid, "EgoSchema q_uid"),
        )
        object.__setattr__(
            self,
            "question",
            _text(self.question, "EgoSchema question"),
        )
        if type(self.options) is not tuple or len(self.options) != 5:
            raise ValueError("EgoSchema requires exactly five answer options")
        if any(type(value) is not str or not value.strip() for value in self.options):
            raise ValueError("EgoSchema options must be non-empty text")
        if len(set(self.options)) != len(self.options):
            raise ValueError("EgoSchema options must be distinct")
        object.__setattr__(
            self,
            "video_content_sha256",
            require_sha256(
                self.video_content_sha256,
                "EgoSchema video_content_sha256",
            ),
        )
        if self.answer_index is not None and (
            type(self.answer_index) is not int
            or not 0 <= self.answer_index <= 4
        ):
            raise ValueError("EgoSchema answer_index must be in [0, 4]")
        object.__setattr__(
            self,
            "record_digest",
            canonical_digest({
                "q_uid": self.q_uid,
                "question": self.question,
                "options": self.options,
                "video_content_sha256": self.video_content_sha256,
                "answer_index": self.answer_index,
            }),
        )


def build_egoschema_source(
    *,
    split_id: str,
    questions_content_sha256: str,
    public_answers_content_sha256: str,
) -> BenchmarkSourceSpec:
    questions = require_sha256(
        questions_content_sha256,
        "EgoSchema questions content digest",
    )
    answers = require_sha256(
        public_answers_content_sha256,
        "EgoSchema public answers content digest",
    )
    if split_id not in {EGOSCHEMA_PUBLIC_SPLIT, EGOSCHEMA_FULL_SPLIT}:
        raise ValueError("unsupported EgoSchema resolved split")
    content_digest = canonical_digest({
        "repository": EGOSCHEMA_SOURCE_REPOSITORY,
        "commit": EGOSCHEMA_SOURCE_COMMIT,
        "questions_content_sha256": questions,
        "public_answers_content_sha256": answers,
    })
    return BenchmarkSourceSpec(
        source_id=EGOSCHEMA_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=(
            f"{EGOSCHEMA_SOURCE_COMMIT}:{split_id}:"
            f"{content_digest}"
        ),
        locator=EGOSCHEMA_SOURCE_REPOSITORY,
        content_digest=content_digest,
        metadata={
            "question_count": str(EGOSCHEMA_FULL_COUNT),
            "public_answer_count": str(EGOSCHEMA_PUBLIC_COUNT),
            "answer_choices_per_question": "5",
            "evaluation": "zero-shot-multiple-choice",
            "full_evaluation": "official-server-or-kaggle",
            "resolved_split": split_id,
        },
    )


def _build_cut(
    records: tuple[EgoSchemaTaskRecord, ...],
    *,
    split_id: str,
    expected_count: int,
    require_public_answers: bool,
    questions_content_sha256: str,
    public_answers_content_sha256: str,
) -> BenchmarkSourceResolution:
    if type(records) is not tuple or any(
        not isinstance(row, EgoSchemaTaskRecord) for row in records
    ):
        raise TypeError("EgoSchema records must be EgoSchemaTaskRecord tuple")
    if len(records) != expected_count:
        raise ValueError(
            f"EgoSchema {split_id} requires exactly {expected_count} tasks"
        )
    if require_public_answers and any(
        row.answer_index is None for row in records
    ):
        raise ValueError(
            "EgoSchema public-500 cut requires public answer indices"
        )
    ordered = tuple(sorted(records, key=lambda row: row.q_uid))
    ids = tuple(row.q_uid for row in ordered)
    if len(ids) != len(set(ids)):
        raise ValueError("EgoSchema q_uid values must be unique")

    source = build_egoschema_source(
        split_id=split_id,
        questions_content_sha256=questions_content_sha256,
        public_answers_content_sha256=public_answers_content_sha256,
    )
    revision = source.revision_id
    tasks: list[TaskDefinition] = []
    for row in ordered:
        task_digest = canonical_digest({
            "benchmark_source_digest": source.content_digest,
            "split_id": split_id,
            "record_digest": row.record_digest,
            "zero_shot": True,
        })
        tasks.append(
            TaskDefinition(
                task_id=f"egoschema:{split_id}:{row.q_uid}",
                revision_id=revision,
                family="long_form_video_multiple_choice_qa",
                schema_id=EGOSCHEMA_SCHEMA_ID,
                content_digest=task_digest,
                lineage_refs=(
                    f"q_uid:{row.q_uid}",
                    f"video-sha256:{row.video_content_sha256}",
                    "choice-count:5",
                    "evaluation:zero-shot",
                    (
                        "answers:public"
                        if row.answer_index is not None
                        else "answers:hidden"
                    ),
                ),
                package=TaskPackageSpec(
                    package_schema_id=(
                        "egoschema.long-form-video-mcq-package.v1"
                    ),
                    instruction_digest=task_digest,
                    environment_requirement_id=(
                        "benchmark.long-video.decode"
                    ),
                    verifier_requirement_id=(
                        "benchmark.egoschema.public-answer"
                        if require_public_answers
                        else "benchmark.egoschema.official-external-evaluator"
                    ),
                    verifier_isolation=TaskVerifierIsolation.SEPARATE,
                ),
            )
        )
    task_ids = tuple(task.task_id for task in tasks)
    task_set = BenchmarkTaskSet(
        benchmark_id=EGOSCHEMA_BENCHMARK_ID,
        revision_id=revision,
        source_digest=source.content_digest,
        task_schema_id=EGOSCHEMA_SCHEMA_ID,
        tasks=tuple(tasks),
        splits=(TaskSetSplit(split_id, task_ids),),
        selection_policy_digest=canonical_digest({
            "split_id": split_id,
            "source_digest": source.content_digest,
            "task_record_digests": tuple(
                row.record_digest for row in ordered
            ),
            "expected_count": expected_count,
            "public_answers_required": require_public_answers,
        }),
    )
    return BenchmarkSourceResolution(
        source=source,
        task_set=task_set,
    )


def bind_egoschema_public_500(
    records: tuple[EgoSchemaTaskRecord, ...],
    *,
    questions_content_sha256: str,
    public_answers_content_sha256: str,
) -> BenchmarkSourceResolution:
    return _build_cut(
        records,
        split_id=EGOSCHEMA_PUBLIC_SPLIT,
        expected_count=EGOSCHEMA_PUBLIC_COUNT,
        require_public_answers=True,
        questions_content_sha256=questions_content_sha256,
        public_answers_content_sha256=public_answers_content_sha256,
    )


def bind_egoschema_full_5031(
    records: tuple[EgoSchemaTaskRecord, ...],
    *,
    questions_content_sha256: str,
    public_answers_content_sha256: str,
) -> BenchmarkSourceResolution:
    return _build_cut(
        records,
        split_id=EGOSCHEMA_FULL_SPLIT,
        expected_count=EGOSCHEMA_FULL_COUNT,
        require_public_answers=False,
        questions_content_sha256=questions_content_sha256,
        public_answers_content_sha256=public_answers_content_sha256,
    )


__all__ = [
    "EGOSCHEMA_BENCHMARK_ID",
    "EGOSCHEMA_FULL_COUNT",
    "EGOSCHEMA_FULL_SPLIT",
    "EGOSCHEMA_PUBLIC_COUNT",
    "EGOSCHEMA_PUBLIC_SPLIT",
    "EGOSCHEMA_SCHEMA_ID",
    "EGOSCHEMA_SOURCE_COMMIT",
    "EGOSCHEMA_SOURCE_REPOSITORY",
    "EgoSchemaTaskRecord",
    "bind_egoschema_full_5031",
    "bind_egoschema_public_500",
    "build_egoschema_source",
]
