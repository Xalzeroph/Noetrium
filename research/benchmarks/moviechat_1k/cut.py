from __future__ import annotations

from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
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


MOVIECHAT_1K_BENCHMARK_ID = "moviechat-1k"
MOVIECHAT_1K_TEST_SPLIT = "test"
MOVIECHAT_1K_SOURCE_URI = (
    "https://huggingface.co/datasets/Enxin/MovieChat-1K-test"
)
MOVIECHAT_1K_SCHEMA_ID = "moviechat-1k.long-video-qa-bundle.v1"
MOVIECHAT_1K_VIDEO_COUNT = 1000
MOVIECHAT_1K_GLOBAL_QA_PER_VIDEO = 3
MOVIECHAT_1K_BREAKPOINT_QA_PER_VIDEO = 10


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class MovieChatQuestion:
    question: str
    answer: str
    breakpoint_frame: int | None = None
    question_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "question", _text(self.question, "MovieChat question")
        )
        object.__setattr__(
            self, "answer", _text(self.answer, "MovieChat answer")
        )
        if self.breakpoint_frame is not None and (
            type(self.breakpoint_frame) is not int
            or self.breakpoint_frame < 0
        ):
            raise ValueError(
                "MovieChat breakpoint_frame must be non-negative integer"
            )
        object.__setattr__(
            self,
            "question_digest",
            canonical_digest({
                "question": self.question,
                "answer": self.answer,
                "breakpoint_frame": self.breakpoint_frame,
            }),
        )


@dataclass(frozen=True, slots=True)
class MovieChatVideoRecord:
    video_name: str
    fps: float
    num_frames: int
    global_questions: tuple[MovieChatQuestion, ...]
    breakpoint_questions: tuple[MovieChatQuestion, ...]
    content_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "video_name",
            _text(self.video_name, "MovieChat video_name"),
        )
        if not isinstance(self.fps, (int, float)) or self.fps <= 0:
            raise ValueError("MovieChat fps must be positive")
        if type(self.num_frames) is not int or self.num_frames < 1:
            raise ValueError("MovieChat num_frames must be positive")
        if type(self.global_questions) is not tuple or any(
            not isinstance(row, MovieChatQuestion)
            for row in self.global_questions
        ):
            raise TypeError(
                "MovieChat global_questions must be MovieChatQuestion tuple"
            )
        if type(self.breakpoint_questions) is not tuple or any(
            not isinstance(row, MovieChatQuestion)
            for row in self.breakpoint_questions
        ):
            raise TypeError(
                "MovieChat breakpoint_questions must be MovieChatQuestion tuple"
            )
        if len(self.global_questions) != MOVIECHAT_1K_GLOBAL_QA_PER_VIDEO:
            raise ValueError(
                "MovieChat-1K requires exactly 3 global QA per video"
            )
        if (
            len(self.breakpoint_questions)
            != MOVIECHAT_1K_BREAKPOINT_QA_PER_VIDEO
        ):
            raise ValueError(
                "MovieChat-1K requires exactly 10 breakpoint QA per video"
            )
        if any(
            row.breakpoint_frame is not None
            for row in self.global_questions
        ):
            raise ValueError(
                "MovieChat global questions must not carry breakpoint frames"
            )
        for row in self.breakpoint_questions:
            if row.breakpoint_frame is None:
                raise ValueError(
                    "MovieChat breakpoint question requires frame timestamp"
                )
            if row.breakpoint_frame >= self.num_frames:
                raise ValueError(
                    "MovieChat breakpoint frame must be inside video"
                )
        require_sha256(
            self.content_digest,
            "MovieChat video record content_digest",
        )

    @property
    def record_digest(self) -> str:
        return canonical_digest({
            "video_name": self.video_name,
            "fps": float(self.fps),
            "num_frames": self.num_frames,
            "global_question_digests": tuple(
                row.question_digest for row in self.global_questions
            ),
            "breakpoint_question_digests": tuple(
                row.question_digest for row in self.breakpoint_questions
            ),
            "content_digest": self.content_digest,
        })


def build_moviechat_1k_source(
    *,
    dataset_content_sha256: str,
) -> BenchmarkSourceSpec:
    require_sha256(
        dataset_content_sha256,
        "MovieChat-1K dataset content digest",
    )
    return BenchmarkSourceSpec(
        source_id=MOVIECHAT_1K_BENCHMARK_ID,
        kind=BenchmarkSourceKind.HTTP,
        revision_id=(
            "moviechat-1k-test:"
            f"{dataset_content_sha256}"
        ),
        locator=MOVIECHAT_1K_SOURCE_URI,
        content_digest=dataset_content_sha256,
        metadata={
            "paper_venue": "CVPR 2024",
            "video_count": str(MOVIECHAT_1K_VIDEO_COUNT),
            "global_qa_per_video": str(
                MOVIECHAT_1K_GLOBAL_QA_PER_VIDEO
            ),
            "breakpoint_qa_per_video": str(
                MOVIECHAT_1K_BREAKPOINT_QA_PER_VIDEO
            ),
            "global_execution": "one-memory-build-per-video",
            "breakpoint_execution": "memory-reset-per-question",
        },
    )


