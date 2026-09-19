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

WEBVOYAGER_BENCHMARK_ID = "webvoyager"
WEBVOYAGER_OFFICIAL_REPOSITORY = "https://github.com/MinorJerry/WebVoyager"
WEBVOYAGER_OFFICIAL_COMMIT = "091544539eba485dbd74ef3742011ddeede37336"
WEBVOYAGER_OFFICIAL_TASK_PATH = "data/WebVoyager_data.jsonl"
WEBVOYAGER_OFFICIAL_TASK_BLOB_SHA1 = "7ba2ebd2e3bf6da44210b887cfb29771af1bb0f7"
WEBVOYAGER_OFFICIAL_REVISION = (
    f"webvoyager@{WEBVOYAGER_OFFICIAL_COMMIT}:{WEBVOYAGER_OFFICIAL_TASK_PATH}"
)
WEBVOYAGER_OFFICIAL_SPLIT = "official_643"
WEBVOYAGER_OFFICIAL_TASK_COUNT = 643
WEBVOYAGER_TASK_SCHEMA_ID = "webvoyager.live-web-task.v1"
WEBVOYAGER_OFFICIAL_SELECTION_POLICY_DIGEST = canonical_digest({
    "benchmark_id": WEBVOYAGER_BENCHMARK_ID,
    "revision_id": WEBVOYAGER_OFFICIAL_REVISION,
    "repository": WEBVOYAGER_OFFICIAL_REPOSITORY,
    "commit": WEBVOYAGER_OFFICIAL_COMMIT,
    "path": WEBVOYAGER_OFFICIAL_TASK_PATH,
    "git_blob_sha1": WEBVOYAGER_OFFICIAL_TASK_BLOB_SHA1,
    "selection": "all_643_tasks_in_source_order",
})

WEBVOYAGER_AGENT_Q_SURROGATE_REPOSITORY = "https://github.com/sentient-engineering/agent-q"
WEBVOYAGER_AGENT_Q_SURROGATE_COMMIT = "6050777f833f43c36421398cb2f524ea9709c839"
WEBVOYAGER_AGENT_Q_SURROGATE_TASK_PATH = "test/tasks/webvoyager_test.json"
WEBVOYAGER_AGENT_Q_SURROGATE_TASK_BLOB_SHA1 = "cede5776c2cbd0ce404a5170748b4f4332ae94e4"
WEBVOYAGER_AGENT_Q_SURROGATE_REVISION = (
    f"agent-q-surrogate@{WEBVOYAGER_AGENT_Q_SURROGATE_COMMIT}:webvoyager_test"
)
WEBVOYAGER_AGENT_Q_SURROGATE_SPLIT = "surrogate_snapshot"
WEBVOYAGER_AGENT_Q_SURROGATE_TASK_COUNT = 643
WEBVOYAGER_AGENT_Q_SURROGATE_SELECTION_POLICY_DIGEST = canonical_digest({
    "benchmark_id": WEBVOYAGER_BENCHMARK_ID,
    "revision_id": WEBVOYAGER_AGENT_Q_SURROGATE_REVISION,
    "repository": WEBVOYAGER_AGENT_Q_SURROGATE_REPOSITORY,
    "commit": WEBVOYAGER_AGENT_Q_SURROGATE_COMMIT,
    "path": WEBVOYAGER_AGENT_Q_SURROGATE_TASK_PATH,
    "selection": "all_643_tasks_in_snapshot_order",
})


@dataclass(frozen=True, slots=True)
class OfficialWebVoyagerTaskRecord:
    index: int
    task_id: str
    website: str
    question: str
    start_url: str
    content_digest: str

    def __post_init__(self) -> None:
        if type(self.index) is not int or not 0 <= self.index < WEBVOYAGER_OFFICIAL_TASK_COUNT:
            raise ValueError("WebVoyager official task index must be in [0, 643)")
        for field_name in ("task_id", "website", "question", "start_url"):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"WebVoyager official {field_name} must be non-empty")
        if not self.start_url.startswith(("http://", "https://")):
            raise ValueError("WebVoyager official start_url must be HTTP(S)")
        require_sha256(self.content_digest, "WebVoyager official task content_digest")


