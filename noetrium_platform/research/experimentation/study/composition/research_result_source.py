"""ROLE03 read projection for producer-owned Study research records."""

from __future__ import annotations

from collections import OrderedDict
from threading import RLock

from noetrium_platform.evidence.data.query.api import (
    ResearchDimension,
    ResearchDimensionKind,
    ResearchResultKind,
    ResearchResultQuery,
    ResearchResultRecord,
    ResearchResultReference,
    ResearchSourceSnapshot,
)
from noetrium_platform.evidence.data.query.api.identity import source_cut
from noetrium_platform.research.experimentation.study.api import (
    StudyResearchReadPort,
    StudyResearchReadSnapshot,
)
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


class StudyResearchResultSource:
    """Federation adapter; it owns no Study state and performs no writes."""

    source_id = "experimentation.study"
    supported_kinds = frozenset({
        ResearchResultKind.TRIAL,
        ResearchResultKind.TASK,
        ResearchResultKind.MEASUREMENT,
    })
    supported_dimensions = frozenset({
        ResearchDimensionKind.PROJECT,
        ResearchDimensionKind.STUDY,
        ResearchDimensionKind.BENCHMARK,
        ResearchDimensionKind.TASK,
        ResearchDimensionKind.RUN,
        ResearchDimensionKind.TRIAL,
        ResearchDimensionKind.ASSIGNMENT,
        ResearchDimensionKind.VARIANT,
        ResearchDimensionKind.MEASUREMENT,
    })

    def __init__(self, read_port: StudyResearchReadPort, *, scope: ScopeIdentity) -> None:
        if type(scope) is not ScopeIdentity:
            raise TypeError("study result source scope must be ScopeIdentity")
        self._read_port = read_port
        self._scope = scope
        self._projection_cache: OrderedDict[str, tuple[ResearchResultRecord, ...]] = OrderedDict()
        self._snapshot_cache: OrderedDict[
            tuple[str, ResearchResultQuery], ResearchSourceSnapshot
        ] = OrderedDict()
        self._projection_cache_lock = RLock()

    @staticmethod
    def _matches(record: ResearchResultRecord, query: ResearchResultQuery) -> bool:
        if query.kinds and record.reference.kind not in query.kinds:
            return False
        dimensions = {item.kind: item for item in record.dimensions}
        return all(dimensions.get(item.kind) == item for item in query.dimensions)
    def _snapshot(self) -> StudyResearchReadSnapshot:
        snapshot = self._read_port.snapshot()
        if type(snapshot) is not StudyResearchReadSnapshot:
            raise RuntimeError("study research read port returned an invalid snapshot")
        if snapshot.scope != self._scope:
            raise RuntimeError("study research snapshot scope does not match source binding")
        return snapshot

    def _record(
        self,
        *,
        kind: ResearchResultKind,
        result_id: str,
        content_sha256: str,
        schema_ref: str,
        dimensions: tuple[ResearchDimension, ...],
        lineage: tuple[ResearchResultReference, ...] = (),
    ) -> ResearchResultRecord:
        return ResearchResultRecord(
            reference=ResearchResultReference(kind, result_id, self.source_id),
            scope=self._scope,
            content_sha256=content_sha256,
            schema_ref=schema_ref,
            dimensions=dimensions,
            lineage=lineage,
        )

    def _scope_dimensions(self) -> tuple[ResearchDimension, ...]:
        if self._scope.kind is ScopeKind.STUDY:
            return (ResearchDimension(ResearchDimensionKind.STUDY, self._scope.scope_id),)
        if self._scope.kind is ScopeKind.RUN:
            return (ResearchDimension(ResearchDimensionKind.RUN, self._scope.scope_id),)
        return ()

    @staticmethod
    def _unique_dimensions(
        dimensions: tuple[ResearchDimension, ...] | list[ResearchDimension],
    ) -> tuple[ResearchDimension, ...]:
        by_kind: dict[ResearchDimensionKind, ResearchDimension] = {}
        for dimension in dimensions:
            previous = by_kind.get(dimension.kind)
            if previous is not None and previous != dimension:
                raise RuntimeError("study result contains conflicting dimensions")
            by_kind.setdefault(dimension.kind, dimension)
        return tuple(by_kind.values())

    def _task_records(
        self, snapshot: StudyResearchReadSnapshot
    ) -> list[ResearchResultRecord]:
        records: list[ResearchResultRecord] = []
        for task_set in snapshot.task_sets:
            benchmark = ResearchDimension(
                ResearchDimensionKind.BENCHMARK, task_set.benchmark_id, task_set.revision_id
            )
            for task in task_set.tasks:
                records.append(self._record(
                    kind=ResearchResultKind.TASK,
                    result_id=(
                        f"{task_set.benchmark_id}@{task_set.revision_id}:"
                        f"{task.task_id}@{task.revision_id}"
                    ),
                    content_sha256=task.content_digest,
                    schema_ref=task.schema_id,
                    dimensions=self._scope_dimensions() + (
                        benchmark,
                        ResearchDimension(
                            ResearchDimensionKind.TASK, task.task_id, task.revision_id
                        ),
                    ),
                ))
        return records

    def _trial_records(
        self, snapshot: StudyResearchReadSnapshot
    ) -> tuple[list[ResearchResultRecord], dict[str, tuple[ResearchResultReference, ...]]]:
        records: list[ResearchResultRecord] = []
        measurement_lineage: dict[str, list[ResearchResultReference]] = {}
        for receipt in snapshot.trial_receipts:
            trial = ResearchResultReference(
                ResearchResultKind.TRIAL, receipt.request_digest, self.source_id
            )
            run_ids = {row.run_id for row in receipt.measurements}
            if len(run_ids) > 1:
                raise RuntimeError("trial receipt contains measurements from multiple runs")
            dimensions = list(self._scope_dimensions())
            if len(run_ids) == 1 and not any(
                row.kind is ResearchDimensionKind.RUN for row in dimensions
            ):
                dimensions.append(ResearchDimension(
                    ResearchDimensionKind.RUN, next(iter(run_ids))
                ))
            dimensions.append(ResearchDimension(
                ResearchDimensionKind.TRIAL, receipt.request_digest
            ))
            records.append(self._record(
                kind=ResearchResultKind.TRIAL,
                result_id=receipt.request_digest,
                content_sha256=receipt.receipt_digest,
                schema_ref="trial-execution.receipt.v1",
                dimensions=tuple(dimensions),
            ))
            for measurement in receipt.measurements:
                measurement_lineage.setdefault(measurement.record_digest, []).append(trial)
        return records, {
            key: tuple(sorted(values)) for key, values in measurement_lineage.items()
        }

    def _measurement_records(
        self,
        snapshot: StudyResearchReadSnapshot,
        trial_lineage: dict[str, tuple[ResearchResultReference, ...]],
    ) -> list[ResearchResultRecord]:
        records: list[ResearchResultRecord] = []
        measurements = {row.record_digest: row for row in snapshot.measurements}
        for receipt in snapshot.trial_receipts:
            for row in receipt.measurements:
                measurements.setdefault(row.record_digest, row)
        for measurement in measurements.values():
            dimensions = list(self._scope_dimensions())
            dimensions.extend((
                ResearchDimension(ResearchDimensionKind.PROJECT, measurement.project_id),
                ResearchDimension(ResearchDimensionKind.STUDY, measurement.study_id),
                ResearchDimension(ResearchDimensionKind.RUN, measurement.run_id),
                ResearchDimension(
                    ResearchDimensionKind.ASSIGNMENT, measurement.assignment_digest
                ),
                ResearchDimension(ResearchDimensionKind.VARIANT, measurement.variant_id),
                ResearchDimension(
                    ResearchDimensionKind.MEASUREMENT, measurement.measurement_id,
                    measurement.schema_id
                ),
            ))
            unique_dimensions = self._unique_dimensions(dimensions)
            records.append(self._record(
                kind=ResearchResultKind.MEASUREMENT,
                result_id=measurement.record_digest,
                content_sha256=measurement.value.digest(),
                schema_ref=measurement.schema_id,
                dimensions=unique_dimensions,
                lineage=trial_lineage.get(measurement.record_digest, ()),
            ))
        return records
    def _all_records(
        self, snapshot: StudyResearchReadSnapshot
    ) -> tuple[ResearchResultRecord, ...]:
        """Project one immutable producer snapshot once for concurrent read queries."""

        cache_key = snapshot.snapshot_digest
        with self._projection_cache_lock:
            cached = self._projection_cache.pop(cache_key, None)
            if cached is not None:
                self._projection_cache[cache_key] = cached
                return cached

            trial_records, trial_lineage = self._trial_records(snapshot)
            records = self._task_records(snapshot)
            records.extend(trial_records)
            records.extend(self._measurement_records(snapshot, trial_lineage))
            if len({row.reference for row in records}) != len(records):
                raise RuntimeError("study research source produced duplicate result references")
            projected = tuple(sorted(
                records,
                key=lambda row: (
                    row.reference.kind.value,
                    row.reference.result_id,
                ),
            ))
            self._projection_cache[cache_key] = projected
            while len(self._projection_cache) > 2:
                self._projection_cache.popitem(last=False)
            return projected

    def snapshot(self, query: ResearchResultQuery) -> ResearchSourceSnapshot:
        if not isinstance(query, ResearchResultQuery):
            raise TypeError("study result source query must be ResearchResultQuery")
        producer_snapshot = self._snapshot()
        cache_key = (producer_snapshot.snapshot_digest, query)
        with self._projection_cache_lock:
            cached = self._snapshot_cache.pop(cache_key, None)
            if cached is not None:
                self._snapshot_cache[cache_key] = cached
                return cached
            records = self._all_records(producer_snapshot)
            selected = (
                records
                if not query.kinds and not query.dimensions
                else tuple(row for row in records if self._matches(row, query))
            )
            projected = ResearchSourceSnapshot(
                source_id=self.source_id,
                cut=source_cut(self.source_id, query, selected),
                records=selected,
            )
            self._snapshot_cache[cache_key] = projected
            while len(self._snapshot_cache) > 8:
                self._snapshot_cache.popitem(last=False)
            return projected


__all__ = ["StudyResearchResultSource"]
