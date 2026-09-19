"""ExperimentPlan -> ExperimentProgram compilation and execution.

Each concurrency-preserving batch is one Machine transition. Observations are
stored in serializable Program state, so crash recovery resumes at the next
uncommitted batch rather than replaying an opaque matrix runner.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    JsonObject,
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    ExperimentConcern,
    ExperimentProgramBuilder,
    ProgramHandlerRegistry,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchMachineSession,
    ResearchProgram,
    ResearchProgramHost,
    core_program_handlers,
)
from noetrium_platform.research.experimentation.study.api import (
    BoundStudyExecutionPort,
    ExperimentPlan,
    StudyAssignment,
    StudyExecutionUnit,
    StudyMatrixExecutionReport,
    StudyMetricAggregate,
    StudyMetricAggregationPort,
    StudyMetricObservation,
)


class ExperimentBatchKind(StrEnum):
    REPETITION_UNITS = "repetition_units"
    PARALLEL_ASSIGNMENTS = "parallel_assignments"


@dataclass(frozen=True, slots=True)
class ExperimentBatch:
    batch_id: str
    kind: ExperimentBatchKind
    unit_repetitions: tuple[int, ...]
    assignment_digests: tuple[str, ...]
    batch_digest: str

    @classmethod
    def create(
        cls,
        *,
        batch_id: str,
        kind: ExperimentBatchKind,
        unit_repetitions: tuple[int, ...],
        assignment_digests: tuple[str, ...],
    ) -> "ExperimentBatch":
        return cls(
            batch_id=batch_id,
            kind=kind,
            unit_repetitions=unit_repetitions,
            assignment_digests=assignment_digests,
            batch_digest=canonical_digest({
                "batch_id": batch_id,
                "kind": kind.value,
                "unit_repetitions": unit_repetitions,
                "assignment_digests": assignment_digests,
            }),
        )

    def __post_init__(self) -> None:
        if not self.batch_id.strip():
            raise ValueError("experiment batch_id is required")
        if not isinstance(self.kind, ExperimentBatchKind):
            raise TypeError("experiment batch kind must be ExperimentBatchKind")
        if type(self.unit_repetitions) is not tuple or any(
            type(value) is not int or value < 0 for value in self.unit_repetitions
        ):
            raise TypeError("experiment batch repetitions must be non-negative int tuple")
        if type(self.assignment_digests) is not tuple or not self.assignment_digests:
            raise ValueError("experiment batch requires assignment digests")
        if len(self.assignment_digests) != len(set(self.assignment_digests)):
            raise ValueError("experiment batch assignment digests must be unique")
        expected = canonical_digest({
            "batch_id": self.batch_id,
            "kind": self.kind.value,
            "unit_repetitions": self.unit_repetitions,
            "assignment_digests": self.assignment_digests,
        })
        if self.batch_digest != expected:
            raise ValueError("experiment batch digest mismatch")


@dataclass(frozen=True, slots=True)
class CompiledExperimentProgram:
    plan: ExperimentPlan
    program: ResearchProgram
    batches: tuple[ExperimentBatch, ...]
    batch_plan_digest: str

    def initial_data(self) -> JsonObject:
        return {
            "plan_digest": self.plan.plan_digest,
            "batch_plan_digest": self.batch_plan_digest,
            "batch_cursor": 0,
            "observations": (),
            "aggregates": (),
        }


def _units(plan: ExperimentPlan) -> tuple[StudyExecutionUnit, ...]:
    grouped: dict[int, list[StudyAssignment]] = defaultdict(list)
    for assignment in plan.assignments:
        grouped[assignment.repetition].append(assignment)
    return tuple(
        StudyExecutionUnit(
            plan.protocol.study_id,
            repetition,
            tuple(sorted(grouped[repetition], key=lambda row: (row.variant_id, row.seed))),
        )
        for repetition in sorted(grouped)
    )


def _compile_batches(plan: ExperimentPlan) -> tuple[ExperimentBatch, ...]:
    units = _units(plan)
    policy = plan.protocol.concurrency_policy
    batches: list[ExperimentBatch] = []
    ordinal = 0
    if not policy.parallel_assignments:
        limit = policy.max_parallel_repetitions
        for start in range(0, len(units), limit):
            selected = units[start:start + limit]
            digests = tuple(
                assignment.assignment_digest
                for unit in selected
                for assignment in unit.assignments
            )
            batches.append(ExperimentBatch.create(
                batch_id=f"batch:{ordinal}",
                kind=ExperimentBatchKind.REPETITION_UNITS,
                unit_repetitions=tuple(unit.repetition for unit in selected),
                assignment_digests=digests,
            ))
            ordinal += 1
        return tuple(batches)

    repetition_limit = policy.max_parallel_repetitions
    variant_limit = policy.max_parallel_assignments
    for start in range(0, len(units), repetition_limit):
        active = units[start:start + repetition_limit]
        offsets = {unit.repetition: 0 for unit in active}
        while True:
            selected: list[StudyAssignment] = []
            repetitions: list[int] = []
            for unit in active:
                offset = offsets[unit.repetition]
                rows = unit.assignments[offset:offset + variant_limit]
                if rows:
                    selected.extend(rows)
                    repetitions.extend([unit.repetition] * len(rows))
                    offsets[unit.repetition] += len(rows)
            if not selected:
                break
            batches.append(ExperimentBatch.create(
                batch_id=f"batch:{ordinal}",
                kind=ExperimentBatchKind.PARALLEL_ASSIGNMENTS,
                unit_repetitions=tuple(repetitions),
                assignment_digests=tuple(row.assignment_digest for row in selected),
            ))
            ordinal += 1
    return tuple(batches)


def compile_experiment_program(plan: ExperimentPlan) -> CompiledExperimentProgram:
    if type(plan) is not ExperimentPlan:
        raise TypeError("compile_experiment_program requires ExperimentPlan")
    plan.assert_consistent()
    batches = _compile_batches(plan)
    if not batches:
        raise ValueError("experiment plan compiled to no execution batches")
    batch_plan_digest = canonical_digest(tuple(batch.batch_digest for batch in batches))
    program = (
        ExperimentProgramBuilder.create(
            program_id=f"experiment:{plan.protocol.study_id}",
            version="1",
            state_schema="experiment.program-state.v1",
            entrypoint="advance",
        )
        .semantic(
            "advance",
            ExperimentConcern.SCHEDULING,
            "experiment.execute_batch",
            configuration={
                "plan_digest": plan.plan_digest,
                "batch_plan_digest": batch_plan_digest,
            },
            next_node="advance",
        )
        .semantic(
            "aggregate",
            ExperimentConcern.AGGREGATION,
            "experiment.aggregate",
            configuration={
                "plan_digest": plan.plan_digest,
                "batch_plan_digest": batch_plan_digest,
            },
        )
        .build()
    )
    return CompiledExperimentProgram(plan, program, batches, batch_plan_digest)


def _observation_json(observation: StudyMetricObservation) -> JsonObject:
    assignment = observation.assignment
    return {
        "study_id": assignment.study_id,
        "variant_id": assignment.variant_id,
        "repetition": assignment.repetition,
        "seed": assignment.seed,
        "task_id": assignment.task_id,
        "assignment_digest": assignment.assignment_digest,
        "metrics": tuple((name, float(value)) for name, value in observation.metrics),
    }


def _observation_from_json(value: object) -> StudyMetricObservation:
    if not isinstance(value, dict):
        raise TypeError("experiment observation state row must be an object")
    assignment = StudyAssignment(
        study_id=value["study_id"],
        variant_id=value["variant_id"],
        repetition=value["repetition"],
        seed=value["seed"],
        task_id=value.get("task_id"),
    )
    if assignment.assignment_digest != value.get("assignment_digest"):
        raise ValueError("experiment observation assignment digest mismatch")
    metrics_value = value.get("metrics")
    if not isinstance(metrics_value, (tuple, list)):
        raise TypeError("experiment observation metrics must be a sequence")
    metrics = tuple((row[0], float(row[1])) for row in metrics_value)
    return StudyMetricObservation(assignment, metrics)


def _aggregate_json(value: StudyMetricAggregate) -> JsonObject:
    return {
        "study_id": value.study_id,
        "variant_id": value.variant_id,
        "metric_name": value.metric_name,
        "count": value.count,
        "mean": value.mean,
        "sample_variance": value.sample_variance,
        "standard_error": value.standard_error,
    }


def _aggregate_from_json(value: object) -> StudyMetricAggregate:
    if not isinstance(value, dict):
        raise TypeError("experiment aggregate state row must be an object")
    return StudyMetricAggregate(
        study_id=value["study_id"],
        variant_id=value["variant_id"],
        metric_name=value["metric_name"],
        count=value["count"],
        mean=value["mean"],
        sample_variance=value["sample_variance"],
        standard_error=value["standard_error"],
    )


class ExperimentProgramBinding:
    """Runtime binding for one immutable compiled experiment program."""

    def __init__(
        self,
        compiled: CompiledExperimentProgram,
        adapter: BoundStudyExecutionPort,
        aggregation: StudyMetricAggregationPort,
        *,
        task_group: TaskGroupPort | None = None,
    ) -> None:
        if not isinstance(compiled, CompiledExperimentProgram):
            raise TypeError("experiment binding requires CompiledExperimentProgram")
        if not isinstance(adapter, BoundStudyExecutionPort):
            raise TypeError("experiment binding requires BoundStudyExecutionPort")
        if not callable(getattr(aggregation, "aggregate", None)):
            raise TypeError("experiment binding requires StudyMetricAggregationPort")
        self.compiled = compiled
        self.adapter = adapter
        self.aggregation = aggregation
        self.task_group = task_group
        self._assignment_by_digest = {
            row.assignment_digest: row for row in compiled.plan.assignments
        }
        self._units_by_repetition = {
            unit.repetition: unit for unit in _units(compiled.plan)
        }
        self._binding_by_variant = {
            row.variant.variant_id: row for row in compiled.plan.bindings
        }

    def _parallel(self, items: tuple[object, ...], fn, *, batch_id: str) -> tuple[object, ...]:
        if len(items) <= 1:
            return tuple(fn(item) for item in items)
        if self.task_group is None:
            raise RuntimeError("parallel experiment batch requires TaskGroupPort")
        timeout = self.compiled.plan.protocol.concurrency_policy.repetition_timeout_seconds
        invocation = uuid4().hex
        handles = tuple(
            self.task_group.submit(
                ExecutionSpec(
                    task_id=f"experiment:{batch_id}:{invocation}:{index}",
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                lambda _context, owned=item: fn(owned),
                deadline=Deadline.after(timeout),
            )
            for index, item in enumerate(items)
        )
        values: list[object] = []
        errors: list[BaseException] = []
        for handle in handles:
            try:
                values.append(handle.result(timeout=timeout))
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup(f"experiment batch failed: {batch_id}", errors)
        return tuple(values)

    def _execute_batch(self, batch: ExperimentBatch) -> tuple[StudyMetricObservation, ...]:
        plan = self.compiled.plan
        if batch.kind is ExperimentBatchKind.REPETITION_UNITS:
            units = tuple(self._units_by_repetition[row] for row in batch.unit_repetitions)

            def execute(unit: StudyExecutionUnit):
                bindings = tuple(self._binding_by_variant[row.variant_id] for row in unit.assignments)
                values = tuple(self.adapter.execute_bound(unit, bindings, plan.plan_digest))
                expected = {row.assignment_digest for row in unit.assignments}
                actual = tuple(row.assignment.assignment_digest for row in values)
                if len(actual) != len(set(actual)) or set(actual) != expected:
                    raise ValueError("experiment unit did not return exact assignment observations")
                return values

            groups = self._parallel(units, execute, batch_id=batch.batch_id)
            return tuple(
                observation
                for group in groups
                for observation in group
            )

        assignments = tuple(self._assignment_by_digest[digest] for digest in batch.assignment_digests)

        def execute_variant(assignment: StudyAssignment):
            return self.adapter.execute_bound_variant(
                assignment,
                self._binding_by_variant[assignment.variant_id],
                plan.plan_digest,
            )

        observations = self._parallel(assignments, execute_variant, batch_id=batch.batch_id)
        return tuple(observations)

    def open_session(
        self,
        *,
        journal: MachineJournalPort | None = None,
        snapshot_store: MachineSnapshotStorePort | None = None,
        machine_id: str | None = None,
    ) -> ResearchMachineSession:
        owned_journal = journal if journal is not None else InMemoryMachineJournal()
        host = ResearchProgramHost(
            host_id="experiment.program",
            program=self.compiled.program,
            journal=owned_journal,
            snapshot_store=snapshot_store,
            base_handlers=self.handlers(),
            dependency_identity={
                "plan_digest": self.compiled.plan.plan_digest,
                "batch_plan_digest": self.compiled.batch_plan_digest,
                "protocol_digest": self.compiled.plan.protocol.protocol_digest,
                "required_capabilities": self.compiled.program.required_capabilities,
                "batches": tuple(
                    row.batch_digest for row in self.compiled.batches
                ),
            },
        )
        resolved_machine_id = (
            machine_id
            or f"experiment:{self.compiled.plan.protocol.study_id}:"
            f"{self.compiled.plan.plan_digest[:16]}"
        )
        return host.open_session(
            machine_id=resolved_machine_id,
            instance_identity={
                "plan_digest": self.compiled.plan.plan_digest,
                "binding_digest": self.compiled.plan.binding_digest,
                "batch_plan_digest": self.compiled.batch_plan_digest,
            },
            binding=None,
        )

    def execute(
        self,
        *,
        journal: MachineJournalPort | None = None,
        snapshot_store: MachineSnapshotStorePort | None = None,
        machine_id: str | None = None,
    ) -> StudyMatrixExecutionReport:
        session = self.open_session(
            journal=journal,
            snapshot_store=snapshot_store,
            machine_id=machine_id,
        )
        if not session.started:
            session.start(
                self.compiled.initial_data(),
                command_id=f"{session.machine_id}:start",
            )
        if session.status is MachineStatus.RUNNABLE:
            run = session.run_until_blocked(
                command_id_prefix=f"{session.machine_id}:drive",
                max_steps=len(self.compiled.batches) + 2,
            )
            if run.status is not MachineStatus.COMPLETED:
                raise RuntimeError(
                    f"ExperimentProgram stopped with status={run.status.value}"
                )
        elif session.status is not MachineStatus.COMPLETED:
            raise RuntimeError(
                f"ExperimentProgram is not executable: status={session.status.value}"
            )
        session.checkpoint()
        return experiment_report_from_data(self.compiled, session.data)

    def handlers(self) -> ProgramHandlerRegistry:
        registry = core_program_handlers()

        def execute_batch(request: ProgramNodeRequest) -> ProgramNodeResult:
            data = request.data
            if data.get("plan_digest") != self.compiled.plan.plan_digest:
                raise ValueError("experiment Program state plan digest drift")
            if data.get("batch_plan_digest") != self.compiled.batch_plan_digest:
                raise ValueError("experiment Program state batch plan drift")
            cursor = data.get("batch_cursor", 0)
            if type(cursor) is not int or cursor < 0 or cursor >= len(self.compiled.batches):
                raise ValueError("experiment batch cursor is invalid")
            existing = data.get("observations", ())
            if not isinstance(existing, (tuple, list)):
                raise TypeError("experiment observations state must be a sequence")
            batch = self.compiled.batches[cursor]
            observations = self._execute_batch(batch)
            actual = tuple(row.assignment.assignment_digest for row in observations)
            if set(actual) != set(batch.assignment_digests) or len(actual) != len(batch.assignment_digests):
                raise ValueError("experiment batch observation identity mismatch")
            encoded = tuple(_observation_json(row) for row in observations)
            next_cursor = cursor + 1
            return ProgramNodeResult(
                value={"batch_id": batch.batch_id, "batch_digest": batch.batch_digest},
                state_update={
                    "batch_cursor": next_cursor,
                    "observations": tuple(existing) + encoded,
                },
                next_node="aggregate" if next_cursor == len(self.compiled.batches) else "advance",
                events=({
                    "type": "experiment_batch_completed",
                    "batch_id": batch.batch_id,
                    "batch_digest": batch.batch_digest,
                    "observation_count": len(observations),
                },),
            )

        def aggregate(request: ProgramNodeRequest) -> ProgramNodeResult:
            rows = request.data.get("observations", ())
            if not isinstance(rows, (tuple, list)):
                raise TypeError("experiment observations state must be a sequence")
            observations = tuple(_observation_from_json(row) for row in rows)
            expected = {row.assignment_digest for row in self.compiled.plan.assignments}
            actual = tuple(row.assignment.assignment_digest for row in observations)
            if len(actual) != len(set(actual)) or set(actual) != expected:
                raise ValueError("experiment cannot aggregate incomplete/duplicate observations")
            aggregates = self.aggregation.aggregate(
                self.compiled.plan.protocol,
                observations,
                self.compiled.plan.assignments,
            )
            report_digest = canonical_digest({
                "plan_digest": self.compiled.plan.plan_digest,
                "observations": tuple(_observation_json(row) for row in observations),
                "aggregates": tuple(_aggregate_json(row) for row in aggregates),
            })
            return ProgramNodeResult(
                value={"report_digest": report_digest},
                state_update={
                    "aggregates": tuple(_aggregate_json(row) for row in aggregates),
                    "report_digest": report_digest,
                },
                status=MachineStatus.COMPLETED,
                events=({
                    "type": "experiment_aggregated",
                    "report_digest": report_digest,
                    "observation_count": len(observations),
                    "aggregate_count": len(aggregates),
                },),
            )

        registry.register(
            "experiment.execute_batch",
            execute_batch,
            implementation_digest=canonical_digest({
                "operation": "experiment.execute_batch",
                "implementation_revision": 1,
            }),
        )
        registry.register(
            "experiment.aggregate",
            aggregate,
            implementation_digest=canonical_digest({
                "operation": "experiment.aggregate",
                "implementation_revision": 1,
            }),
        )
        return registry


def experiment_report_from_data(
    compiled: CompiledExperimentProgram,
    data: object,
) -> StudyMatrixExecutionReport:
    if not isinstance(data, dict):
        raise TypeError("experiment Program data must be an object")
    if data.get("plan_digest") != compiled.plan.plan_digest:
        raise ValueError("experiment report state belongs to another plan")
    observations = tuple(_observation_from_json(row) for row in data.get("observations", ()))
    aggregates = tuple(_aggregate_from_json(row) for row in data.get("aggregates", ()))
    if not aggregates:
        raise ValueError("experiment Program has not completed aggregation")
    return StudyMatrixExecutionReport(
        compiled.plan.protocol.protocol_digest,
        observations,
        aggregates,
        binding_digest=compiled.plan.binding_digest,
        plan_digest=compiled.plan.plan_digest,
    )


__all__ = [
    "CompiledExperimentProgram",
    "ExperimentBatch",
    "ExperimentBatchKind",
    "ExperimentProgramBinding",
    "compile_experiment_program",
    "experiment_report_from_data",
]