def build_official_webvoyager_source_spec(*, content_digest: str) -> BenchmarkSourceSpec:
    require_sha256(content_digest, "WebVoyager official source content_digest")
    return BenchmarkSourceSpec(
        source_id="webvoyager.official",
        kind=BenchmarkSourceKind.GIT,
        revision_id=WEBVOYAGER_OFFICIAL_REVISION,
        locator=(
            f"{WEBVOYAGER_OFFICIAL_REPOSITORY}/blob/"
            f"{WEBVOYAGER_OFFICIAL_COMMIT}/{WEBVOYAGER_OFFICIAL_TASK_PATH}"
        ),
        content_digest=content_digest,
        metadata={
            "repository": WEBVOYAGER_OFFICIAL_REPOSITORY,
            "commit": WEBVOYAGER_OFFICIAL_COMMIT,
            "path": WEBVOYAGER_OFFICIAL_TASK_PATH,
            "git_blob_sha1": WEBVOYAGER_OFFICIAL_TASK_BLOB_SHA1,
            "expected_task_count": str(WEBVOYAGER_OFFICIAL_TASK_COUNT),
        },
    )


def build_official_webvoyager_task_set(
    records: tuple[OfficialWebVoyagerTaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or any(
        type(row) is not OfficialWebVoyagerTaskRecord for row in records
    ):
        raise TypeError("WebVoyager official records must be OfficialWebVoyagerTaskRecord tuple")
    require_sha256(source_digest, "WebVoyager official source_digest")
    if len(records) != WEBVOYAGER_OFFICIAL_TASK_COUNT:
        raise ValueError("WebVoyager official cut requires exactly 643 tasks")
    ordered = tuple(sorted(records, key=lambda row: row.index))
    if tuple(row.index for row in ordered) != tuple(range(WEBVOYAGER_OFFICIAL_TASK_COUNT)):
        raise ValueError("WebVoyager official task indices must be exactly 0 through 642")
    task_ids = tuple(row.task_id for row in ordered)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("WebVoyager official task ids must be unique")

    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=WEBVOYAGER_OFFICIAL_REVISION,
            family=row.website,
            schema_id=WEBVOYAGER_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"source-index:{row.index}",
                f"website:{row.website}",
                f"start-url:{row.start_url}",
                f"source-commit:{WEBVOYAGER_OFFICIAL_COMMIT}",
            ),
            package=TaskPackageSpec(
                package_schema_id="webvoyager.live-web-package.v1",
                instruction_digest=row.content_digest,
                environment_requirement_id="benchmark.webvoyager.live-web.environment",
                verifier_requirement_id="benchmark.webvoyager.task.verifier",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for row in ordered
    )
    return BenchmarkTaskSet(
        benchmark_id=WEBVOYAGER_BENCHMARK_ID,
        revision_id=WEBVOYAGER_OFFICIAL_REVISION,
        source_digest=source_digest,
        task_schema_id=WEBVOYAGER_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(WEBVOYAGER_OFFICIAL_SPLIT, task_ids),),
        selection_policy_digest=WEBVOYAGER_OFFICIAL_SELECTION_POLICY_DIGEST,
    )


@dataclass(frozen=True, slots=True)
class WebVoyagerTaskRecord:
    index: int
    start_url: str
    content_digest: str

    def __post_init__(self) -> None:
        if type(self.index) is not int or not 0 <= self.index < WEBVOYAGER_AGENT_Q_SURROGATE_TASK_COUNT:
            raise ValueError("WebVoyager surrogate task index must be in [0, 643)")
        if type(self.start_url) is not str or not self.start_url.startswith(("http://", "https://")):
            raise ValueError("WebVoyager task start_url must be an HTTP(S) URL")
        require_sha256(self.content_digest, "WebVoyager task content_digest")

    @property
    def task_id(self) -> str:
        return f"webvoyager:{self.index:03d}"

