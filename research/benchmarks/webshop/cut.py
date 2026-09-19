from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)

WEBSHOP_BENCHMARK_ID = "webshop"
LATS_WEBSHOP_REVISION = "lats@853d8161:webshop"
LATS_WEBSHOP_SPLIT = "released_eval_0_49"
LATS_WEBSHOP_START_INDEX = 0
LATS_WEBSHOP_END_INDEX = 50
LATS_WEBSHOP_TASK_COUNT = LATS_WEBSHOP_END_INDEX - LATS_WEBSHOP_START_INDEX
WEBSHOP_TASK_SCHEMA_ID = "webshop.session-task.v1"
LATS_WEBSHOP_SELECTION_POLICY_DIGEST = canonical_digest(
    {
        "benchmark_id": WEBSHOP_BENCHMARK_ID,
        "revision": LATS_WEBSHOP_REVISION,
        "session_template": "fixed_{index}",
        "start_index": LATS_WEBSHOP_START_INDEX,
        "end_index_exclusive": LATS_WEBSHOP_END_INDEX,
        "selection": "released_lats_script_range",
    }
)


@dataclass(frozen=True, slots=True)
class WebShopTaskRecord:
    index: int
    content_digest: str

    def __post_init__(self) -> None:
        if type(self.index) is not int or not LATS_WEBSHOP_START_INDEX <= self.index < LATS_WEBSHOP_END_INDEX:
            raise ValueError("LATS WebShop task index must be in [0, 50)")
        require_sha256(self.content_digest, "WebShop task content_digest")

    @property
    def session_id(self) -> str:
        return f"fixed_{self.index}"

    @property
    def task_id(self) -> str:
        return f"webshop:{self.session_id}"


def build_lats_webshop_task_set(
    records: tuple[WebShopTaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    """Freeze the released LATS WebShop 0..49 evaluation sessions."""

    if type(records) is not tuple or any(type(row) is not WebShopTaskRecord for row in records):
        raise TypeError("WebShop records must be a tuple of WebShopTaskRecord")
    require_sha256(source_digest, "WebShop source_digest")
    expected_indices = tuple(range(LATS_WEBSHOP_START_INDEX, LATS_WEBSHOP_END_INDEX))
    by_index = {row.index: row for row in records}
    if len(records) != LATS_WEBSHOP_TASK_COUNT or tuple(sorted(by_index)) != expected_indices:
        raise ValueError("LATS released WebShop cut requires exactly task indices 0 through 49")

    released_order = tuple(by_index[index] for index in expected_indices)
    tasks = tuple(
        sorted(
            (
                TaskDefinition(
                    task_id=row.task_id,
                    revision_id=LATS_WEBSHOP_REVISION,
                    family="webshop",
                    schema_id=WEBSHOP_TASK_SCHEMA_ID,
                    content_digest=row.content_digest,
                    lineage_refs=(f"session:{row.session_id}",),
                )
                for row in released_order
            ),
            key=lambda row: row.task_id,
        )
    )
    return BenchmarkTaskSet(
        benchmark_id=WEBSHOP_BENCHMARK_ID,
        revision_id=LATS_WEBSHOP_REVISION,
        source_digest=source_digest,
        task_schema_id=WEBSHOP_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(LATS_WEBSHOP_SPLIT, tuple(row.task_id for row in released_order)),),
        selection_policy_digest=LATS_WEBSHOP_SELECTION_POLICY_DIGEST,
    )


__all__ = [
    "LATS_WEBSHOP_END_INDEX",
    "LATS_WEBSHOP_REVISION",
    "LATS_WEBSHOP_SELECTION_POLICY_DIGEST",
    "LATS_WEBSHOP_SPLIT",
    "LATS_WEBSHOP_START_INDEX",
    "LATS_WEBSHOP_TASK_COUNT",
    "WEBSHOP_BENCHMARK_ID",
    "WEBSHOP_TASK_SCHEMA_ID",
    "WebShopTaskRecord",
    "build_lats_webshop_task_set",
]
