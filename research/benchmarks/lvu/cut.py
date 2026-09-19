from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Mapping

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


LVU_BENCHMARK_ID = "lvu"
LVU_DATASET_VERSION = "1.0"
LVU_DATASET_URI = "https://chaoyuan.org/lvu/lvu_1.0.tar.gz"
LVU_REPOSITORY = "https://github.com/chaoyuaw/lvu"
LVU_PAPER_ERA_COMMIT = "e1e7d4f43e9a62ed989329d8fe36fc5b8837ccd4"
LVU_TASK_SCHEMA_ID = "lvu.long-video-window.v1"

LVU_CLASSIFICATION_TASKS = (
    "relationship",
    "way_speaking",
    "scene",
    "director",
    "writer",
    "year",
    "genre",
)
LVU_REGRESSION_TASKS = ("like_ratio", "view_count")
LVU_TASKS = (*LVU_CLASSIFICATION_TASKS, *LVU_REGRESSION_TASKS)

LVU_CLASS_COUNTS = {
    "relationship": 4,
    "way_speaking": 5,
    "scene": 6,
    "director": 10,
    "writer": 10,
    "year": 9,
    "genre": 4,
}

MA_LMM_LVU_TASKS = (
    "director",
    "genre",
    "relationship",
    "scene",
    "way_speaking",
    "writer",
    "year",
)


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _pairs(
    value: tuple[tuple[str, str], ...],
    field_name: str,
) -> tuple[tuple[str, str], ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field_name} must be a tuple")
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in value:
        if type(row) is not tuple or len(row) != 2:
            raise TypeError(f"{field_name} rows must be key/value tuples")
        key = _text(row[0], f"{field_name} key")
        val = _text(row[1], f"{field_name} value")
        if key in seen:
            raise ValueError(f"{field_name} keys must be unique")
        seen.add(key)
        rows.append((key, val))
    return tuple(sorted(rows))


@dataclass(frozen=True, slots=True, order=True)
class LVUVideoRecord:
    """One immutable LVU 1.0 video-level annotation record."""

    split_id: str
    video_id: str
    duration_seconds: int
    num_frames: int
    annotations: tuple[tuple[str, str], ...]
    answer_codes: tuple[tuple[str, str], ...] = ()
    content_digest: str = field(default="")

    def __post_init__(self) -> None:
        split_id = _text(self.split_id, "LVU split_id")
        if split_id not in {"train", "val", "test"}:
            raise ValueError("LVU split_id must be train, val or test")
        object.__setattr__(self, "split_id", split_id)
        object.__setattr__(self, "video_id", _text(self.video_id, "LVU video_id"))
        if type(self.duration_seconds) is not int or self.duration_seconds < 1:
            raise ValueError("LVU duration_seconds must be positive integer seconds")
        if type(self.num_frames) is not int or self.num_frames < 1:
            raise ValueError("LVU num_frames must be positive")
        annotations = _pairs(self.annotations, "LVU annotations")
        answers = _pairs(self.answer_codes, "LVU answer_codes")
        unknown = tuple(key for key, _ in annotations if key not in LVU_TASKS)
        if unknown:
            raise ValueError(f"LVU annotations contain unknown tasks: {unknown}")
        unknown_answers = tuple(key for key, _ in answers if key not in LVU_TASKS)
        if unknown_answers:
            raise ValueError(f"LVU answer_codes contain unknown tasks: {unknown_answers}")
        object.__setattr__(self, "annotations", annotations)
        object.__setattr__(self, "answer_codes", answers)
        require_sha256(self.content_digest, "LVU record content_digest")

    @property
    def annotation_map(self) -> Mapping[str, str]:
        return dict(self.annotations)

    @property
    def answer_map(self) -> Mapping[str, str]:
        return dict(self.answer_codes)


