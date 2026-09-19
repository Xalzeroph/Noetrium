from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import time

from noetrium_platform.evidence.data.query.api import (
    ResearchDimension,
    ResearchDimensionKind,
    ResearchResultKind,
    ResearchResultQuery,
)
from noetrium_platform.evidence.data.query.cross.composition import compose
from noetrium_platform.research.experimentation.identity import OptionalIdentityFacet
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    MeasurementRecord,
    MeasurementValue,
    MeasurementValueKind,
    StudyResearchReadSnapshot,
    TaskDefinition,
    TrialExecutionReceipt,
)
from noetrium_platform.research.experimentation.study.composition import StudyResearchResultSource
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind

SCOPE = ScopeIdentity(ScopeKind.RUN, "run-load")
SHA = lambda value: hashlib.sha256(value.encode()).hexdigest()


def _measurement(index: int) -> MeasurementRecord:
    return MeasurementRecord(
        "project-load",
        "study-load",
        "run-load",
        SHA(f"assignment-{index // 4}"),
        f"variant-{index % 2}",
        "paper-method-provider",
        SHA("provider-revision"),
        f"score-{index:05d}",
        "measurement.scalar.v1",
        SHA("measurement-semantics"),
        SHA("measurement-protocol"),
        MeasurementValue(MeasurementValueKind.SCALAR, scalar=float(index)),
        f"step:{index}",
        OptionalIdentityFacet(),
        OptionalIdentityFacet(),
    )
def _snapshot(task_count: int = 2048, trial_count: int = 512) -> StudyResearchReadSnapshot:
    measurements = tuple(_measurement(index) for index in range(task_count))
    trials = tuple(
        TrialExecutionReceipt(
            SHA(f"request-{trial}"),
            SHA(f"assignment-{trial}"),
            measurements[trial * 4:(trial + 1) * 4],
        )
        for trial in range(trial_count)
    )
    tasks = tuple(
        TaskDefinition(
            f"task-{index:05d}",
            "rev-1",
            "paper-benchmark",
            "task.schema.v1",
            SHA(f"task-content-{index}"),
        )
        for index in range(task_count)
    )
    task_set = BenchmarkTaskSet(
        "benchmark-load",
        "rev-1",
        SHA("benchmark-source"),
        "task.schema.v1",
        tasks,
    )
    return StudyResearchReadSnapshot(
        SCOPE,
        task_sets=(task_set,),
        trial_receipts=trials,
    )


class _ReadPort:
    def __init__(self, snapshot: StudyResearchReadSnapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> StudyResearchReadSnapshot:
        return self._snapshot


def test_study_source_projects_task_trial_and_measurement_with_lineage() -> None:
    source = StudyResearchResultSource(_ReadPort(_snapshot(16, 4)), scope=SCOPE)
    result = source.snapshot(ResearchResultQuery(limit=100))
    assert len(result.records) == 36
    assert {row.reference.kind for row in result.records} == {
        ResearchResultKind.TASK,
        ResearchResultKind.TRIAL,
        ResearchResultKind.MEASUREMENT,
    }
    measurement = next(
        row for row in result.records
        if row.reference.kind is ResearchResultKind.MEASUREMENT
    )
    assert measurement.lineage
    assert measurement.lineage[0].kind is ResearchResultKind.TRIAL
def test_study_source_supports_pinned_federated_reads_under_concurrency() -> None:
    source = StudyResearchResultSource(_ReadPort(_snapshot()), scope=SCOPE)
    federation = compose((source,))
    query = ResearchResultQuery(
        kinds=(
            ResearchResultKind.TASK,
            ResearchResultKind.TRIAL,
            ResearchResultKind.MEASUREMENT,
        ),
        limit=10_000,
    )
    started = time.perf_counter()
    pages = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        pages = list(pool.map(lambda _: federation.query(query), range(32)))
    elapsed = time.perf_counter() - started
    assert len(pages) == 32
    assert all(page.complete for page in pages)
    assert all(page.matched_count == 4608 for page in pages)
    assert len({page.input_cut_digest for page in pages}) == 1
    assert elapsed < 20.0


def test_study_source_filters_dimensions_without_materializing_a_second_authority() -> None:
    snapshot = _snapshot(64, 16)
    source = StudyResearchResultSource(_ReadPort(snapshot), scope=SCOPE)
    page = source.snapshot(ResearchResultQuery(
        dimensions=(
            ResearchDimension(
                ResearchDimensionKind.MEASUREMENT,
                "score-00017",
                "measurement.scalar.v1",
            ),
        ),
        kinds=(ResearchResultKind.MEASUREMENT,),
    ))
    assert len(page.records) == 1
    assert page.records[0].content_sha256 == _measurement(17).value.digest()
    assert page.cut.record_count == 1
def test_study_snapshot_digest_includes_measurements_embedded_in_trials() -> None:
    first = _snapshot(8, 2)
    second = StudyResearchReadSnapshot(
        SCOPE,
        task_sets=first.task_sets,
        trial_receipts=first.trial_receipts,
        measurements=tuple(_measurement(index) for index in range(8)),
    )
    assert first.snapshot_digest == second.snapshot_digest
