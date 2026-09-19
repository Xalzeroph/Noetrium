from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkSourceKind,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskArtifactSpec,
    TaskDefinition,
    TaskPackageSpec,
    TaskSetSplit,
    TaskVerifierIsolation,
)

TOOLBENCH_BENCHMARK_ID = "toolbench"
TOOLBENCH_REPOSITORY = "https://github.com/OpenBMB/ToolBench"
TOOLBENCH_PAPER_CODE_COMMIT = "b2384c2a7f9c3e444a5e579596968ad88cd3201a"
TOOLBENCH_TOOLEVAL_COMMIT = TOOLBENCH_PAPER_CODE_COMMIT
TOOLBENCH_TASK_SCHEMA_ID = "toolbench.real-api-instruction.v1"
TOOLBENCH_SUBSETS = (
    "I1-Inst",
    "I1-Tool",
    "I1-Cat",
    "I2-Inst",
    "I2-Cat",
    "I3-Inst",
)
TOOLBENCH_API_BINDING_MODES = ("oracle", "retrieved-top5")


@dataclass(frozen=True, slots=True, order=True)
class ToolBenchTaskRecord:
    query_id: str
    subset_id: str
    content_digest: str
    oracle_api_set_digest: str
    oracle_api_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.query_id, str) or not self.query_id.strip():
            raise ValueError("ToolBench query_id must be non-empty")
        if self.subset_id not in TOOLBENCH_SUBSETS:
            raise ValueError(f"unsupported ToolBench subset: {self.subset_id!r}")
        require_sha256(self.content_digest, "ToolBench task content_digest")
        require_sha256(
            self.oracle_api_set_digest,
            "ToolBench oracle_api_set_digest",
        )
        if type(self.oracle_api_count) is not int or self.oracle_api_count <= 0:
            raise ValueError("ToolBench oracle_api_count must be positive")

    @property
    def task_id(self) -> str:
        return f"toolbench:{self.subset_id}:{self.query_id}"


def toolbench_revision(
    dataset_revision: str,
    *,
    api_binding_mode: str = "oracle",
) -> str:
    if not isinstance(dataset_revision, str) or not dataset_revision.strip():
        raise ValueError("ToolBench dataset_revision must be non-empty")
    if api_binding_mode not in TOOLBENCH_API_BINDING_MODES:
        raise ValueError(f"unsupported ToolBench API binding mode: {api_binding_mode!r}")
    return (
        f"toolbench@dataset:{dataset_revision.strip()}:"
        f"code:{TOOLBENCH_PAPER_CODE_COMMIT}:"
        f"tooleval:{TOOLBENCH_TOOLEVAL_COMMIT}:"
        f"apis:{api_binding_mode}"
    )


def build_toolbench_source(
    *,
    dataset_revision: str,
    dataset_content_sha256: str,
    api_binding_mode: str = "oracle",
) -> BenchmarkSourceSpec:
    require_sha256(dataset_content_sha256, "ToolBench dataset_content_sha256")
    return BenchmarkSourceSpec(
        source_id=TOOLBENCH_BENCHMARK_ID,
        kind=BenchmarkSourceKind.CUSTOM,
        revision_id=toolbench_revision(
            dataset_revision,
            api_binding_mode=api_binding_mode,
        ),
        locator=TOOLBENCH_REPOSITORY,
        content_digest=dataset_content_sha256,
        license="CC-BY-NC-4.0",
        metadata={
            "paper_code_commit": TOOLBENCH_PAPER_CODE_COMMIT,
            "tooleval_commit": TOOLBENCH_TOOLEVAL_COMMIT,
            "api_binding_mode": api_binding_mode,
            "subsets": ",".join(TOOLBENCH_SUBSETS),
            "paper_metrics": "pass_rate,win_rate",
            "external_environment": "RapidAPI",
        },
    )