@dataclass(frozen=True, slots=True)
class LVUSelectionProtocol:
    """Method-independent projection from LVU videos to temporal task windows."""

    task_ids: tuple[str, ...]
    history_seconds: int
    stride_seconds: int
    sampled_frames: int
    fps: int = 10
    protocol_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.task_ids) is not tuple or not self.task_ids:
            raise TypeError("LVU selection task_ids must be non-empty tuple")
        if len(self.task_ids) != len(set(self.task_ids)):
            raise ValueError("LVU selection task_ids must be unique")
        if any(task not in LVU_TASKS for task in self.task_ids):
            raise ValueError("LVU selection contains unknown task")
        for name in (
            "history_seconds",
            "stride_seconds",
            "sampled_frames",
            "fps",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"LVU selection {name} must be positive")
        object.__setattr__(
            self,
            "protocol_digest",
            canonical_digest({
                "task_ids": self.task_ids,
                "history_seconds": self.history_seconds,
                "stride_seconds": self.stride_seconds,
                "sampled_frames": self.sampled_frames,
                "fps": self.fps,
                "window_semantics": (
                    "source-always-start-zero-then-range-stride-"
                    "duration-minus-history-plus-one"
                ),
                "frame_sampling": "numpy-rint-linspace-inclusive",
            }),
        )


MA_LMM_LVU_PROTOCOL = LVUSelectionProtocol(
    task_ids=MA_LMM_LVU_TASKS,
    history_seconds=100,
    stride_seconds=20,
    sampled_frames=100,
    fps=10,
)


@dataclass(frozen=True, slots=True)
class LVUFullVideoProtocol:
    """Method-independent full-video streaming projection for LVU."""

    task_ids: tuple[str, ...]
    fps: int = 10
    protocol_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.task_ids) is not tuple or not self.task_ids:
            raise TypeError(
                "LVU full-video task_ids must be non-empty tuple"
            )
        if len(self.task_ids) != len(set(self.task_ids)):
            raise ValueError(
                "LVU full-video task_ids must be unique"
            )
        if any(task not in LVU_TASKS for task in self.task_ids):
            raise ValueError(
                "LVU full-video protocol contains unknown task"
            )
        if type(self.fps) is not int or self.fps < 1:
            raise ValueError(
                "LVU full-video fps must be positive"
            )
        object.__setattr__(
            self,
            "protocol_digest",
            canonical_digest({
                "task_ids": self.task_ids,
                "fps": self.fps,
                "projection": "full-video-stream",
                "frame_sampling": "all-frames-at-declared-fps",
            }),
        )


def lvu_window_starts(
    duration_seconds: int,
    protocol: LVUSelectionProtocol,
) -> tuple[int, ...]:
    """Match MA-LMM/LVUCLSDataset temporal-window enumeration exactly."""

    if type(duration_seconds) is not int or duration_seconds < 1:
        raise ValueError("LVU window duration_seconds must be positive")
    if not isinstance(protocol, LVUSelectionProtocol):
        raise TypeError("LVU window protocol is invalid")
    return (
        0,
        *tuple(
            range(
                protocol.stride_seconds,
                duration_seconds - protocol.history_seconds + 1,
                protocol.stride_seconds,
            )
        ),
    )


def lvu_revision(
    dataset_content_sha256: str,
    protocol: LVUSelectionProtocol,
) -> str:
    require_sha256(dataset_content_sha256, "LVU dataset content digest")
    return (
        f"lvu-{LVU_DATASET_VERSION}@{LVU_PAPER_ERA_COMMIT}:"
        f"dataset:{dataset_content_sha256}:policy:{protocol.protocol_digest}"
    )


