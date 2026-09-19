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

MULTIAGENTBENCH_BENCHMARK_ID = "multiagentbench"
MULTIAGENTBENCH_REPOSITORY = "https://github.com/ulab-uiuc/MARBLE"
MULTIAGENTBENCH_TASK_SCHEMA_ID = "multiagentbench.team-task.v1"
MULTIAGENTBENCH_ENVIRONMENTS = (
    "research",
    "database",
    "coding",
    "minecraft",
)


@dataclass(frozen=True, slots=True, order=True)
class MultiAgentBenchTaskRecord:
    task_id: str
    environment: str
    split_id: str
    participant_roles: tuple[str, ...]
    content_digest: str

    def __post_init__(self) -> None:
        for field_name in ("task_id", "split_id"):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"MultiAgentBench {field_name} must be non-empty")
        if self.environment not in MULTIAGENTBENCH_ENVIRONMENTS:
            raise ValueError(
                f"unsupported MultiAgentBench environment: {self.environment!r}"
            )
        if type(self.participant_roles) is not tuple or len(self.participant_roles) < 2:
            raise ValueError("MultiAgentBench tasks require at least two participant roles")
        if any(
            type(role) is not str or not role.strip()
            for role in self.participant_roles
        ):
            raise ValueError("MultiAgentBench participant roles must be non-empty")
        if len(set(self.participant_roles)) != len(self.participant_roles):
            raise ValueError("MultiAgentBench participant roles must be unique")
        require_sha256(self.content_digest, "MultiAgentBench task content_digest")


def multiagentbench_revision(
    *,
    harness_commit: str,
    task_manifest_revision: str,
) -> str:
    if type(harness_commit) is not str or len(harness_commit) != 40:
        raise ValueError("MultiAgentBench harness_commit must be a full Git SHA")
    if any(char not in "0123456789abcdef" for char in harness_commit):
        raise ValueError("MultiAgentBench harness_commit must be lowercase hexadecimal")
    if type(task_manifest_revision) is not str or not task_manifest_revision.strip():
        raise ValueError("MultiAgentBench task_manifest_revision must be non-empty")
    return (
        f"multiagentbench@{harness_commit}:tasks@"
        f"{task_manifest_revision.strip()}"
    )


def build_multiagentbench_source(
    *,
    harness_commit: str,
    task_manifest_revision: str,
    source_content_sha256: str,
) -> BenchmarkSourceSpec:
    require_sha256(source_content_sha256, "MultiAgentBench source_content_sha256")
    revision = multiagentbench_revision(
        harness_commit=harness_commit,
        task_manifest_revision=task_manifest_revision,
    )
    return BenchmarkSourceSpec(
        source_id=MULTIAGENTBENCH_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=revision,
        locator=MULTIAGENTBENCH_REPOSITORY,
        content_digest=source_content_sha256,
        license=None,
        metadata={
            "harness_commit": harness_commit,
            "task_manifest_revision": task_manifest_revision,
        },
    )


def build_multiagentbench_task_set(
    records: tuple[MultiAgentBenchTaskRecord, ...],
    *,
    harness_commit: str,
    task_manifest_revision: str,
    source_content_sha256: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or not records:
        raise ValueError("MultiAgentBench task records must be a non-empty tuple")
    if any(type(row) is not MultiAgentBenchTaskRecord for row in records):
        raise TypeError(
            "MultiAgentBench records must contain MultiAgentBenchTaskRecord"
        )
    require_sha256(source_content_sha256, "MultiAgentBench source_content_sha256")
    revision = multiagentbench_revision(
        harness_commit=harness_commit,
        task_manifest_revision=task_manifest_revision,
    )
    ordered = tuple(sorted(records, key=lambda row: row.task_id))
    task_ids = tuple(row.task_id for row in ordered)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("MultiAgentBench task ids must be unique")

    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=revision,
            family=row.environment,
            schema_id=MULTIAGENTBENCH_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=tuple(
                f"participant_role:{role}" for role in row.participant_roles
            ),
            package=TaskPackageSpec(
                package_schema_id=(
                    f"multiagentbench.{row.environment}.team-task-package.v1"
                ),
                instruction_digest=row.content_digest,
                environment_requirement_id=(
                    f"benchmark.multiagentbench.{row.environment}.environment"
                ),
                verifier_requirement_id=(
                    f"benchmark.multiagentbench.{row.environment}.verifier"
                ),
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for row in ordered
    )
    split_names = tuple(sorted({row.split_id for row in ordered}))
    splits = tuple(
        TaskSetSplit(
            split_id,
            tuple(row.task_id for row in ordered if row.split_id == split_id),
        )
        for split_id in split_names
    )
    selection_policy_digest = canonical_digest(
        {
            "benchmark_id": MULTIAGENTBENCH_BENCHMARK_ID,
            "harness_commit": harness_commit,
            "task_manifest_revision": task_manifest_revision,
            "tasks": tuple(
                {
                    "task_id": row.task_id,
                    "environment": row.environment,
                    "participant_roles": row.participant_roles,
                }
                for row in ordered
            ),
            "splits": tuple((row.split_id, row.task_ids) for row in splits),
        }
    )
    return BenchmarkTaskSet(
        benchmark_id=MULTIAGENTBENCH_BENCHMARK_ID,
        revision_id=revision,
        source_digest=source_content_sha256,
        task_schema_id=MULTIAGENTBENCH_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=splits,
        selection_policy_digest=selection_policy_digest,
    )


__all__ = [
    "MULTIAGENTBENCH_BENCHMARK_ID",
    "MULTIAGENTBENCH_ENVIRONMENTS",
    "MULTIAGENTBENCH_REPOSITORY",
    "MULTIAGENTBENCH_TASK_SCHEMA_ID",
    "MultiAgentBenchTaskRecord",
    "build_multiagentbench_source",
    "build_multiagentbench_task_set",
    "multiagentbench_revision",
]
