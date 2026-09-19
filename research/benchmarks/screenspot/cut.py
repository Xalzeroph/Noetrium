from __future__ import annotations

import math
from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    TaskDefinition,
    TaskPackageSpec,
    TaskSetSplit,
    TaskVerifierIsolation,
)

SCREENSPOT_BENCHMARK_ID = "screenspot"
SCREENSPOT_SPLIT_ID = "paper-test"
SCREENSPOT_ELEMENT_TYPES = ("text", "icon")
SCREENSPOT_PLATFORMS = ("iOS", "Android", "macOS", "Windows", "Web")


def _coordinate(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"ScreenSpot {field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"ScreenSpot {field} must be within [0,1]")
    return number


@dataclass(frozen=True, slots=True, order=True)
class ScreenSpotRecord:
    task_id: str
    screenshot_content_sha256: str
    instruction: str
    target_bbox: tuple[float, float, float, float]
    element_type: str
    platform: str

    def __post_init__(self) -> None:
        if type(self.task_id) is not str or not self.task_id.strip():
            raise ValueError("ScreenSpot task_id is required")
        require_sha256(
            self.screenshot_content_sha256,
            "ScreenSpot screenshot_content_sha256",
        )
        if type(self.instruction) is not str or not self.instruction.strip():
            raise ValueError("ScreenSpot instruction is required")
        if type(self.target_bbox) is not tuple or len(self.target_bbox) != 4:
            raise TypeError("ScreenSpot target_bbox must be a four-coordinate tuple")
        left, top, right, bottom = tuple(
            _coordinate(value, "target bbox coordinate")
            for value in self.target_bbox
        )
        if not left < right or not top < bottom:
            raise ValueError("ScreenSpot target_bbox must have positive area")
        object.__setattr__(self, "target_bbox", (left, top, right, bottom))
        if self.element_type not in SCREENSPOT_ELEMENT_TYPES:
            raise ValueError("ScreenSpot element_type is unsupported")
        if self.platform not in SCREENSPOT_PLATFORMS:
            raise ValueError("ScreenSpot platform is unsupported")

    @property
    def task_content_digest(self) -> str:
        return canonical_digest({
            "screenshot_content_sha256": self.screenshot_content_sha256,
            "instruction": self.instruction,
            "target_bbox": self.target_bbox,
            "element_type": self.element_type,
            "platform": self.platform,
        })


def build_screenspot_task_set(
    records: tuple[ScreenSpotRecord, ...],
    *,
    dataset_content_sha256: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or not records:
        raise ValueError("ScreenSpot records must be non-empty")
    if any(type(row) is not ScreenSpotRecord for row in records):
        raise TypeError("ScreenSpot records must be typed")
    require_sha256(dataset_content_sha256, "ScreenSpot dataset_content_sha256")
    ordered = tuple(sorted(records, key=lambda row: row.task_id))
    ids = tuple(row.task_id for row in ordered)
    if len(ids) != len(set(ids)):
        raise ValueError("ScreenSpot task ids must be unique")
    revision = f"screenspot:acl2024:{dataset_content_sha256}"
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=revision,
            family=f"{row.platform}:{row.element_type}",
            schema_id="screenspot.gui-grounding.v1",
            content_digest=row.task_content_digest,
            lineage_refs=(
                f"platform:{row.platform}",
                f"element-type:{row.element_type}",
                f"screenshot-sha256:{row.screenshot_content_sha256}",
            ),
            package=TaskPackageSpec(
                package_schema_id="screenspot.gui-grounding-package.v1",
                instruction_digest=canonical_digest(row.instruction),
                environment_requirement_id=None,
                verifier_requirement_id="benchmark.screenspot.grounding",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for row in ordered
    )
    splits = [
        TaskSetSplit("all", ids),
        TaskSetSplit(SCREENSPOT_SPLIT_ID, ids),
    ]
    for platform in SCREENSPOT_PLATFORMS:
        platform_ids = tuple(row.task_id for row in ordered if row.platform == platform)
        if platform_ids:
            splits.append(TaskSetSplit(f"platform:{platform}", platform_ids))
    return BenchmarkTaskSet(
        benchmark_id=SCREENSPOT_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id="screenspot.gui-grounding.v1",
        tasks=tasks,
        splits=tuple(splits),
        selection_policy_digest=canonical_digest({
            "dataset_content_sha256": dataset_content_sha256,
            "task_ids": ids,
            "coordinate_system": "normalized-[0,1]",
        }),
    )


__all__ = [
    "SCREENSPOT_BENCHMARK_ID",
    "SCREENSPOT_ELEMENT_TYPES",
    "SCREENSPOT_PLATFORMS",
    "SCREENSPOT_SPLIT_ID",
    "ScreenSpotRecord",
    "build_screenspot_task_set",
]
