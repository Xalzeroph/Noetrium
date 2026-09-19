from __future__ import annotations

from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkSourceKind,
    BenchmarkSourceResolution,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskPackageSpec,
    TaskSetSplit,
    TaskVerifierIsolation,
)


SAYCAN_BENCHMARK_ID = "saycan-101"
SAYCAN_DATA_REPOSITORY = "https://github.com/say-can/say-can.github.io"
SAYCAN_DATA_COMMIT = "69886495c40568ed782833c4440c831cf7bfda7a"
SAYCAN_INITIAL_CONDITIONS_PATH = (
    "data/saycan_initial_condition_for_dataset_v0.tsv"
)
SAYCAN_INITIAL_CONDITIONS_BLOB_SHA = (
    "0db34cc71e82e875d8549a4918d3121a9a14399d"
)
SAYCAN_PLAN_REFERENCE_PATH = "data/saycan_plan_v0_l.tsv"
SAYCAN_PLAN_REFERENCE_BLOB_SHA = (
    "1c9ae055d28e98fc005378f67ead432f6e16fc7e"
)
SAYCAN_TASK_COUNT = 101
SAYCAN_ALL_SPLIT = "all-101"
SAYCAN_TASK_SCHEMA_ID = "saycan.initial-condition-task.v0"


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be text")
    value = value.strip()
    if not value and not allow_empty:
        raise ValueError(f"{field_name} must be non-empty")
    return value


