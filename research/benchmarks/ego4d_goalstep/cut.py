from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkSourceKind,
    BenchmarkSourceResolution,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskPackageSpec,
    TaskSetSplit,
    TaskVerifierIsolation,
)

EGO4D_GOALSTEP_BENCHMARK_ID = "ego4d-goalstep"
EGO4D_GOALSTEP_SOURCE_REPOSITORY = "https://github.com/facebookresearch/ego4d-goalstep"
EGO4D_GOALSTEP_SOURCE_COMMIT = "b4fe5768f1595b80a3367186f4c5316b979d04fb"
EGO4D_GOALSTEP_SCHEMA_ID = "ego4d-goalstep.online-step-detection.v1"
EGO4D_GOALSTEP_SPLITS = ("train", "val", "test")


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True, order=True)
class Ego4DGoalStepVideoRecord:
    split_id: str
    video_uid: str
    duration_seconds: float
    step_segment_count: int
    video_content_sha256: str
    annotation_content_sha256: str
    record_digest: str = field(init=False, compare=False)

    def __post_init__(self) -> None:
        split_id = _text(self.split_id, "GoalStep split_id")
        if split_id not in EGO4D_GOALSTEP_SPLITS:
            raise ValueError("GoalStep split_id must be train, val or test")
        object.__setattr__(self, "split_id", split_id)
        object.__setattr__(self, "video_uid", _text(self.video_uid, "GoalStep video_uid"))
        if isinstance(self.duration_seconds, bool) or not isinstance(self.duration_seconds, (int, float)) or float(self.duration_seconds) <= 0:
            raise ValueError("GoalStep duration_seconds must be positive")
        if type(self.step_segment_count) is not int or self.step_segment_count < 0:
            raise ValueError("GoalStep step_segment_count must be non-negative")
        video_digest = require_sha256(self.video_content_sha256, "GoalStep video content digest")
        annotation_digest = require_sha256(self.annotation_content_sha256, "GoalStep annotation content digest")
        object.__setattr__(self, "record_digest", canonical_digest({"split_id": split_id, "video_uid": self.video_uid, "duration_seconds": float(self.duration_seconds), "step_segment_count": self.step_segment_count, "video_content_sha256": video_digest, "annotation_content_sha256": annotation_digest}))


def build_ego4d_goalstep_source(*, dataset_content_sha256: str) -> BenchmarkSourceSpec:
    digest = require_sha256(dataset_content_sha256, "GoalStep dataset content digest")
    return BenchmarkSourceSpec(source_id=EGO4D_GOALSTEP_BENCHMARK_ID, kind=BenchmarkSourceKind.GIT, revision_id=f"{EGO4D_GOALSTEP_SOURCE_COMMIT}:dataset:{digest}", locator=EGO4D_GOALSTEP_SOURCE_REPOSITORY, content_digest=digest, metadata={"paper_venue": "NeurIPS 2023", "source_commit": EGO4D_GOALSTEP_SOURCE_COMMIT, "task": "online-step-detection", "evaluation": "per-frame-mean-average-precision", "data_access": "Ego4D CLI --benchmark goalstep"})


def bind_ego4d_goalstep_cut(records: tuple[Ego4DGoalStepVideoRecord, ...], *, dataset_content_sha256: str) -> BenchmarkSourceResolution:
    if type(records) is not tuple or any(not isinstance(row, Ego4DGoalStepVideoRecord) for row in records):
        raise TypeError("GoalStep records must be Ego4DGoalStepVideoRecord tuple")
    if not records:
        raise ValueError("GoalStep benchmark cut requires records")
    source = build_ego4d_goalstep_source(dataset_content_sha256=dataset_content_sha256)
    ordered = tuple(sorted(records, key=lambda row: (row.split_id, row.video_uid)))
    identities = tuple((row.split_id, row.video_uid) for row in ordered)
    if len(identities) != len(set(identities)):
        raise ValueError("GoalStep split/video identities must be unique")
    tasks: list[TaskDefinition] = []
    split_ids: dict[str, list[str]] = defaultdict(list)
    for row in ordered:
        task_id = f"ego4d-goalstep:{row.split_id}:{row.video_uid}"
        content_digest = canonical_digest({"source_digest": source.content_digest, "record_digest": row.record_digest, "task": "online-step-detection", "metric": "per-frame-map"})
        tasks.append(TaskDefinition(task_id=task_id, revision_id=source.revision_id, family="procedural_online_step_detection", schema_id=EGO4D_GOALSTEP_SCHEMA_ID, content_digest=content_digest, lineage_refs=(f"source-split:{row.split_id}", f"video:{row.video_uid}", f"step-segments:{row.step_segment_count}", "evaluation:per-frame-map"), package=TaskPackageSpec(package_schema_id="ego4d-goalstep.video-stream-package.v1", instruction_digest=content_digest, environment_requirement_id="benchmark.egocentric-video.stream", verifier_requirement_id="benchmark.ego4d-goalstep.per-frame-map", verifier_isolation=TaskVerifierIsolation.SEPARATE)))
        split_ids[row.split_id].append(task_id)
    return BenchmarkSourceResolution(source=source, task_set=BenchmarkTaskSet(benchmark_id=EGO4D_GOALSTEP_BENCHMARK_ID, revision_id=source.revision_id, source_digest=source.content_digest, task_schema_id=EGO4D_GOALSTEP_SCHEMA_ID, tasks=tuple(tasks), splits=tuple(TaskSetSplit(split_id, tuple(split_ids[split_id])) for split_id in sorted(split_ids)), selection_policy_digest=canonical_digest({"source_digest": source.content_digest, "source_commit": EGO4D_GOALSTEP_SOURCE_COMMIT, "record_digests": tuple(row.record_digest for row in ordered), "task_granularity": "one-streaming-video-per-task"})))


__all__ = ["EGO4D_GOALSTEP_BENCHMARK_ID", "EGO4D_GOALSTEP_SCHEMA_ID", "EGO4D_GOALSTEP_SOURCE_COMMIT", "EGO4D_GOALSTEP_SOURCE_REPOSITORY", "EGO4D_GOALSTEP_SPLITS", "Ego4DGoalStepVideoRecord", "bind_ego4d_goalstep_cut", "build_ego4d_goalstep_source"]