def build_lvu_source(
    *,
    dataset_content_sha256: str,
    revision_id: str,
) -> BenchmarkSourceSpec:
    require_sha256(dataset_content_sha256, "LVU dataset content digest")
    _text(revision_id, "LVU resolved revision_id")
    return BenchmarkSourceSpec(
        source_id=LVU_BENCHMARK_ID,
        kind=BenchmarkSourceKind.HTTP,
        revision_id=revision_id,
        locator=LVU_DATASET_URI,
        content_digest=dataset_content_sha256,
        metadata={
            "repository": LVU_REPOSITORY,
            "paper_era_commit": LVU_PAPER_ERA_COMMIT,
            "dataset_version": LVU_DATASET_VERSION,
            "task_count": "9",
            "classification_tasks": ",".join(LVU_CLASSIFICATION_TASKS),
            "regression_tasks": ",".join(LVU_REGRESSION_TASKS),
            "paper_venue": "CVPR 2021",
        },
    )


def _task_content_digest(
    row: LVUVideoRecord,
    *,
    task_id: str,
    start_second: int,
    protocol: LVUSelectionProtocol,
) -> str:
    annotation = row.annotation_map[task_id]
    answer = row.answer_map.get(task_id)
    end_second = min(
        start_second + protocol.history_seconds - 1,
        row.duration_seconds,
    )
    start_frame_index = int(start_second * protocol.fps)
    end_frame_index = min(
        int(end_second * protocol.fps),
        row.num_frames - 1,
    )
    return canonical_digest({
        "record_content_digest": row.content_digest,
        "video_id": row.video_id,
        "task_id": task_id,
        "annotation": annotation,
        "answer_code": answer,
        "start_second": start_second,
        "end_second": end_second,
        "start_frame_index": start_frame_index,
        "end_frame_index": end_frame_index,
        "sampled_frames": protocol.sampled_frames,
        "frame_sampling": "numpy-rint-linspace-inclusive",
        "protocol_digest": protocol.protocol_digest,
    })


