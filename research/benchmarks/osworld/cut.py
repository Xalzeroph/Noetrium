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

OSWORLD_BENCHMARK_ID = "osworld"
OSWORLD_REPOSITORY = "https://github.com/xlang-ai/OSWorld"
OSWORLD_TASK_SCHEMA_ID = "osworld.desktop-task.v1"


@dataclass(frozen=True, slots=True, order=True)
class OSWorldTaskRecord:
    task_id: str
    domain: str
    split_id: str
    config_path: str
    content_digest: str

    def __post_init__(self) -> None:
        for field_name in ("task_id", "domain", "split_id", "config_path"):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"OSWorld {field_name} must be non-empty")
        if self.config_path.startswith("/") or ".." in self.config_path.split("/"):
            raise ValueError("OSWorld config_path must be repository-relative POSIX")
        require_sha256(self.content_digest, "OSWorld task content_digest")


def osworld_revision(
    *,
    harness_commit: str,
    task_manifest_revision: str,
) -> str:
    if type(harness_commit) is not str or len(harness_commit) != 40:
        raise ValueError("OSWorld harness_commit must be a full Git SHA")
    if any(char not in "0123456789abcdef" for char in harness_commit):
        raise ValueError("OSWorld harness_commit must be lowercase hexadecimal")
    if type(task_manifest_revision) is not str or not task_manifest_revision.strip():
        raise ValueError("OSWorld task_manifest_revision must be non-empty")
    return f"osworld@{harness_commit}:tasks@{task_manifest_revision.strip()}"


def build_osworld_source(
    *,
    harness_commit: str,
    task_manifest_revision: str,
    source_content_sha256: str,
) -> BenchmarkSourceSpec:
    require_sha256(source_content_sha256, "OSWorld source_content_sha256")
    revision = osworld_revision(
        harness_commit=harness_commit,
        task_manifest_revision=task_manifest_revision,
    )
    return BenchmarkSourceSpec(
        source_id=OSWORLD_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=revision,
        locator=OSWORLD_REPOSITORY,
        content_digest=source_content_sha256,
        license=None,
        metadata={
            "harness_commit": harness_commit,
            "task_manifest_revision": task_manifest_revision,
        },
    )


def build_osworld_task_set(
    records: tuple[OSWorldTaskRecord, ...],
    *,
    harness_commit: str,
    task_manifest_revision: str,
    source_content_sha256: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or not records:
        raise ValueError("OSWorld task records must be a non-empty tuple")
    if any(type(row) is not OSWorldTaskRecord for row in records):
        raise TypeError("OSWorld records must contain OSWorldTaskRecord")
    require_sha256(source_content_sha256, "OSWorld source_content_sha256")

    revision = osworld_revision(
        harness_commit=harness_commit,
        task_manifest_revision=task_manifest_revision,
    )
    ordered = tuple(sorted(records, key=lambda row: row.task_id))
    task_ids = tuple(row.task_id for row in ordered)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("OSWorld task ids must be unique")

    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=revision,
            family=row.domain,
            schema_id=OSWORLD_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(f"config:{row.config_path}",),
            package=TaskPackageSpec(
                package_schema_id="osworld.desktop-task-package.v1",
                instruction_digest=row.content_digest,
                environment_requirement_id="benchmark.osworld.gui.environment",
                verifier_requirement_id="benchmark.osworld.task.verifier",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
                verifier_environment_requirement_id="benchmark.osworld.verifier.environment",
                artifacts=(
                    TaskArtifactSpec(
                        "final_screenshot",
                        "final_screenshot.png",
                        required=False,
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
            tuple(row.task_id for row in ordered if row.split_id == split_id),
        )
        for split_id in split_names
    )
    selection_policy_digest = canonical_digest(
        {
            "benchmark_id": OSWORLD_BENCHMARK_ID,
            "harness_commit": harness_commit,
            "task_manifest_revision": task_manifest_revision,
            "splits": tuple((row.split_id, row.task_ids) for row in splits),
        }
    )
    return BenchmarkTaskSet(
        benchmark_id=OSWORLD_BENCHMARK_ID,
        revision_id=revision,
        source_digest=source_content_sha256,
        task_schema_id=OSWORLD_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=splits,
        selection_policy_digest=selection_policy_digest,
    )


__all__ = [
    "OSWORLD_BENCHMARK_ID",
    "OSWORLD_REPOSITORY",
    "OSWORLD_TASK_SCHEMA_ID",
    "OSWorldTaskRecord",
    "build_osworld_source",
    "build_osworld_task_set",
    "osworld_revision",
]