def build_agent_q_surrogate_webvoyager_source_spec(*, content_digest: str) -> BenchmarkSourceSpec:
    require_sha256(content_digest, "WebVoyager source content_digest")
    return BenchmarkSourceSpec(
        source_id="webvoyager.agent-q-surrogate",
        kind=BenchmarkSourceKind.GIT,
        revision_id=WEBVOYAGER_AGENT_Q_SURROGATE_REVISION,
        locator=f"{WEBVOYAGER_AGENT_Q_SURROGATE_REPOSITORY}/blob/{WEBVOYAGER_AGENT_Q_SURROGATE_COMMIT}/{WEBVOYAGER_AGENT_Q_SURROGATE_TASK_PATH}",
        content_digest=content_digest,
        metadata={
            "benchmark_family_repository": WEBVOYAGER_OFFICIAL_REPOSITORY,
            "snapshot_repository": WEBVOYAGER_AGENT_Q_SURROGATE_REPOSITORY,
            "snapshot_commit": WEBVOYAGER_AGENT_Q_SURROGATE_COMMIT,
            "snapshot_path": WEBVOYAGER_AGENT_Q_SURROGATE_TASK_PATH,
            "git_blob_sha1": WEBVOYAGER_AGENT_Q_SURROGATE_TASK_BLOB_SHA1,
            "expected_task_count": str(WEBVOYAGER_AGENT_Q_SURROGATE_TASK_COUNT),
        },
    )

def build_agent_q_surrogate_webvoyager_task_set(records: tuple[WebVoyagerTaskRecord, ...], *, source_digest: str) -> BenchmarkTaskSet:
    if type(records) is not tuple or any(type(row) is not WebVoyagerTaskRecord for row in records):
        raise TypeError("WebVoyager records must be a tuple of WebVoyagerTaskRecord")
    require_sha256(source_digest, "WebVoyager source_digest")
    by_index = {row.index: row for row in records}
    expected = tuple(range(WEBVOYAGER_AGENT_Q_SURROGATE_TASK_COUNT))
    if len(records) != WEBVOYAGER_AGENT_Q_SURROGATE_TASK_COUNT or tuple(sorted(by_index)) != expected:
        raise ValueError("Agent-Q surrogate WebVoyager cut requires exactly task indices 0 through 642")
    ordered = tuple(by_index[index] for index in expected)
    tasks = tuple(TaskDefinition(
        task_id=row.task_id,
        revision_id=WEBVOYAGER_AGENT_Q_SURROGATE_REVISION,
        family="webvoyager",
        schema_id=WEBVOYAGER_TASK_SCHEMA_ID,
        content_digest=row.content_digest,
        lineage_refs=(f"snapshot-index:{row.index}", f"start-url:{row.start_url}", f"snapshot-commit:{WEBVOYAGER_AGENT_Q_SURROGATE_COMMIT}"),
    ) for row in ordered)
    return BenchmarkTaskSet(
        benchmark_id=WEBVOYAGER_BENCHMARK_ID,
        revision_id=WEBVOYAGER_AGENT_Q_SURROGATE_REVISION,
        source_digest=source_digest,
        task_schema_id=WEBVOYAGER_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(WEBVOYAGER_AGENT_Q_SURROGATE_SPLIT, tuple(row.task_id for row in ordered)),),
        selection_policy_digest=WEBVOYAGER_AGENT_Q_SURROGATE_SELECTION_POLICY_DIGEST,
    )


__all__ = [name for name in globals() if name.startswith("WEBVOYAGER_")] + [
    "OfficialWebVoyagerTaskRecord",
    "WebVoyagerTaskRecord",
    "build_official_webvoyager_source_spec",
    "build_official_webvoyager_task_set",
    "build_agent_q_surrogate_webvoyager_source_spec",
    "build_agent_q_surrogate_webvoyager_task_set",
]