def build_lvu_task_set(
    records: tuple[LVUVideoRecord, ...],
    *,
    dataset_content_sha256: str,
    protocol: LVUSelectionProtocol,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or any(
        not isinstance(row, LVUVideoRecord) for row in records
    ):
        raise TypeError("LVU records must be LVUVideoRecord tuple")
    if not records:
        raise ValueError("LVU benchmark cut requires records")
    require_sha256(dataset_content_sha256, "LVU dataset content digest")
    if not isinstance(protocol, LVUSelectionProtocol):
        raise TypeError("LVU selection protocol is invalid")

    ordered = tuple(
        sorted(records, key=lambda row: (row.split_id, row.video_id))
    )
    identities = tuple((row.split_id, row.video_id) for row in ordered)
    if len(identities) != len(set(identities)):
        raise ValueError("LVU split/video identities must be unique")

    revision = lvu_revision(dataset_content_sha256, protocol)
    tasks: list[TaskDefinition] = []
    split_task_ids: dict[str, list[str]] = defaultdict(list)

    for row in ordered:
        annotations = row.annotation_map
        for task_name in protocol.task_ids:
            if task_name not in annotations:
                continue
            for start_second in lvu_window_starts(
                row.duration_seconds,
                protocol,
            ):
                task_id = (
                    f"{row.split_id}:{row.video_id}:"
                    f"{task_name}:{start_second:06d}"
                )
                content_digest = _task_content_digest(
                    row,
                    task_id=task_name,
                    start_second=start_second,
                    protocol=protocol,
                )
                verifier = (
                    "benchmark.lvu.exact-label.verifier"
                    if task_name in LVU_CLASSIFICATION_TASKS
                    else "benchmark.lvu.regression.verifier"
                )
                tasks.append(
                    TaskDefinition(
                        task_id=task_id,
                        revision_id=revision,
                        family=f"lvu_{task_name}",
                        schema_id=LVU_TASK_SCHEMA_ID,
                        content_digest=content_digest,
                        lineage_refs=(
                            f"source-split:{row.split_id}",
                            f"video:{row.video_id}",
                            f"task:{task_name}",
                            f"window-start:{start_second}",
                            f"history-seconds:{protocol.history_seconds}",
                            f"stride-seconds:{protocol.stride_seconds}",
                            f"sampled-frames:{protocol.sampled_frames}",
                        ),
                        package=TaskPackageSpec(
                            package_schema_id=(
                                "lvu.long-video-window-package.v1"
                            ),
                            instruction_digest=content_digest,
                            environment_requirement_id=(
                                "benchmark.lvu.video-frame-sequence"
                            ),
                            verifier_requirement_id=verifier,
                            verifier_isolation=TaskVerifierIsolation.SEPARATE,
                        ),
                    )
                )
                split_task_ids[row.split_id].append(task_id)
                split_task_ids[
                    f"{row.split_id}:{task_name}"
                ].append(task_id)

    if not tasks:
        raise ValueError("LVU selection produced no tasks")

    all_ids = tuple(task.task_id for task in tasks)
    split_rows = [TaskSetSplit("all", all_ids)]
    for split_id in sorted(split_task_ids):
        ids = tuple(split_task_ids[split_id])
        if ids:
            split_rows.append(TaskSetSplit(split_id, ids))

    return BenchmarkTaskSet(
        benchmark_id=LVU_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id=LVU_TASK_SCHEMA_ID,
        tasks=tuple(tasks),
        splits=tuple(split_rows),
        selection_policy_digest=canonical_digest({
            "benchmark_id": LVU_BENCHMARK_ID,
            "dataset_content_sha256": dataset_content_sha256,
            "protocol_digest": protocol.protocol_digest,
            "record_content_digests": tuple(
                row.content_digest for row in ordered
            ),
            "task_ids": all_ids,
        }),
    )


def bind_lvu_cut(
    records: tuple[LVUVideoRecord, ...],
    *,
    dataset_content_sha256: str,
    protocol: LVUSelectionProtocol,
) -> BenchmarkSourceResolution:
    task_set = build_lvu_task_set(
        records,
        dataset_content_sha256=dataset_content_sha256,
        protocol=protocol,
    )
    return BenchmarkSourceResolution(
        source=build_lvu_source(
            dataset_content_sha256=dataset_content_sha256,
            revision_id=task_set.revision_id,
        ),
        task_set=task_set,
    )


def build_lvu_full_video_task_set(
    records: tuple[LVUVideoRecord, ...],
    *,
    dataset_content_sha256: str,
    protocol: LVUFullVideoProtocol,
) -> BenchmarkTaskSet:
    """Project each LVU video/task pair as one full-video streaming task."""

    if type(records) is not tuple or any(
        not isinstance(row, LVUVideoRecord) for row in records
    ):
        raise TypeError(
            "LVU full-video records must be LVUVideoRecord tuple"
        )
    if not records:
        raise ValueError("LVU full-video cut requires records")
    require_sha256(
        dataset_content_sha256,
        "LVU full-video dataset content digest",
    )
    if not isinstance(protocol, LVUFullVideoProtocol):
        raise TypeError("LVU full-video protocol is invalid")

    ordered = tuple(
        sorted(records, key=lambda row: (row.split_id, row.video_id))
    )
    identities = tuple((row.split_id, row.video_id) for row in ordered)
    if len(identities) != len(set(identities)):
        raise ValueError(
            "LVU full-video split/video identities must be unique"
        )

    revision = (
        f"lvu-{LVU_DATASET_VERSION}@{LVU_PAPER_ERA_COMMIT}:"
        f"dataset:{dataset_content_sha256}:"
        f"full-video-policy:{protocol.protocol_digest}"
    )
    tasks: list[TaskDefinition] = []
    split_task_ids: dict[str, list[str]] = defaultdict(list)

    for row in ordered:
        annotations = row.annotation_map
        for task_name in protocol.task_ids:
            if task_name not in annotations:
                continue
            task_id = (
                f"{row.split_id}:{row.video_id}:"
                f"{task_name}:full-video"
            )
            annotation = annotations[task_name]
            answer = row.answer_map.get(task_name)
            content_digest = canonical_digest({
                "record_content_digest": row.content_digest,
                "video_id": row.video_id,
                "task_id": task_name,
                "annotation": annotation,
                "answer_code": answer,
                "duration_seconds": row.duration_seconds,
                "num_frames": row.num_frames,
                "fps": protocol.fps,
                "projection": "full-video-stream",
                "protocol_digest": protocol.protocol_digest,
            })
            verifier = (
                "benchmark.lvu.exact-label.verifier"
                if task_name in LVU_CLASSIFICATION_TASKS
                else "benchmark.lvu.regression.verifier"
            )
            tasks.append(
                TaskDefinition(
                    task_id=task_id,
                    revision_id=revision,
                    family=f"lvu_{task_name}",
                    schema_id="lvu.full-video-stream.v1",
                    content_digest=content_digest,
                    lineage_refs=(
                        f"source-split:{row.split_id}",
                        f"video:{row.video_id}",
                        f"task:{task_name}",
                        "projection:full-video-stream",
                        f"fps:{protocol.fps}",
                        f"duration-seconds:{row.duration_seconds}",
                        f"source-frames:{row.num_frames}",
                    ),
                    package=TaskPackageSpec(
                        package_schema_id=(
                            "lvu.full-video-stream-package.v1"
                        ),
                        instruction_digest=content_digest,
                        environment_requirement_id=(
                            "benchmark.lvu.video-frame-stream"
                        ),
                        verifier_requirement_id=verifier,
                        verifier_isolation=(
                            TaskVerifierIsolation.SEPARATE
                        ),
                    ),
                )
            )
            split_task_ids[row.split_id].append(task_id)
            split_task_ids[
                f"{row.split_id}:{task_name}"
            ].append(task_id)

    if not tasks:
        raise ValueError(
            "LVU full-video projection produced no tasks"
        )

    all_ids = tuple(task.task_id for task in tasks)
    split_rows = [TaskSetSplit("all", all_ids)]
    for split_id in sorted(split_task_ids):
        ids = tuple(split_task_ids[split_id])
        if ids:
            split_rows.append(TaskSetSplit(split_id, ids))

    return BenchmarkTaskSet(
        benchmark_id=LVU_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id="lvu.full-video-stream.v1",
        tasks=tuple(tasks),
        splits=tuple(split_rows),
        selection_policy_digest=canonical_digest({
            "benchmark_id": LVU_BENCHMARK_ID,
            "dataset_content_sha256": dataset_content_sha256,
            "protocol_digest": protocol.protocol_digest,
            "record_content_digests": tuple(
                row.content_digest for row in ordered
            ),
            "task_ids": all_ids,
        }),
    )


def bind_lvu_full_video_cut(
    records: tuple[LVUVideoRecord, ...],
    *,
    dataset_content_sha256: str,
    protocol: LVUFullVideoProtocol,
) -> BenchmarkSourceResolution:
    task_set = build_lvu_full_video_task_set(
        records,
        dataset_content_sha256=dataset_content_sha256,
        protocol=protocol,
    )
    return BenchmarkSourceResolution(
        source=build_lvu_source(
            dataset_content_sha256=dataset_content_sha256,
            revision_id=task_set.revision_id,
        ),
        task_set=task_set,
    )


__all__ = [
    "LVU_BENCHMARK_ID",
    "LVU_CLASSIFICATION_TASKS",
    "LVU_CLASS_COUNTS",
    "LVU_DATASET_URI",
    "LVU_DATASET_VERSION",
    "LVU_PAPER_ERA_COMMIT",
    "LVU_REGRESSION_TASKS",
    "LVU_REPOSITORY",
    "LVU_TASKS",
    "LVU_TASK_SCHEMA_ID",
    "LVUFullVideoProtocol",
    "LVUSelectionProtocol",
    "LVUVideoRecord",
    "MA_LMM_LVU_PROTOCOL",
    "MA_LMM_LVU_TASKS",
    "bind_lvu_cut",
    "bind_lvu_full_video_cut",
    "build_lvu_full_video_task_set",
    "build_lvu_source",
    "build_lvu_task_set",
    "lvu_revision",
    "lvu_window_starts",
]
