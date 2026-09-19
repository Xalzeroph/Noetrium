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

VISUALWEBARENA_BENCHMARK_ID = "visualwebarena"
VISUALWEBARENA_OFFICIAL_REPOSITORY = "https://github.com/web-arena-x/visualwebarena"
VISUALWEBARENA_SOURCE_COMMIT = "8039d2e3420ec572f33483db7316fba0f216ace4"
VISUALWEBARENA_REVISION = f"visualwebarena@{VISUALWEBARENA_SOURCE_COMMIT}"
VISUALWEBARENA_TASK_SCHEMA_ID = "visualwebarena.browser-task.v1"
VISUALWEBARENA_SITE_TASK_COUNTS = {
    "classifieds": 234,
    "reddit": 210,
    "shopping": 466,
}
VISUALWEBARENA_RAW_CONFIG_BLOBS = {
    "classifieds": "f1d47cc7a0b003963c99ccc257d69bc8f313a4f7",
    "reddit": "7cc2a2eefc9b9b57cda4bb28b52b9c3d621ff7eb",
    "shopping": "f116bd0801f586339179f820390e089ba12e53a8",
}


def _site(site: str) -> str:
    if type(site) is not str or site not in VISUALWEBARENA_SITE_TASK_COUNTS:
        raise ValueError(
            "VisualWebArena site must be one of classifieds, reddit, shopping"
        )
    return site


def visualwebarena_site_split_id(site: str) -> str:
    return f"released_{_site(site)}"


def build_visualwebarena_source_spec(
    site: str,
    *,
    content_digest: str,
) -> BenchmarkSourceSpec:
    """Bind one official VWA site task file to the generic benchmark source ABI."""

    site = _site(site)
    require_sha256(content_digest, "VisualWebArena source content_digest")
    path = f"config_files/vwa/test_{site}.raw.json"
    return BenchmarkSourceSpec(
        source_id=f"visualwebarena.{site}",
        kind=BenchmarkSourceKind.GIT,
        revision_id=VISUALWEBARENA_REVISION,
        locator=(
            f"{VISUALWEBARENA_OFFICIAL_REPOSITORY}/blob/"
            f"{VISUALWEBARENA_SOURCE_COMMIT}/{path}"
        ),
        content_digest=content_digest,
        metadata={
            "repository": VISUALWEBARENA_OFFICIAL_REPOSITORY,
            "commit": VISUALWEBARENA_SOURCE_COMMIT,
            "path": path,
            "git_blob_sha1": VISUALWEBARENA_RAW_CONFIG_BLOBS[site],
            "site": site,
        },
    )


@dataclass(frozen=True, slots=True)
class VisualWebArenaTaskRecord:
    site: str
    index: int
    content_digest: str

    def __post_init__(self) -> None:
        site = _site(self.site)
        if type(self.index) is not int or not 0 <= self.index < VISUALWEBARENA_SITE_TASK_COUNTS[site]:
            raise ValueError(
                f"VisualWebArena {site} task index must be in "
                f"[0, {VISUALWEBARENA_SITE_TASK_COUNTS[site]})"
            )
        require_sha256(self.content_digest, "VisualWebArena task content_digest")

    @property
    def task_id(self) -> str:
        return f"visualwebarena:{self.site}:{self.index}"


def build_visualwebarena_site_task_set(
    site: str,
    records: tuple[VisualWebArenaTaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    """Freeze one full official VWA site split in released numeric order."""

    site = _site(site)
    if type(records) is not tuple or any(type(row) is not VisualWebArenaTaskRecord for row in records):
        raise TypeError("VisualWebArena records must be a tuple of VisualWebArenaTaskRecord")
    require_sha256(source_digest, "VisualWebArena source_digest")
    expected_count = VISUALWEBARENA_SITE_TASK_COUNTS[site]
    expected_indices = tuple(range(expected_count))
    if any(row.site != site for row in records):
        raise ValueError("VisualWebArena task records must all belong to the requested site")
    by_index = {row.index: row for row in records}
    if len(records) != expected_count or tuple(sorted(by_index)) != expected_indices:
        raise ValueError(
            f"VisualWebArena {site} cut requires exactly task indices 0 through {expected_count - 1}"
        )

    released_order = tuple(by_index[index] for index in expected_indices)
    tasks = tuple(
        sorted(
            (
                TaskDefinition(
                    task_id=row.task_id,
                    revision_id=VISUALWEBARENA_REVISION,
                    family=f"visualwebarena.{site}",
                    schema_id=VISUALWEBARENA_TASK_SCHEMA_ID,
                    content_digest=row.content_digest,
                    lineage_refs=(
                        f"site:{site}",
                        f"task-index:{row.index}",
                        f"source-commit:{VISUALWEBARENA_SOURCE_COMMIT}",
                    ),
                )
                for row in released_order
            ),
            key=lambda row: row.task_id,
        )
    )
    selection_policy_digest = canonical_digest(
        {
            "benchmark_id": VISUALWEBARENA_BENCHMARK_ID,
            "revision": VISUALWEBARENA_REVISION,
            "site": site,
            "start_index": 0,
            "end_index_exclusive": expected_count,
            "selection": "full_official_site_split",
        }
    )
    return BenchmarkTaskSet(
        benchmark_id=VISUALWEBARENA_BENCHMARK_ID,
        revision_id=VISUALWEBARENA_REVISION,
        source_digest=source_digest,
        task_schema_id=VISUALWEBARENA_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(
            TaskSetSplit(
                visualwebarena_site_split_id(site),
                tuple(row.task_id for row in released_order),
            ),
        ),
        selection_policy_digest=selection_policy_digest,
    )


__all__ = [
    "VISUALWEBARENA_BENCHMARK_ID",
    "VISUALWEBARENA_OFFICIAL_REPOSITORY",
    "VISUALWEBARENA_RAW_CONFIG_BLOBS",
    "VISUALWEBARENA_REVISION",
    "VISUALWEBARENA_SITE_TASK_COUNTS",
    "VISUALWEBARENA_SOURCE_COMMIT",
    "VISUALWEBARENA_TASK_SCHEMA_ID",
    "VisualWebArenaTaskRecord",
    "build_visualwebarena_site_task_set",
    "build_visualwebarena_source_spec",
    "visualwebarena_site_split_id",
]
