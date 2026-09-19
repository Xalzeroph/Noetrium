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

SWEBENCH_BENCHMARK_ID = "swe-bench"
SWEBENCH_HARNESS_REPOSITORY = "https://github.com/SWE-bench/SWE-bench"
SWEBENCH_TASK_SCHEMA_ID = "swe-bench.software-issue-task.v1"

SWEBENCH_DATASET_LOCATORS = {
    "full": "https://huggingface.co/datasets/princeton-nlp/SWE-bench",
    "lite": "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite",
    "verified": "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified",
}


@dataclass(frozen=True, slots=True, order=True)
class SWEBenchTaskRecord:
    """One immutable SWE-bench issue instance from a pinned dataset cut."""

    instance_id: str
    repo: str
    base_commit: str
    split_id: str
    content_digest: str

    def __post_init__(self) -> None:
        for field_name in ("instance_id", "repo", "base_commit", "split_id"):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"SWE-bench {field_name} must be non-empty")
        require_sha256(self.content_digest, "SWE-bench task content_digest")


def swe_bench_revision(
    *,
    subset: str,
    harness_commit: str,
    dataset_revision: str,
) -> str:
    if subset not in SWEBENCH_DATASET_LOCATORS:
        raise ValueError(f"unsupported SWE-bench subset: {subset!r}")
    if type(harness_commit) is not str or len(harness_commit) != 40:
        raise ValueError("SWE-bench harness_commit must be a full Git SHA")
    if any(char not in "0123456789abcdef" for char in harness_commit):
        raise ValueError("SWE-bench harness_commit must be lowercase hexadecimal")
    if type(dataset_revision) is not str or not dataset_revision.strip():
        raise ValueError("SWE-bench dataset_revision must be non-empty")
    return (
        f"swe-bench:{subset}@harness:{harness_commit}:"
        f"dataset:{dataset_revision.strip()}"
    )


def build_swe_bench_source(
    *,
    subset: str,
    harness_commit: str,
    dataset_revision: str,
    dataset_content_sha256: str,
) -> BenchmarkSourceSpec:
    require_sha256(dataset_content_sha256, "SWE-bench dataset_content_sha256")
    revision = swe_bench_revision(
        subset=subset,
        harness_commit=harness_commit,
        dataset_revision=dataset_revision,
    )
    return BenchmarkSourceSpec(
        source_id=SWEBENCH_BENCHMARK_ID,
        kind=BenchmarkSourceKind.HUGGINGFACE,
        revision_id=revision,
        locator=SWEBENCH_DATASET_LOCATORS[subset],
        content_digest=dataset_content_sha256,
        license=None,
        metadata={
            "subset": subset,
            "harness_repository": SWEBENCH_HARNESS_REPOSITORY,
            "harness_commit": harness_commit,
            "dataset_revision": dataset_revision,
        },
    )


def build_swe_bench_task_set(
    records: tuple[SWEBenchTaskRecord, ...],
    *,
    subset: str,
    harness_commit: str,
    dataset_revision: str,
    dataset_content_sha256: str,
) -> BenchmarkTaskSet:
    """Adapt exact SWE-bench instances into the generic benchmark task ABI."""

    if type(records) is not tuple or not records:
        raise ValueError("SWE-bench task records must be a non-empty tuple")
    if any(type(row) is not SWEBenchTaskRecord for row in records):
        raise TypeError("SWE-bench records must contain SWEBenchTaskRecord")
    require_sha256(dataset_content_sha256, "SWE-bench dataset_content_sha256")
    revision = swe_bench_revision(
        subset=subset,
        harness_commit=harness_commit,
        dataset_revision=dataset_revision,
    )

    ordered = tuple(sorted(records, key=lambda row: row.instance_id))
    ids = tuple(row.instance_id for row in ordered)
    if len(ids) != len(set(ids)):
        raise ValueError("SWE-bench instance ids must be unique")

    tasks = tuple(
        TaskDefinition(
            task_id=row.instance_id,
            revision_id=revision,
            family=row.repo,
            schema_id=SWEBENCH_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"repo:{row.repo}",
                f"base_commit:{row.base_commit}",
            ),
            package=TaskPackageSpec(
                package_schema_id="swe-bench.patch-task-package.v1",
                instruction_digest=row.content_digest,
                environment_requirement_id="benchmark.swe-bench.software.environment",
                verifier_requirement_id="benchmark.swe-bench.patch.verifier",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
                verifier_environment_requirement_id=(
                    "benchmark.swe-bench.verifier.environment"
                ),
                artifacts=(
                    TaskArtifactSpec(
                        "prediction.patch",
                        "prediction.patch",
                        required=True,
                    ),
                ),
            ),
        )
        for row in ordered
    )

    split_names = tuple(sorted({row.split_id for row in ordered}))
    splits = tuple(
        TaskSetSplit(
            split_id,
            tuple(row.instance_id for row in ordered if row.split_id == split_id),
        )
        for split_id in split_names
    )
    selection_policy_digest = canonical_digest(
        {
            "benchmark_id": SWEBENCH_BENCHMARK_ID,
            "subset": subset,
            "harness_commit": harness_commit,
            "dataset_revision": dataset_revision,
            "splits": tuple((row.split_id, row.task_ids) for row in splits),
            "verification_artifact": "prediction.patch",
        }
    )
    return BenchmarkTaskSet(
        benchmark_id=SWEBENCH_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id=SWEBENCH_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=splits,
        selection_policy_digest=selection_policy_digest,
    )


__all__ = [
    "SWEBENCH_BENCHMARK_ID",
    "SWEBENCH_DATASET_LOCATORS",
    "SWEBENCH_HARNESS_REPOSITORY",
    "SWEBENCH_TASK_SCHEMA_ID",
    "SWEBenchTaskRecord",
    "build_swe_bench_source",
    "build_swe_bench_task_set",
    "swe_bench_revision",
]
