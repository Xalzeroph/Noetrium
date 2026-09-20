"""Source-bound benchmark adapter for newly introduced 2026 agent benchmarks.

The adapter does not embed external benchmark projects.  It converts verified,
content-addressed task records obtained from benchmark-specific importers into
Noetrium's canonical BenchmarkTaskSet authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)


SUPPORTED_BENCHMARKS = frozenset(
    {
        "mem-gallery",
        "osworld-verified",
        "windowsagentarena",
        "macosarena",
        "embodiedbench",
        "groundedvqa",
        "ego2web",
        "mmbench-gui",
        "androidworld",
        "androidlab",
        "state-control-benchmark",
        "video-mme",
        "hd-epic",
        "mlvu",
        "vstream-qa",
        "lmee-bench",
        "libero",
        "calvin",
        "robotwin2-hard",
        "screenspot-pro",
        "screenspot-v2",
        "androidcontrol",
        "aitw",
        "r2r-ce",
        "reverie-ce",
        "navrag-ce",
        "hm3d-ovon",
        "sg3d",
        "goat-bench",
        "minecraft-openha",
    }
)


@dataclass(frozen=True, slots=True)
class Frontier2026TaskRecord:
    benchmark_id: str
    task_id: str
    split_id: str
    content_digest: str
    family: str = "frontier-2026"
    schema_id: str = "frontier-2026.task.v1"
    lineage_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.benchmark_id not in SUPPORTED_BENCHMARKS:
            raise ValueError(
                f"unsupported 2026 benchmark {self.benchmark_id!r}; "
                f"expected one of {tuple(sorted(SUPPORTED_BENCHMARKS))!r}"
            )
        for name, value in (
            ("task_id", self.task_id),
            ("split_id", self.split_id),
            ("family", self.family),
            ("schema_id", self.schema_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"frontier 2026 task {name} must be non-empty")
        require_sha256(self.content_digest, "frontier 2026 task content_digest")
        if type(self.lineage_refs) is not tuple or any(
            type(row) is not str or not row.strip() for row in self.lineage_refs
        ):
            raise TypeError("frontier 2026 task lineage_refs must be a text tuple")
        if len(self.lineage_refs) != len(set(self.lineage_refs)):
            raise ValueError("frontier 2026 task lineage_refs must be unique")


def build_frontier_2026_task_set(
    records: tuple[Frontier2026TaskRecord, ...],
    *,
    benchmark_id: str,
    revision: str,
    source_uri: str,
    source_digest: str,
) -> BenchmarkTaskSet:
    """Freeze imported records into one canonical benchmark cut.

    Benchmark-specific code is responsible only for parsing the external
    dataset/environment release into Frontier2026TaskRecord objects.  Noetrium
    owns task identity, split authority, source/content digests and replayable
    experiment binding from this boundary onward.
    """

    if benchmark_id not in SUPPORTED_BENCHMARKS:
        raise ValueError(f"unsupported 2026 benchmark {benchmark_id!r}")
    for name, value in (("revision", revision), ("source_uri", source_uri)):
        if type(value) is not str or not value.strip():
            raise ValueError(f"frontier 2026 benchmark {name} must be non-empty")
    require_sha256(source_digest, "frontier 2026 benchmark source_digest")
    if type(records) is not tuple or not records:
        raise ValueError("frontier 2026 benchmark records must be a non-empty tuple")
    if any(type(row) is not Frontier2026TaskRecord for row in records):
        raise TypeError("records must contain Frontier2026TaskRecord")
    if any(row.benchmark_id != benchmark_id for row in records):
        raise ValueError("all records must belong to benchmark_id")

    task_ids = tuple(row.task_id for row in records)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("frontier 2026 task ids must be unique")
    schema_ids = {row.schema_id for row in records}
    if len(schema_ids) != 1:
        raise ValueError("one benchmark cut must use one task schema")
    task_schema_id = next(iter(schema_ids))

    ordered = tuple(sorted(records, key=lambda row: row.task_id))
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=revision,
            family=row.family,
            schema_id=row.schema_id,
            content_digest=row.content_digest,
            lineage_refs=(
                f"source:{source_uri}",
                f"source-revision:{revision}",
                *row.lineage_refs,
            ),
        )
        for row in ordered
    )

    split_ids = tuple(sorted({row.split_id for row in ordered}))
    splits = tuple(
        TaskSetSplit(
            split_id,
            tuple(
                row.task_id
                for row in ordered
                if row.split_id == split_id
            ),
        )
        for split_id in split_ids
    )
    selection_policy_digest = canonical_digest(
        {
            "benchmark_id": benchmark_id,
            "revision": revision,
            "source_uri": source_uri,
            "source_digest": source_digest,
            "task_schema_id": task_schema_id,
            "task_ids": tuple(row.task_id for row in ordered),
            "splits": tuple((split.split_id, split.task_ids) for split in splits),
        }
    )
    return BenchmarkTaskSet(
        benchmark_id=benchmark_id,
        revision_id=revision,
        source_digest=source_digest,
        task_schema_id=task_schema_id,
        tasks=tasks,
        splits=splits,
        selection_policy_digest=selection_policy_digest,
    )


__all__ = [
    "Frontier2026TaskRecord",
    "SUPPORTED_BENCHMARKS",
    "build_frontier_2026_task_set",
]
