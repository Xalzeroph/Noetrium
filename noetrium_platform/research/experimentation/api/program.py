"""StudyExecutionPlan -> ExperimentProgram compilation and execution.

The Experiment Machine owns one completion-driven scheduling frontier. Child
Trial/Workload Machines remain the durable unit of physical work, so replay can
reuse completed assignments while the parent keeps all declared concurrency
slots saturated instead of imposing fixed wave barriers.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from queue import Queue
from typing import Protocol, runtime_checkable
from uuid import uuid4

from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.research.execution.api import (
    ArtifactReference,
    ScopeIdentity,
    ScopeKind,
    ExperimentConcern,
    ExperimentProgramBuilder,
    ProgramHandlerRegistry,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchMachineSessionPort,
    ResearchProgram,
    ResearchProgramHost,
    core_program_handlers,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    AssignmentWorkload,
    BoundStudyExecutionPort,
    StudyExecutionPlan,
    StudyAssignment,
    TaskGraph,
    TaskGraphEdge,
    TaskGraphRelation,
    StudyExecutionUnit,
    StudyMatrixExecutionReport,
    StudyMetricAggregate,
    StudyMetricAggregationPort,
    StudyMetricObservation,
)


@runtime_checkable
class _BoundStudyPreparationPort(Protocol):
    """Optional preparation seam on the canonical Study execution adapter."""

    def prepare_bound(
        self,
        unit: StudyExecutionUnit,
        bindings: tuple[object, ...],
        plan_digest: str,
        *,
        execution_id: str,
    ) -> None: ...

    def prepare_bound_variant(
        self,
        assignment: StudyAssignment,
        binding: object,
        plan_digest: str,
        *,
        execution_id: str,
    ) -> None: ...


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
    plan: StudyExecutionPlan
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


def _units(plan: StudyExecutionPlan) -> tuple[StudyExecutionUnit, ...]:
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


def _compile_batches(plan: StudyExecutionPlan) -> tuple[ExperimentBatch, ...]:
    units = _units(plan)
    if not units:
        return ()
    # Assignment independence is already encoded by the scientific plan. The
    # compiler never freezes a machine-specific parallelism number into that
    # plan; physical admission belongs to the runtime execution pool.
    assignments = tuple(
        assignment
        for unit in units
        for assignment in unit.assignments
    )
    return (
        ExperimentBatch.create(
            batch_id="frontier:0",
            kind=ExperimentBatchKind.PARALLEL_ASSIGNMENTS,
            unit_repetitions=tuple(
                assignment.repetition for assignment in assignments
            ),
            assignment_digests=tuple(
                assignment.assignment_digest for assignment in assignments
            ),
        ),
    )


def compile_experiment_program(plan: StudyExecutionPlan) -> CompiledExperimentProgram:
    if type(plan) is not StudyExecutionPlan:
        raise TypeError("compile_experiment_program requires StudyExecutionPlan")
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


def _artifact_reference_json(reference: ArtifactReference) -> JsonObject:
    return {
        "reference_id": reference.reference_id,
        "scope_kind": reference.scope.kind.value,
        "scope_id": reference.scope.scope_id,
        "artifact_id": reference.artifact_id,
        "generation": reference.generation,
    }


def _artifact_reference_from_json(value: object) -> ArtifactReference:
    if not isinstance(value, Mapping):
        raise TypeError("experiment artifact reference state must be an object")
    return ArtifactReference(
        str(value["reference_id"]),
        ScopeIdentity(ScopeKind(str(value["scope_kind"])), str(value["scope_id"])),
        str(value["artifact_id"]),
        int(value["generation"]),
    )


def _observation_json(observation: StudyMetricObservation) -> JsonObject:
    assignment = observation.assignment
    return {
        "study_id": assignment.study_id,
        "variant_id": assignment.variant_id,
        "repetition": assignment.repetition,
        "seed": assignment.seed,
        "workload": {
            "task_ids": assignment.workload.task_ids,
            "task_graph_edges": tuple(
                (
                    edge.source_task_id,
                    edge.target_task_id,
                    edge.relation.value,
                )
                for edge in assignment.workload.task_graph.edges
            ),
            "workload_digest": assignment.workload.workload_digest,
        },
        "assignment_digest": assignment.assignment_digest,
        "metrics": tuple((name, float(value)) for name, value in observation.metrics),
        "trial_request_digest": observation.trial_request_digest,
        "trial_receipt_digest": observation.trial_receipt_digest,
        "trial_receipt_reference": (
            None
            if observation.trial_receipt_reference is None
            else _artifact_reference_json(observation.trial_receipt_reference)
        ),
        "measurement_record_digests": observation.measurement_record_digests,
        "evidence_refs": tuple(
            _artifact_reference_json(row) for row in observation.evidence_refs
        ),
        "verifier_receipt_digest": observation.verifier_receipt_digest,
        "observation_digest": observation.observation_digest,
    }


def _observation_from_json(value: object) -> StudyMetricObservation:
    if not isinstance(value, Mapping):
        raise TypeError("experiment observation state row must be an object")
    workload_value = value.get("workload")
    if not isinstance(workload_value, Mapping):
        raise TypeError("experiment observation workload must be an object")
    task_ids_value = workload_value.get("task_ids")
    if not isinstance(task_ids_value, (tuple, list)):
        raise TypeError("experiment observation workload task_ids must be a sequence")
    edges_value = workload_value.get("task_graph_edges", ())
    if not isinstance(edges_value, (tuple, list)):
        raise TypeError(
            "experiment observation workload task_graph_edges must be a sequence"
        )
    workload = AssignmentWorkload(
        tuple(str(task_id) for task_id in task_ids_value),
        TaskGraph(
            tuple(
                sorted(
                    (
                        TaskGraphEdge(
                            str(row[0]),
                            str(row[1]),
                            TaskGraphRelation(str(row[2])),
                        )
                        for row in edges_value
                    )
                )
            )
        ),
    )
    if workload.workload_digest != workload_value.get("workload_digest"):
        raise ValueError("experiment observation workload digest mismatch")
    assignment = StudyAssignment(
        study_id=value["study_id"],
        variant_id=value["variant_id"],
        repetition=value["repetition"],
        seed=value["seed"],
        workload=workload,
    )
    if assignment.assignment_digest != value.get("assignment_digest"):
        raise ValueError("experiment observation assignment digest mismatch")
    metrics_value = value.get("metrics")
    if not isinstance(metrics_value, (tuple, list)):
        raise TypeError("experiment observation metrics must be a sequence")
    metrics = tuple((row[0], float(row[1])) for row in metrics_value)
    receipt_reference_value = value.get("trial_receipt_reference")
    observation = StudyMetricObservation(
        assignment,
        metrics,
        trial_request_digest=value.get("trial_request_digest"),
        trial_receipt_digest=value.get("trial_receipt_digest"),
        trial_receipt_reference=(
            None
            if receipt_reference_value is None
            else _artifact_reference_from_json(receipt_reference_value)
        ),
        measurement_record_digests=tuple(
            str(row) for row in value.get("measurement_record_digests", ())
        ),
        evidence_refs=tuple(
            _artifact_reference_from_json(row)
            for row in value.get("evidence_refs", ())
        ),
        verifier_receipt_digest=value.get("verifier_receipt_digest"),
    )
    expected_observation_digest = value.get("observation_digest")
    if (
        expected_observation_digest is not None
        and observation.observation_digest != expected_observation_digest
    ):
        raise ValueError("experiment observation provenance digest mismatch")
    return observation


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
    if not isinstance(value, Mapping):
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
        execution_binding_digest: str,
        execution_id: str,
        task_group: TaskGroupPort | None = None,
        frontier_capacity: int = 1,
    ) -> None:
        if not isinstance(compiled, CompiledExperimentProgram):
            raise TypeError("experiment binding requires CompiledExperimentProgram")
        if not isinstance(adapter, BoundStudyExecutionPort):
            raise TypeError("experiment binding requires BoundStudyExecutionPort")
        if not callable(getattr(aggregation, "aggregate", None)):
            raise TypeError("experiment binding requires StudyMetricAggregationPort")
        require_sha256(
            execution_binding_digest,
            "experiment execution_binding_digest",
        )
        require_sha256(
            execution_id,
            "experiment execution_id",
        )
        self.compiled = compiled
        self.adapter = adapter
        self._preparation = (
            adapter
            if isinstance(adapter, _BoundStudyPreparationPort)
            else None
        )
        self.aggregation = aggregation
        if type(frontier_capacity) is not int or frontier_capacity <= 0:
            raise ValueError("experiment frontier_capacity must be a positive integer")
        self.execution_binding_digest = execution_binding_digest
        self.execution_id = execution_id
        self.task_group = task_group
        self.frontier_capacity = frontier_capacity
        self._assignment_by_digest = {
            row.assignment_digest: row for row in compiled.plan.assignments
        }
        self._units_by_repetition = {
            unit.repetition: unit for unit in _units(compiled.plan)
        }
        self._binding_by_variant = {
            row.variant.variant_id: row for row in compiled.plan.bindings
        }

    @staticmethod
    def _prepare_once(
        index: int,
        items: tuple[object, ...],
        prepare,
        prepared: set[int],
    ) -> None:
        if prepare is None or index < 0 or index >= len(items) or index in prepared:
            return
        prepare(items[index])
        prepared.add(index)

    def _parallel(
        self,
        items: tuple[object, ...],
        fn,
        *,
        batch_id: str,
        limit: int,
        prepare=None,
    ) -> tuple[object, ...]:
        if type(limit) is not int or limit <= 0:
            raise ValueError("parallel experiment limit must be positive")
        # Without a platform TaskGroup there is no parallel execution authority.
        # Direct/internal bindings therefore degrade mechanically to one slot;
        # formal ResearchOS execution always injects the platform-owned group.
        effective_limit = 1 if self.task_group is None else limit
        prepared: set[int] = set()

        if len(items) <= 1 or effective_limit == 1:
            values: list[object] = []
            for index, item in enumerate(items):
                self._prepare_once(index, items, prepare, prepared)
                self._prepare_once(index + 1, items, prepare, prepared)
                values.append(fn(item))
            return tuple(values)

        if self.task_group is None:
            raise RuntimeError("parallel experiment batch requires TaskGroupPort")
        invocation = uuid4().hex
        completion: Queue[int] = Queue()
        active: dict[int, object] = {}
        values: list[object | None] = [None] * len(items)
        errors: list[BaseException] = []
        next_index = 0
        prepared_upto = 0

        def prepare_through(stop: int) -> None:
            nonlocal prepared_upto
            target = min(len(items), max(prepared_upto, stop))
            if prepare is not None:
                for candidate_index in range(prepared_upto, target):
                    prepare(items[candidate_index])
            prepared_upto = target

        def submit(index: int) -> None:
            if index >= prepared_upto:
                prepare_through(index + 1)
            item = items[index]

            def run(_context, owned=item, owned_index=index):
                try:
                    return fn(owned)
                finally:
                    completion.put(owned_index)

            active[index] = self.task_group.submit(
                ExecutionSpec(
                    task_id=f"experiment:{batch_id}:{invocation}:{index}",
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                run,
            )

        # Publish preparation for both the active wave and one complete
        # replacement wave before workers can begin consuming the active wave.
        # The frontier is monotonic: every item crosses preparation exactly once
        # instead of repeatedly rescanning an overlapping lookahead window.
        #
        # Preparation/submission is part of the same ownership boundary as the
        # workers already admitted by this rolling frontier.  If either fails,
        # the caller must not unwind into authority teardown while those workers
        # are still live.  Cancel every admitted handle and wait for physical
        # convergence before propagating the primary error.
        try:
            prepare_through(2 * effective_limit)
            while next_index < len(items) and len(active) < effective_limit:
                submit(next_index)
                next_index += 1

            while active:
                index = completion.get()
                handle = active.pop(index)
                try:
                    values[index] = handle.result()
                except BaseException as exc:
                    errors.append(exc)
                if next_index < len(items):
                    # Extend the replacement frontier before making the next slot
                    # runnable so startup work always leads execution.
                    prepare_through(next_index + effective_limit + 1)
                    submit(next_index)
                    next_index += 1
        except BaseException as primary:
            convergence_errors: list[BaseException] = []
            remaining = tuple(active.values())
            for handle in remaining:
                try:
                    handle.cancel()
                except BaseException as exc:
                    convergence_errors.append(exc)
            for handle in remaining:
                try:
                    handle.result()
                except BaseException:
                    # A cancelled/racing worker may report its own task failure;
                    # the rolling-frontier failure remains the causal primary.
                    pass
            active.clear()
            if convergence_errors:
                raise ExceptionGroup(
                    f"experiment batch abort convergence failed: {batch_id}",
                    [primary, *convergence_errors],
                ) from primary
            raise

        if errors:
            raise ExceptionGroup(f"experiment batch failed: {batch_id}", errors)
        if any(value is None for value in values):
            raise RuntimeError("experiment rolling scheduler lost a result")
        return tuple(values)

    def _parallel_assignments(
        self,
        assignments: tuple[StudyAssignment, ...],
        fn,
        *,
        batch_id: str,
        prepare=None,
    ) -> tuple[object, ...]:
        # One scheduler authority: the platform execution pool supplies the
        # mechanical frontier. Scientific Study code never caps repetitions or
        # assignments with machine-specific numbers. ResourceCompetition and
        # downstream resource leases remain free to admit fewer tasks at runtime.
        return self._parallel(
            assignments,
            fn,
            batch_id=batch_id,
            limit=min(self.frontier_capacity, max(1, len(assignments))),
            prepare=prepare,
        )

    def _execute_batch(self, batch: ExperimentBatch) -> tuple[StudyMetricObservation, ...]:
        plan = self.compiled.plan
        if batch.kind is ExperimentBatchKind.REPETITION_UNITS:
            units = tuple(self._units_by_repetition[row] for row in batch.unit_repetitions)

            def execute(unit: StudyExecutionUnit):
                bindings = tuple(self._binding_by_variant[row.variant_id] for row in unit.assignments)
                values = tuple(
                    self.adapter.execute_bound(
                        unit,
                        bindings,
                        plan.plan_digest,
                        execution_id=self.execution_id,
                    )
                )
                expected = {row.assignment_digest for row in unit.assignments}
                actual = tuple(row.assignment.assignment_digest for row in values)
                if len(actual) != len(set(actual)) or set(actual) != expected:
                    raise ValueError("experiment unit did not return exact assignment observations")
                return values

            def prepare_unit(unit: StudyExecutionUnit) -> None:
                if self._preparation is None:
                    return
                bindings = tuple(
                    self._binding_by_variant[row.variant_id]
                    for row in unit.assignments
                )
                self._preparation.prepare_bound(
                    unit,
                    bindings,
                    plan.plan_digest,
                    execution_id=self.execution_id,
                )

            groups = self._parallel(
                units,
                execute,
                batch_id=batch.batch_id,
                limit=self.frontier_capacity,
                prepare=(
                    prepare_unit
                    if self._preparation is not None
                    else None
                ),
            )
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
                execution_id=self.execution_id,
            )

        def prepare_variant(assignment: StudyAssignment) -> None:
            if self._preparation is None:
                return
            self._preparation.prepare_bound_variant(
                assignment,
                self._binding_by_variant[assignment.variant_id],
                plan.plan_digest,
                execution_id=self.execution_id,
            )

        observations = self._parallel_assignments(
            assignments,
            execute_variant,
            batch_id=batch.batch_id,
            prepare=(
                prepare_variant
                if self._preparation is not None
                else None
            ),
        )
        return tuple(observations)

    def open_session(
        self,
        *,
        journal: MachineJournalPort,
        snapshot_store: MachineSnapshotStorePort | None = None,
        machine_id: str | None = None,
    ) -> ResearchMachineSessionPort:
        host = ResearchProgramHost(
            host_id="experiment.program",
            program=self.compiled.program,
            journal=journal,
            snapshot_store=snapshot_store,
            base_handlers=self.handlers(),
            dependency_identity={
                "plan_digest": self.compiled.plan.plan_digest,
                "batch_plan_digest": self.compiled.batch_plan_digest,
                "protocol_digest": self.compiled.plan.protocol.protocol_digest,
                "execution_binding_digest": self.execution_binding_digest,
                "execution_id": self.execution_id,
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
                "execution_binding_digest": self.execution_binding_digest,
                "execution_id": self.execution_id,
            },
            binding=None,
        )

    def execute(
        self,
        *,
        journal: MachineJournalPort,
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
                detail = ""
                if run.status is MachineStatus.FAILED:
                    failure = session.semantic_state.get("program_failure")
                    if isinstance(failure, Mapping):
                        detail = (
                            f"; failure_code={failure.get('code')}"
                            f"; cursor={failure.get('cursor')}"
                            f"; visit={failure.get('visit')}"
                            f"; error_digest={failure.get('error_digest')}"
                            f"; message={failure.get('message')}"
                        )
                raise RuntimeError(
                    f"ExperimentProgram stopped with status={run.status.value}{detail}"
                )
        elif session.status is not MachineStatus.COMPLETED:
            raise RuntimeError(
                f"ExperimentProgram is not executable: status={session.status.value}"
            )
        # Every accepted ExperimentProgram transition is already durable in
        # the journal; automatic full-snapshot persistence here is redundant.
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
    if not isinstance(data, Mapping):
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