def build_toolbench_task_set(
    records: tuple[ToolBenchTaskRecord, ...],
    *,
    dataset_revision: str,
    dataset_content_sha256: str,
    api_binding_mode: str = "oracle",
) -> BenchmarkTaskSet:
    """Freeze one exact ToolBench evaluation cut.

    Task cardinality is taken from the supplied immutable dataset cut rather than
    hard-coded from secondary reports. The six official subset memberships and
    every task/API-set digest become part of the benchmark cut identity.
    """

    if type(records) is not tuple or not records:
        raise ValueError("ToolBench records must be a non-empty tuple")
    if any(type(row) is not ToolBenchTaskRecord for row in records):
        raise TypeError("ToolBench records must contain ToolBenchTaskRecord")
    require_sha256(dataset_content_sha256, "ToolBench dataset_content_sha256")
    if api_binding_mode not in TOOLBENCH_API_BINDING_MODES:
        raise ValueError(f"unsupported ToolBench API binding mode: {api_binding_mode!r}")

    ordered = tuple(sorted(records, key=lambda row: row.task_id))
    task_ids = tuple(row.task_id for row in ordered)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("ToolBench task ids must be unique")

    revision = toolbench_revision(
        dataset_revision,
        api_binding_mode=api_binding_mode,
    )
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=revision,
            family=row.subset_id,
            schema_id=TOOLBENCH_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"subset:{row.subset_id}",
                f"oracle-api-set:{row.oracle_api_set_digest}",
                f"oracle-api-count:{row.oracle_api_count}",
                f"api-binding-mode:{api_binding_mode}",
            ),
            package=TaskPackageSpec(
                package_schema_id="toolbench.real-api-package.v1",
                instruction_digest=row.content_digest,
                environment_requirement_id="benchmark.toolbench.rapidapi.environment",
                verifier_requirement_id="benchmark.toolbench.tooleval.verifier",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
                artifacts=(
                    TaskArtifactSpec(
                        "toolbench_trajectory",
                        "answer_generation.json",
                        True,
                    ),
                ),
            ),
        )
        for row in ordered
    )
    splits = tuple(sorted(
        (
            TaskSetSplit(
                subset,
                tuple(row.task_id for row in ordered if row.subset_id == subset),
            )
            for subset in TOOLBENCH_SUBSETS
            if any(row.subset_id == subset for row in ordered)
        ),
        key=lambda split: split.split_id,
    ))
    selection_policy_digest = canonical_digest(
        {
            "benchmark_id": TOOLBENCH_BENCHMARK_ID,
            "dataset_revision": dataset_revision,
            "dataset_content_sha256": dataset_content_sha256,
            "paper_code_commit": TOOLBENCH_PAPER_CODE_COMMIT,
            "tooleval_commit": TOOLBENCH_TOOLEVAL_COMMIT,
            "api_binding_mode": api_binding_mode,
            "subsets": tuple(
                (split.split_id, split.task_ids)
                for split in splits
            ),
            "oracle_api_sets": tuple(
                (
                    row.task_id,
                    row.oracle_api_set_digest,
                    row.oracle_api_count,
                )
                for row in ordered
            ),
            "metrics": ("pass_rate", "win_rate"),
        }
    )
    return BenchmarkTaskSet(
        benchmark_id=TOOLBENCH_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id=TOOLBENCH_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=splits,
        selection_policy_digest=selection_policy_digest,
    )


__all__ = [
    "TOOLBENCH_API_BINDING_MODES",
    "TOOLBENCH_BENCHMARK_ID",
    "TOOLBENCH_PAPER_CODE_COMMIT",
    "TOOLBENCH_REPOSITORY",
    "TOOLBENCH_SUBSETS",
    "TOOLBENCH_TASK_SCHEMA_ID",
    "TOOLBENCH_TOOLEVAL_COMMIT",
    "ToolBenchTaskRecord",
    "build_toolbench_source",
    "build_toolbench_task_set",
    "toolbench_revision",
]
