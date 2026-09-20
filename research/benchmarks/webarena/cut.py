from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkSourceKind,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)

WEBARENA_BENCHMARK_ID = "webarena"
WEBARENA_OFFICIAL_REPOSITORY = "https://github.com/web-arena-x/webarena"
WEBARENA_SOURCE_COMMIT = "dce04686a56253aefba7b18a4fa0937cf1dc987b"
WEBARENA_REVISION = f"webarena@{WEBARENA_SOURCE_COMMIT}"
WEBARENA_TASK_SCHEMA_ID = "webarena.browser-task.v1"
WEBARENA_TEST_TASK_COUNT = 812
WEBARENA_TEST_CONFIG_PATH = "config_files/test.raw.json"
WEBARENA_TEST_CONFIG_BLOB_SHA1 = "6649a867e5d7c7da7e6f69c86d2ffdb505fb12d3"
WEBARENA_TEST_SPLIT = "released_test_812"


@dataclass(frozen=True, slots=True)
class WebArenaTaskRecord:
    index: int
    content_digest: str

    def __post_init__(self) -> None:
        if type(self.index) is not int or not 0 <= self.index < WEBARENA_TEST_TASK_COUNT:
            raise ValueError("WebArena task index must be in [0, 812)")
        require_sha256(self.content_digest, "WebArena task content_digest")

    @property
    def task_id(self) -> str:
        return f"webarena:{self.index:03d}"


def build_webarena_source_spec(*, content_digest: str) -> BenchmarkSourceSpec:
    require_sha256(content_digest, "WebArena source content_digest")
    return BenchmarkSourceSpec(
        source_id=WEBARENA_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=WEBARENA_REVISION,
        locator=(
            f"{WEBARENA_OFFICIAL_REPOSITORY}/blob/{WEBARENA_SOURCE_COMMIT}/"
            f"{WEBARENA_TEST_CONFIG_PATH}"
        ),
        content_digest=content_digest,
        metadata={
            "repository": WEBARENA_OFFICIAL_REPOSITORY,
            "commit": WEBARENA_SOURCE_COMMIT,
            "path": WEBARENA_TEST_CONFIG_PATH,
            "git_blob_sha1": WEBARENA_TEST_CONFIG_BLOB_SHA1,
            "task_count": str(WEBARENA_TEST_TASK_COUNT),
        },
    )


def build_webarena_test_cut(
    records: tuple[WebArenaTaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or any(type(row) is not WebArenaTaskRecord for row in records):
        raise TypeError("WebArena records must be WebArenaTaskRecord tuple")
    require_sha256(source_digest, "WebArena source_digest")
    by_index = {row.index: row for row in records}
    if len(records) != WEBARENA_TEST_TASK_COUNT or tuple(sorted(by_index)) != tuple(range(WEBARENA_TEST_TASK_COUNT)):
        raise ValueError("WebArena released cut requires task indices 0 through 811")
    ordered = tuple(by_index[index] for index in range(WEBARENA_TEST_TASK_COUNT))
    tasks = tuple(sorted((
        TaskDefinition(
            task_id=row.task_id,
            revision_id=WEBARENA_REVISION,
            family="webarena.browser",
            schema_id=WEBARENA_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"task-index:{row.index}",
                f"source-commit:{WEBARENA_SOURCE_COMMIT}",
            ),
        )
        for row in ordered
    ), key=lambda row: row.task_id))
    return BenchmarkTaskSet(
        benchmark_id=WEBARENA_BENCHMARK_ID,
        revision_id=WEBARENA_REVISION,
        source_digest=source_digest,
        task_schema_id=WEBARENA_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(WEBARENA_TEST_SPLIT, tuple(row.task_id for row in ordered)),),
        selection_policy_digest=canonical_digest({
            "benchmark_id": WEBARENA_BENCHMARK_ID,
            "revision": WEBARENA_REVISION,
            "selection": "full_official_released_test",
            "start_index": 0,
            "end_index_exclusive": WEBARENA_TEST_TASK_COUNT,
        }),
    )


__all__ = [
    "WEBARENA_BENCHMARK_ID", "WEBARENA_OFFICIAL_REPOSITORY",
    "WEBARENA_SOURCE_COMMIT", "WEBARENA_REVISION", "WEBARENA_TASK_SCHEMA_ID",
    "WEBARENA_TEST_TASK_COUNT", "WEBARENA_TEST_CONFIG_PATH",
    "WEBARENA_TEST_CONFIG_BLOB_SHA1", "WEBARENA_TEST_SPLIT",
    "WebArenaTaskRecord", "build_webarena_source_spec", "build_webarena_test_cut",
]