def build_moviechat_1k_test_cut(
    records: tuple[MovieChatVideoRecord, ...],
    *,
    dataset_content_sha256: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or any(
        not isinstance(row, MovieChatVideoRecord) for row in records
    ):
        raise TypeError(
            "MovieChat-1K records must be MovieChatVideoRecord tuple"
        )
    if len(records) != MOVIECHAT_1K_VIDEO_COUNT:
        raise ValueError(
            "MovieChat-1K canonical test cut requires exactly 1000 videos"
        )
    require_sha256(
        dataset_content_sha256,
        "MovieChat-1K dataset content digest",
    )

    ordered = tuple(sorted(records, key=lambda row: row.video_name))
    names = tuple(row.video_name for row in ordered)
    if len(names) != len(set(names)):
        raise ValueError("MovieChat-1K video names must be unique")

    revision = (
        "moviechat-1k-test:"
        f"{dataset_content_sha256}"
    )
    tasks: list[TaskDefinition] = []
    for index, row in enumerate(ordered):
        task_id = f"moviechat-1k:test:{index:04d}"
        content_digest = canonical_digest({
            "dataset_content_sha256": dataset_content_sha256,
            "record_digest": row.record_digest,
            "source_execution_semantics": {
                "global": (
                    "reset-memory-once-build-full-video-then-answer-"
                    "three-questions"
                ),
                "breakpoint": (
                    "reset-memory-before-each-question-build-prefix-"
                    "to-frame-timestamp"
                ),
            },
        })
        tasks.append(
            TaskDefinition(
                task_id=task_id,
                revision_id=revision,
                family="moviechat_long_video_qa",
                schema_id=MOVIECHAT_1K_SCHEMA_ID,
                content_digest=content_digest,
                lineage_refs=(
                    f"video:{row.video_name}",
                    "global-qa-count:3",
                    "breakpoint-qa-count:10",
                    "global-mode:shared-video-memory",
                    "breakpoint-mode:reset-per-question",
                ),
                package=TaskPackageSpec(
                    package_schema_id=(
                        "moviechat-1k.video-qa-bundle-package.v1"
                    ),
                    instruction_digest=content_digest,
                    environment_requirement_id=(
                        "benchmark.long-video.decode"
                    ),
                    verifier_requirement_id=(
                        "benchmark.moviechat-1k.paper-era-llm-judge"
                    ),
                    verifier_isolation=TaskVerifierIsolation.SEPARATE,
                ),
            )
        )

    ids = tuple(row.task_id for row in tasks)
    return BenchmarkTaskSet(
        benchmark_id=MOVIECHAT_1K_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id=MOVIECHAT_1K_SCHEMA_ID,
        tasks=tuple(tasks),
        splits=(
            TaskSetSplit(MOVIECHAT_1K_TEST_SPLIT, ids),
        ),
        selection_policy_digest=canonical_digest({
            "dataset_content_sha256": dataset_content_sha256,
            "record_digests": tuple(row.record_digest for row in ordered),
            "video_count": MOVIECHAT_1K_VIDEO_COUNT,
            "global_qa_per_video": MOVIECHAT_1K_GLOBAL_QA_PER_VIDEO,
            "breakpoint_qa_per_video": (
                MOVIECHAT_1K_BREAKPOINT_QA_PER_VIDEO
            ),
            "task_granularity": (
                "one-video-bundle-preserves-shared-global-memory"
            ),
        }),
    )


def bind_moviechat_1k_test_cut(
    records: tuple[MovieChatVideoRecord, ...],
    *,
    dataset_content_sha256: str,
) -> BenchmarkSourceResolution:
    return BenchmarkSourceResolution(
        source=build_moviechat_1k_source(
            dataset_content_sha256=dataset_content_sha256,
        ),
        task_set=build_moviechat_1k_test_cut(
            records,
            dataset_content_sha256=dataset_content_sha256,
        ),
    )


__all__ = [
    "MOVIECHAT_1K_BENCHMARK_ID",
    "MOVIECHAT_1K_BREAKPOINT_QA_PER_VIDEO",
    "MOVIECHAT_1K_GLOBAL_QA_PER_VIDEO",
    "MOVIECHAT_1K_SCHEMA_ID",
    "MOVIECHAT_1K_SOURCE_URI",
    "MOVIECHAT_1K_TEST_SPLIT",
    "MOVIECHAT_1K_VIDEO_COUNT",
    "MovieChatQuestion",
    "MovieChatVideoRecord",
    "bind_moviechat_1k_test_cut",
    "build_moviechat_1k_source",
    "build_moviechat_1k_test_cut",
]