@dataclass(frozen=True, slots=True, order=True)
class SayCanTaskRecord:
    index: int
    family: str
    query: str
    robot_start_state: str
    environment_start_state: str
    note: str = ""
    record_digest: str = field(init=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.index) is not int or not 1 <= self.index <= SAYCAN_TASK_COUNT:
            raise ValueError("SayCan task index must be in [1, 101]")
        for field_name in (
            "family",
            "query",
            "robot_start_state",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), f"SayCan {field_name}"),
            )
        object.__setattr__(
            self,
            "environment_start_state",
            _text(
                self.environment_start_state,
                "SayCan environment_start_state",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "note",
            _text(self.note, "SayCan note", allow_empty=True),
        )
        object.__setattr__(
            self,
            "record_digest",
            canonical_digest({
                "index": self.index,
                "family": self.family,
                "query": self.query,
                "robot_start_state": self.robot_start_state,
                "environment_start_state": self.environment_start_state,
                "note": self.note,
            }),
        )


def parse_saycan_initial_conditions_tsv(
    text: str,
) -> tuple[SayCanTaskRecord, ...]:
    if type(text) is not str or not text.strip():
        raise ValueError("SayCan initial-condition TSV must be non-empty text")
    lines = tuple(
        line for line in text.replace("\r", "").split("\n") if line
    )
    if not lines:
        raise ValueError("SayCan initial-condition TSV is empty")
    header = tuple(lines[0].split("\t"))
    expected_header = (
        "Task Family",
        "Query",
        "Robot Start State",
        "Env Start State ",
    )
    if header != expected_header:
        raise ValueError("SayCan initial-condition TSV header drifted")

    records: list[SayCanTaskRecord] = []
    current_family = ""
    for index, line in enumerate(lines[1:], start=1):
        columns = line.split("\t")
        if len(columns) != 4:
            raise ValueError(
                f"SayCan TSV row {index} must contain exactly four columns"
            )
        raw_family, query, robot_start, environment_start = columns
        raw_family = raw_family.strip()
        note = ""
        if raw_family.startswith("*note"):
            if not current_family:
                raise ValueError("SayCan note row has no preceding family")
            note = raw_family
            family = current_family
        elif raw_family:
            current_family = raw_family
            family = raw_family
        else:
            if not current_family:
                raise ValueError("SayCan row has no task family")
            family = current_family

        records.append(
            SayCanTaskRecord(
                index=index,
                family=family,
                query=query,
                robot_start_state=robot_start,
                environment_start_state=environment_start,
                note=note,
            )
        )

    if len(records) != SAYCAN_TASK_COUNT:
        raise ValueError(
            f"SayCan v0 evaluation requires exactly {SAYCAN_TASK_COUNT} tasks"
        )
    if tuple(row.index for row in records) != tuple(
        range(1, SAYCAN_TASK_COUNT + 1)
    ):
        raise ValueError("SayCan task indices drifted")
    return tuple(records)


def saycan_source_content_digest() -> str:
    return canonical_digest({
        "repository": SAYCAN_DATA_REPOSITORY,
        "commit": SAYCAN_DATA_COMMIT,
        "initial_conditions": {
            "path": SAYCAN_INITIAL_CONDITIONS_PATH,
            "git_blob_sha": SAYCAN_INITIAL_CONDITIONS_BLOB_SHA,
        },
        "plan_reference": {
            "path": SAYCAN_PLAN_REFERENCE_PATH,
            "git_blob_sha": SAYCAN_PLAN_REFERENCE_BLOB_SHA,
            "role": "reference-only-not-verifier",
        },
    })


def build_saycan_source() -> BenchmarkSourceSpec:
    return BenchmarkSourceSpec(
        source_id=SAYCAN_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=SAYCAN_DATA_COMMIT,
        locator=SAYCAN_DATA_REPOSITORY,
        content_digest=saycan_source_content_digest(),
        metadata={
            "task_count": str(SAYCAN_TASK_COUNT),
            "initial_conditions_path": SAYCAN_INITIAL_CONDITIONS_PATH,
            "initial_conditions_git_blob_sha": (
                SAYCAN_INITIAL_CONDITIONS_BLOB_SHA
            ),
            "plan_reference_path": SAYCAN_PLAN_REFERENCE_PATH,
            "plan_reference_git_blob_sha": SAYCAN_PLAN_REFERENCE_BLOB_SHA,
            "plan_reference_role": "reference-only",
            "evaluation": "human-majority-plan-and-execution-success",
        },
    )


def bind_saycan_v0(
    records: tuple[SayCanTaskRecord, ...],
) -> BenchmarkSourceResolution:
    if type(records) is not tuple or any(
        not isinstance(row, SayCanTaskRecord) for row in records
    ):
        raise TypeError("SayCan records must be SayCanTaskRecord tuple")
    if len(records) != SAYCAN_TASK_COUNT:
        raise ValueError("SayCan v0 cut requires exactly 101 tasks")
    ordered = tuple(sorted(records, key=lambda row: row.index))
    indices = tuple(row.index for row in ordered)
    if indices != tuple(range(1, SAYCAN_TASK_COUNT + 1)):
        raise ValueError("SayCan records must cover indices 1..101 exactly")

    source = build_saycan_source()
    revision = (
        f"saycan-v0@{SAYCAN_DATA_COMMIT}:"
        f"{source.content_digest}"
    )
    tasks: list[TaskDefinition] = []
    for row in ordered:
        task_digest = canonical_digest({
            "benchmark_source_digest": source.content_digest,
            "record_digest": row.record_digest,
            "evaluation": {
                "plan_success": "human-majority-2-of-3",
                "execution_success": "human-majority-2-of-3",
            },
        })
        tasks.append(
            TaskDefinition(
                task_id=f"saycan:{row.index:03d}",
                revision_id=revision,
                family=row.family,
                schema_id=SAYCAN_TASK_SCHEMA_ID,
                content_digest=task_digest,
                lineage_refs=(
                    f"source-row:{row.index}",
                    f"family:{row.family}",
                    f"query-digest:{canonical_digest(row.query)}",
                    (
                        "robot-start-digest:"
                        f"{canonical_digest(row.robot_start_state)}"
                    ),
                    (
                        "environment-start-digest:"
                        f"{canonical_digest(row.environment_start_state)}"
                    ),
                    "plan-verifier:human-majority-2-of-3",
                    "execution-verifier:human-majority-2-of-3",
                ),
                package=TaskPackageSpec(
                    package_schema_id="saycan.robot-task.v0",
                    instruction_digest=task_digest,
                    environment_requirement_id=(
                        "environment.embodied.saycan-kitchen"
                    ),
                    verifier_requirement_id=(
                        "benchmark.saycan.human-majority"
                    ),
                    verifier_isolation=TaskVerifierIsolation.SEPARATE,
                ),
            )
        )
    task_ids = tuple(task.task_id for task in tasks)
    task_set = BenchmarkTaskSet(
        benchmark_id=SAYCAN_BENCHMARK_ID,
        revision_id=revision,
        source_digest=source.content_digest,
        task_schema_id=SAYCAN_TASK_SCHEMA_ID,
        tasks=tuple(tasks),
        splits=(TaskSetSplit(SAYCAN_ALL_SPLIT, task_ids),),
        selection_policy_digest=canonical_digest({
            "source_digest": source.content_digest,
            "task_record_digests": tuple(
                row.record_digest for row in ordered
            ),
            "split_id": SAYCAN_ALL_SPLIT,
            "task_count": SAYCAN_TASK_COUNT,
            "verifier": "human-majority-2-of-3",
        }),
    )
    return BenchmarkSourceResolution(source=source, task_set=task_set)


def bind_saycan_v0_tsv(text: str) -> BenchmarkSourceResolution:
    return bind_saycan_v0(parse_saycan_initial_conditions_tsv(text))


__all__ = [
    "SAYCAN_ALL_SPLIT",
    "SAYCAN_BENCHMARK_ID",
    "SAYCAN_DATA_COMMIT",
    "SAYCAN_DATA_REPOSITORY",
    "SAYCAN_INITIAL_CONDITIONS_BLOB_SHA",
    "SAYCAN_INITIAL_CONDITIONS_PATH",
    "SAYCAN_PLAN_REFERENCE_BLOB_SHA",
    "SAYCAN_PLAN_REFERENCE_PATH",
    "SAYCAN_TASK_COUNT",
    "SAYCAN_TASK_SCHEMA_ID",
    "SayCanTaskRecord",
    "bind_saycan_v0",
    "bind_saycan_v0_tsv",
    "build_saycan_source",
    "parse_saycan_initial_conditions_tsv",
    "saycan_source_content_digest",
]
