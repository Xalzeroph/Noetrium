from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.universal import UnitStepContext, UnitTransition

from noetrium_platform.foundation.kernel.kernel.unit_host import BoundExecutableUnit

from noetrium_platform.foundation.kernel.kernel.unit_driver import UnitExecutionDriverPort

from noetrium_platform.foundation.kernel.structure import relation_unit, structure_unit
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    require_study_execution_plan,
    study_plan_protocol,
    study_plan_binding_at,
    study_plan_assignment_count,
    study_plan_assignment_at,
    iter_study_plan_assignment_range,
    study_plan_assignment_digest,
    study_plan_digest,
    study_plan_binding_digest,
    study_protocol_text,
    study_protocol_digest,
    study_assignment_text,
    study_assignment_variant_index,
    study_assignment_repetition,
    study_assignment_workload,
    study_assignment_digest,
    study_assignment,
    assignment_workload_digest,
    assignment_workload_task_ids,
    assignment_workload,
    assignment_workload_dependencies_for,
    assignment_workload_prerequisites_for,
    assignment_workload_retry_sources_for,
    validate_assignment_workload,
    BoundStudyExecutionPort,
    StudyExecutionUnit,
    StudyMatrixExecutionReport,
    StudyMetricAggregate,
    StudyMetricObservation,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.research.experimentation.lifecycle.study.api.contracts import (
    study_protocol_assignment_relations,
    study_protocol_workloads,
)
from noetrium_platform.research.experimentation.projection import evaluate_study_metric_aggregates
"""study execution graph -> ExperimentProgram compilation and execution.

The Experiment Machine owns one completion-driven scheduling frontier. Child
Trial/Workload Machines remain the durable unit of physical work, so replay can
reuse completed assignments while the parent keeps all declared concurrency
slots saturated instead of imposing fixed wave barriers.
"""


from noetrium_platform.foundation.kernel.structure import NoetriumUnit, NoetriumUnit

from noetrium_platform.research.experimentation.lifecycle.study.api.benchmark import (
    TaskRelation,
    task_graph,
    task_graph_relation,
    task_graph_relation_kind,
    task_graph_relation_source_id,
    task_graph_relation_target_id,
    validate_task_graph,
)


from collections.abc import Mapping
from dataclasses import dataclass
from queue import Queue

from uuid import uuid4


from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionControlPort,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.kernel import (
    unit_execution_failure,
    ExecutionContext,
    execution_context_scope,
    JsonObject,
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.research.execution.api import scope_from_data, scope_to_data, ArtifactReference, NoetriumUnit, ScopeKind, scope_unit, ExperimentConcern, unit_flow, unit_operation, executable_unit, UnitOperationRegistry, executable_unit_required_capabilities


@dataclass(frozen=True, slots=True)
class ExperimentBatch:
    """One symbolic contiguous range in the canonical assignment matrix."""

    batch_id: str
    assignment_start: int
    assignment_stop: int
    assignment_matrix_digest: str
    batch_digest: str

    @classmethod
    def create(
        cls,
        *,
        batch_id: str,
        assignment_start: int,
        assignment_stop: int,
        assignment_matrix_digest: str,
    ) -> "ExperimentBatch":
        batch_digest = canonical_digest(
            {
                "batch_id": batch_id,
                "assignment_start": assignment_start,
                "assignment_stop": assignment_stop,
                "assignment_matrix_digest": assignment_matrix_digest,
            }
        )
        return cls(
            batch_id,
            assignment_start,
            assignment_stop,
            assignment_matrix_digest,
            batch_digest,
        )

    def __post_init__(self) -> None:
        if type(self.batch_id) is not str or not self.batch_id.strip():
            raise ValueError("experiment batch_id is required")
        if (
            type(self.assignment_start) is not int
            or type(self.assignment_stop) is not int
            or self.assignment_start < 0
            or self.assignment_stop <= self.assignment_start
        ):
            raise ValueError("experiment batch requires a non-empty assignment range")
        require_sha256(
            self.assignment_matrix_digest,
            "experiment batch assignment_matrix_digest",
        )
        expected = canonical_digest(
            {
                "batch_id": self.batch_id,
                "assignment_start": self.assignment_start,
                "assignment_stop": self.assignment_stop,
                "assignment_matrix_digest": self.assignment_matrix_digest,
            }
        )
        if self.batch_digest != expected:
            raise ValueError("experiment batch digest mismatch")

    @property
    def assignment_count(self) -> int:
        return self.assignment_stop - self.assignment_start


EXPERIMENT_COMPILATION_TRAIT = "experiment.compilation"

def experiment_compilation_graph(
    plan: NoetriumUnit,
    execution_graph: NoetriumUnit,
    batches: tuple[ExperimentBatch, ...],
) -> NoetriumUnit:
    require_study_execution_plan(plan)
    if type(execution_graph) is not NoetriumUnit:
        raise TypeError("experiment execution graph must be NoetriumUnit")
    if type(batches) is not tuple or len(batches) != 1:
        raise ValueError("experiment compilation requires exactly one symbolic frontier batch")
    batch = batches[0]
    if (
        batch.assignment_start != 0
        or batch.assignment_stop != study_plan_assignment_count(plan)
        or batch.assignment_matrix_digest != study_plan_assignment_digest(plan)
    ):
        raise ValueError("experiment frontier batch must exactly cover assignment matrix")
    members = (
        structure_unit(
            "study-plan",
            traits=("experiment.study-plan",),
            members=(plan,),
        ),
        structure_unit(
            "execution",
            traits=("experiment.execution",),
            members=(execution_graph,),
        ),
        structure_unit(
            "batch:0",
            traits=("experiment.batch",),
            parameters={
                "batch_id": batch.batch_id,
                "assignment_start": batch.assignment_start,
                "assignment_stop": batch.assignment_stop,
                "assignment_matrix_digest": batch.assignment_matrix_digest,
                "batch_digest": batch.batch_digest,
            },
        ),
    )
    return structure_unit(
        "experiment-compilation:"
        + canonical_digest(
            (plan.semantic_digest, execution_graph.semantic_digest, batch.batch_digest)
        )[:20],
        traits=(EXPERIMENT_COMPILATION_TRAIT,),
        parameters={"batch_count": 1},
        members=members,
    )

def require_experiment_compilation(g:NoetriumUnit)->NoetriumUnit:
    if type(g) is not NoetriumUnit or not g.has_trait(EXPERIMENT_COMPILATION_TRAIT): raise TypeError("experiment compilation must be NoetriumUnit")
    return g
def experiment_compilation_plan(g:NoetriumUnit)->NoetriumUnit: require_experiment_compilation(g); return g.member("study-plan").members[0]
def experiment_compilation_execution_graph(g:NoetriumUnit)->NoetriumUnit: require_experiment_compilation(g); return g.member("execution").members[0]
def experiment_compilation_batches(g: NoetriumUnit) -> tuple[ExperimentBatch, ...]:
    require_experiment_compilation(g)
    if int(g.parameters["batch_count"]) != 1:
        raise ValueError("experiment compilation must contain one symbolic frontier")
    p = g.member("batch:0").parameters
    return (
        ExperimentBatch(
            str(p["batch_id"]),
            int(p["assignment_start"]),
            int(p["assignment_stop"]),
            str(p["assignment_matrix_digest"]),
            str(p["batch_digest"]),
        ),
    )


def experiment_compilation_batch_digest(g: NoetriumUnit) -> str:
    return experiment_compilation_batches(g)[0].batch_digest


def experiment_compilation_initial_data(g: NoetriumUnit) -> JsonObject:
    return {
        "plan_digest": study_plan_digest(experiment_compilation_plan(g)),
        "batch_plan_digest": experiment_compilation_batch_digest(g),
        "assignment_cursor": 0,
        "assignment_completed_sparse": (),
        "aggregates": (),
    }


def _compile_batches(plan: NoetriumUnit) -> tuple[ExperimentBatch, ...]:
    count = study_plan_assignment_count(plan)
    if count <= 0:
        return ()
    return (
        ExperimentBatch.create(
            batch_id="frontier",
            assignment_start=0,
            assignment_stop=count,
            assignment_matrix_digest=study_plan_assignment_digest(plan),
        ),
    )


def compile_experiment_program(plan: NoetriumUnit) -> NoetriumUnit:
    if type(plan) is not NoetriumUnit:
        raise TypeError("compile_experiment_program requires study execution graph")
    require_study_execution_plan(plan)
    batches = _compile_batches(plan)
    if not batches:
        raise ValueError("experiment plan compiled to no execution batches")
    batch_plan_digest = canonical_digest(tuple(batch.batch_digest for batch in batches))
    common = {
        "plan_digest": study_plan_digest(plan),
        "batch_plan_digest": batch_plan_digest,
    }
    program = executable_unit(
        f"experiment:{study_protocol_text(study_plan_protocol(plan), 'study_id')}",
        domain="experiment",
        version="1",
        state_schema="experiment.unit-state.v2",
        entrypoint="advance",
        members=(
            unit_operation(
                "advance",
                "experiment.execute_batch",
                configuration={
                    **common,
                    "experiment_concern": ExperimentConcern.SCHEDULING.value,
                },
            ),
            unit_operation(
                "aggregate",
                "experiment.aggregate",
                configuration={
                    **common,
                    "experiment_concern": ExperimentConcern.AGGREGATION.value,
                },
            ),
        ),
        relations=(
            unit_flow("advance", "advance", default=True),
            unit_flow("advance", "aggregate", default=False),
        ),
    )
    return experiment_compilation_graph(plan, program, batches)


def _artifact_reference_json(reference: ArtifactReference) -> JsonObject:
    return {
        "reference_id": reference.reference_id,
        "scope": scope_to_data(reference.scope),
        "artifact_id": reference.artifact_id,
        "generation": reference.generation,
    }


def _artifact_reference_from_json(value: object) -> ArtifactReference:
    if not isinstance(value, Mapping):
        raise TypeError("experiment artifact reference state must be an object")
    return ArtifactReference(
        str(value["reference_id"]),
        scope_from_data(value["scope"]),
        str(value["artifact_id"]),
        int(value["generation"]),
    )


def _observation_json(observation: StudyMetricObservation) -> JsonObject:
    assignment = observation.assignment
    return {
        "study_id": study_assignment_text(assignment, "study_id"),
        "variant_id": study_assignment_text(assignment, "variant_id"),
        "variant_index": study_assignment_variant_index(assignment),
        "repetition": study_assignment_repetition(assignment),
        "seed": study_assignment_text(assignment, "seed"),
        "workload": {
            "task_ids": assignment_workload_task_ids(study_assignment_workload(assignment)),
            "task_graph_edges": tuple(
                (
                    task_graph_relation_source_id(edge),
                    task_graph_relation_target_id(edge),
                    task_graph_relation_kind(edge).value,
                )
                for edge in study_assignment_workload(assignment).relations
            ),
            "workload_digest": assignment_workload_digest(study_assignment_workload(assignment)),
        },
        "assignment_digest": study_assignment_digest(assignment),
        "metrics": tuple((name, float(value)) for name, value in observation.metrics),
        "unobserved_metric_names": observation.unobserved_metric_names,
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
    workload = assignment_workload(
        tuple(str(task_id) for task_id in task_ids_value),
        task_graph(
            tuple(
                task_graph_relation(
                    str(row[0]),
                    str(row[1]),
                    TaskRelation(str(row[2])),
                )
                for row in edges_value
            )
        ),
    )
    if assignment_workload_digest(workload) != workload_value.get("workload_digest"):
        raise ValueError("experiment observation workload digest mismatch")
    assignment = study_assignment(
        study_id=value["study_id"],
        variant_id=value["variant_id"],
        variant_index=value["variant_index"],
        repetition=value["repetition"],
        seed=value["seed"],
        workload=workload,
    )
    if study_assignment_digest(assignment) != value.get("assignment_digest"):
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
        unobserved_metric_names=tuple(value.get("unobserved_metric_names", ())),
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


_OBSERVATION_ITEM_PREFIX = "observation-item:"


def _observation_item_key(index: int) -> str:
    if type(index) is not int or index < 0:
        raise ValueError("experiment observation index must be non-negative")
    return f"{_OBSERVATION_ITEM_PREFIX}{index}"


def _encoded_observation_rows(data: Mapping[str, object]) -> tuple[JsonObject, ...]:
    rows: list[tuple[int, JsonObject]] = []
    for key, value in data.items():
        if not isinstance(key, str) or not key.startswith(_OBSERVATION_ITEM_PREFIX):
            continue
        suffix = key[len(_OBSERVATION_ITEM_PREFIX):]
        if not suffix.isdigit():
            raise ValueError("experiment observation item key is not canonical")
        if not isinstance(value, Mapping):
            raise TypeError("experiment observation item must be an object")
        rows.append((int(suffix), dict(value)))
    rows.sort(key=lambda item: item[0])
    for expected, (index, _row) in enumerate(rows):
        if index != expected:
            raise ValueError(
                "experiment observation items are not contiguous: "
                f"expected_index={expected} observed_index={index}"
            )
    return tuple(row for _index, row in rows)


def _ready_assignment_indexes(
    protocol: NoetriumUnit,
    *,
    total: int,
    completed_prefix: int,
    completed_sparse: set[int],
    active_indexes: set[int],
) -> tuple[int, ...]:
    """Project one immutable Study dependency graph onto live assignment cohorts.

    Cohort = (repetition, seed, variant); each retains its own causal chain.
    Predecessor *settlement*, including a scientifically failed task, is the
    ordering event. Neither source and target share physical environment
    lifetime nor are unrelated cohorts serialized.
    """
    workloads = study_protocol_workloads(protocol)
    n = len(workloads)
    if total % n:
        raise ValueError("Experiment assignment count does not match Study workloads")
    preceding: dict[int, set[int]] = {}
    for source, target, relation in study_protocol_assignment_relations(protocol):
        if relation != "sequence_after":
            raise ValueError("Unsupported Study causal assignment relation")
        preceding.setdefault(target, set()).add(source)
    return tuple(
        index for index in range(completed_prefix, total)
        if index not in completed_sparse
        and index not in active_indexes
        and all(
            (index - index % n + source) < completed_prefix
            or (index - index % n + source) in completed_sparse
            for source in preceding.get(index % n, ())
        )
    )


class ExperimentProgramBinding:
    """Runtime binding for one immutable compiled experiment program."""

    def __init__(
        self,
        compiled: NoetriumUnit,
        adapter: BoundStudyExecutionPort,
        *,
        execution_binding_digest: str,
        execution_context: ExecutionContext,
        execution_control: ExecutionControlPort,
        task_group: TaskGroupPort | None = None,
    ) -> None:
        if not type(compiled) is NoetriumUnit:
            raise TypeError("experiment binding requires experiment compilation graph")
        if not isinstance(adapter, BoundStudyExecutionPort):
            raise TypeError("experiment binding requires BoundStudyExecutionPort")
        require_sha256(
            execution_binding_digest,
            "experiment execution_binding_digest",
        )
        if not isinstance(execution_context, ExecutionContext):
            raise TypeError("experiment execution_context must be ExecutionContext")
        if not isinstance(execution_control, ExecutionControlPort):
            raise TypeError("experiment execution_control must be ExecutionControlPort")
        require_sha256(
            execution_context.run_id,
            "experiment execution run_id",
        )
        self.compiled = compiled
        self._study_protocol = study_plan_protocol(experiment_compilation_plan(compiled))
        self.adapter = adapter
        self.execution_binding_digest = execution_binding_digest
        self.execution_context = execution_context
        self.execution_control = execution_control
        self.task_group = task_group
        self._frontier_completion: Queue[int] = Queue()
        self._frontier_active: dict[int, object] = {}
        self._frontier_invocation = uuid4().hex


    @staticmethod
    def _completion_state(
        data: Mapping[str, object],
        *,
        total: int,
    ) -> tuple[int, set[int]]:
        cursor = data.get("assignment_cursor", 0)
        if type(cursor) is not int or cursor < 0 or cursor > total:
            raise ValueError("experiment assignment cursor is invalid")
        raw_sparse = data.get("assignment_completed_sparse", ())
        if not isinstance(raw_sparse, (tuple, list)):
            raise TypeError(
                "experiment assignment_completed_sparse must be a sequence"
            )
        sparse: set[int] = set()
        for value in raw_sparse:
            if type(value) is not int:
                raise TypeError(
                    "experiment sparse completion index must be integer"
                )
            if value < cursor or value >= total:
                raise ValueError(
                    "experiment sparse completion index is outside live suffix"
                )
            if value in sparse:
                raise ValueError(
                    "experiment sparse completion indices must be unique"
                )
            sparse.add(value)
        return cursor, sparse

    def _execute_assignment(
        self,
        index: int,
    ) -> tuple[str, StudyMetricObservation]:
        plan = experiment_compilation_plan(self.compiled)
        assignment = study_plan_assignment_at(plan, index)
        observed = self.adapter.execute_bound_variant(
            assignment,
            study_plan_binding_at(
                plan,
                study_assignment_variant_index(assignment),
            ),
            study_plan_digest(plan),
            execution_context=self.execution_context,
            control=self.execution_control,
        )
        expected_digest = study_assignment_digest(assignment)
        if study_assignment_digest(observed.assignment) != expected_digest:
            raise ValueError(
                "experiment assignment observation identity mismatch"
            )
        return expected_digest, observed

    def _submit_assignment(self, index: int, *, block: bool) -> bool:
        if self.task_group is None:
            raise RuntimeError(
                "experiment concurrent frontier requires TaskGroupPort"
            )

        def run(_context, owned_index=index):
            try:
                with execution_context_scope(self.execution_context):
                    return self._execute_assignment(owned_index)
            finally:
                self._frontier_completion.put(owned_index)

        spec = ExecutionSpec(
            task_id=(
                f"experiment:assignment:{self._frontier_invocation}:{index}"
            ),
            lane_kind=ExecutionLaneKind.BLOCKING_IO,
            failure_scope=TaskFailureScope.CALLER,
        )
        handle = (
            self.task_group.submit(spec, run)
            if block
            else self.task_group.try_submit(spec, run)
        )
        if handle is None:
            return False
        self._frontier_active[index] = handle
        return True

    def _refill_frontier(
        self,
        *,
        total: int,
        completed_prefix: int,
        completed_sparse: set[int],
    ) -> None:
        if self.task_group is None:
            return
        ready = _ready_assignment_indexes(
            self._study_protocol,
            total=total,
            completed_prefix=completed_prefix,
            completed_sparse=completed_sparse,
            active_indexes=set(self._frontier_active),
        )
        for index in ready:
            # Admission and capacity belong solely to the shared task group.
            if not self._submit_assignment(index, block=not self._frontier_active):
                return

    def _abort_frontier(self, primary: BaseException) -> None:
        remaining = tuple(self._frontier_active.values())
        convergence_errors: list[BaseException] = []
        for handle in remaining:
            try:
                handle.cancel()
            except BaseException as exc:
                convergence_errors.append(exc)
        for handle in remaining:
            try:
                handle.result()
            except BaseException:
                pass
        self._frontier_active.clear()
        if convergence_errors:
            raise ExceptionGroup(
                "experiment assignment frontier abort convergence failed",
                [primary, *convergence_errors],
            ) from primary
        raise primary

    def _next_completed_assignment(
        self,
        *,
        total: int,
        completed_prefix: int,
        completed_sparse: set[int],
    ) -> tuple[int, StudyMetricObservation]:
        if self.task_group is None:
            index = completed_prefix
            while index < total and index in completed_sparse:
                index += 1
            if index >= total:
                raise RuntimeError(
                    "experiment completion frontier has no remaining assignment"
                )
            _digest, observation = self._execute_assignment(index)
            return index, observation

        self._refill_frontier(
            total=total,
            completed_prefix=completed_prefix,
            completed_sparse=completed_sparse,
        )
        if not self._frontier_active:
            raise RuntimeError(
                "experiment completion frontier could not admit remaining work"
            )

        index = self._frontier_completion.get()
        handle = self._frontier_active.pop(index)
        try:
            _digest, observation = handle.result()
        except BaseException as exc:
            self._abort_frontier(exc)
            raise AssertionError("unreachable")

        return index, observation

    def open_driver(
        self,
        *,
        journal: MachineJournalPort,
        snapshot_store: MachineSnapshotStorePort | None = None,
        machine_id: str | None = None,
    ) -> UnitExecutionDriverPort:
        plan = experiment_compilation_plan(self.compiled)
        host = BoundExecutableUnit(
            host_id="experiment.program",
            unit=experiment_compilation_execution_graph(self.compiled),
            journal=journal,
            snapshot_store=snapshot_store,
            base_handlers=self.handlers(),
            dependency_identity={
                "plan_digest": study_plan_digest(experiment_compilation_plan(self.compiled)),
                "batch_plan_digest": experiment_compilation_batch_digest(self.compiled),
                "protocol_digest": study_protocol_digest(study_plan_protocol(plan)),
                "execution_binding_digest": self.execution_binding_digest,
                "execution_id": self.execution_context.run_id,
                "required_capabilities": executable_unit_required_capabilities(experiment_compilation_execution_graph(self.compiled)),
                "batches": tuple(
                    row.batch_digest for row in experiment_compilation_batches(self.compiled)
                ),
            },
        )
        resolved_machine_id = (
            machine_id
            or f"experiment:{study_protocol_text(study_plan_protocol(plan), "study_id")}:"
            f"{study_plan_digest(experiment_compilation_plan(self.compiled))[:16]}"
        )
        return host.open_driver(
            machine_id=resolved_machine_id,
            instance_identity={
                "plan_digest": study_plan_digest(experiment_compilation_plan(self.compiled)),
                "binding_digest": study_plan_binding_digest(experiment_compilation_plan(self.compiled)),
                "batch_plan_digest": experiment_compilation_batch_digest(self.compiled),
                "execution_binding_digest": self.execution_binding_digest,
                "execution_id": self.execution_context.run_id,
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
        session = self.open_driver(
            journal=journal,
            snapshot_store=snapshot_store,
            machine_id=machine_id,
        )
        if not session.started:
            session.start(
                experiment_compilation_initial_data(self.compiled),
                command_id=f"{session.machine_id}:start",
            )
        if session.status is MachineStatus.RUNNABLE:
            run = session.run_until_blocked(
                command_id_prefix=f"{session.machine_id}:drive",
                max_steps=(
                    study_plan_assignment_count(
                        experiment_compilation_plan(self.compiled)
                    )
                    + 2
                ),
            )
            if run.status is MachineStatus.FAILED:
                raise unit_execution_failure(
                    session.semantic_state,
                    surface="ExperimentProgram",
                )
            if run.status is not MachineStatus.COMPLETED:
                raise RuntimeError(
                    f"ExperimentProgram stopped with status={run.status.value}"
                )
        elif session.status is MachineStatus.FAILED:
            raise unit_execution_failure(
                session.semantic_state,
                surface="ExperimentProgram",
            )
        elif session.status is not MachineStatus.COMPLETED:
            raise RuntimeError(
                f"ExperimentProgram is not executable: status={session.status.value}"
            )
        # Every accepted ExperimentProgram transition is already durable in
        # the journal; automatic full-snapshot persistence here is redundant.
        return experiment_report_from_data(self.compiled, session.data)

    def handlers(self) -> UnitOperationRegistry:
        registry = UnitOperationRegistry.empty()

        def execute_batch(request: UnitStepContext) -> UnitTransition:
            data = request.data
            plan = experiment_compilation_plan(self.compiled)
            if data.get("plan_digest") != study_plan_digest(plan):
                raise ValueError("experiment Program state plan digest drift")
            if data.get("batch_plan_digest") != experiment_compilation_batch_digest(self.compiled):
                raise ValueError("experiment Program state batch plan drift")
            total = study_plan_assignment_count(plan)
            cursor, sparse = self._completion_state(data, total=total)
            if cursor == total and not sparse:
                return UnitTransition.goto("aggregate")

            index, observation = self._next_completed_assignment(
                total=total,
                completed_prefix=cursor,
                completed_sparse=sparse,
            )
            item_key = _observation_item_key(index)
            if item_key in data:
                raise ValueError(
                    "experiment observation item already exists for assignment"
                )

            if index == cursor:
                cursor += 1
                while cursor in sparse:
                    sparse.remove(cursor)
                    cursor += 1
            else:
                sparse.add(index)

            completed = cursor == total and not sparse
            return UnitTransition.goto(
                "aggregate" if completed else "advance",
                value={
                    "assignment_index": index,
                    "assignment_digest": study_assignment_digest(
                        observation.assignment
                    ),
                    "assignment_matrix_digest": study_plan_assignment_digest(plan),
                },
                state_delta={
                    "assignment_cursor": cursor,
                    "assignment_completed_sparse": tuple(sorted(sparse)),
                    item_key: _observation_json(observation),
                },
                events=(
                    {
                        "type": "experiment_assignment_completed",
                        "assignment_index": index,
                        "assignment_cursor": cursor,
                        "remaining_sparse": len(sparse),
                    },
                ),
            )

        def aggregate(request: UnitStepContext) -> UnitTransition:
            plan = experiment_compilation_plan(self.compiled)
            encoded_rows = _encoded_observation_rows(request.data)
            observations = tuple(
                _observation_from_json(row) for row in encoded_rows
            )
            expected_count = study_plan_assignment_count(plan)
            if len(observations) != expected_count:
                raise ValueError("experiment cannot aggregate incomplete observations")
            for index, observation in enumerate(observations):
                expected = study_plan_assignment_at(plan, index)
                if (
                    study_assignment_digest(observation.assignment)
                    != study_assignment_digest(expected)
                ):
                    raise ValueError(
                        "experiment observations drifted from canonical assignment order"
                    )
            aggregates = evaluate_study_metric_aggregates(
                study_plan_protocol(plan),
                observations,
                expected_assignment_count=expected_count,
            )
            report_digest = canonical_digest({
                "plan_digest": study_plan_digest(plan),
                "observations": encoded_rows,
                "aggregates": tuple(_aggregate_json(row) for row in aggregates),
            })
            return UnitTransition.halt(
                value={"report_digest": report_digest},
                state_delta={
                    "aggregates": tuple(_aggregate_json(row) for row in aggregates),
                    "report_digest": report_digest,
                },
                events=(
                    {
                        "type": "experiment_aggregated",
                        "report_digest": report_digest,
                        "observation_count": len(observations),
                        "aggregate_count": len(aggregates),
                    },
                ),
            )

        registry.register(
            "experiment.execute_batch",
            execute_batch,
            implementation_digest=canonical_digest({
                "operation": "experiment.execute_batch",
                "implementation_revision": 3,
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
    compiled: NoetriumUnit,
    data: object,
) -> StudyMatrixExecutionReport:
    plan = experiment_compilation_plan(compiled)
    if not isinstance(data, Mapping):
        raise TypeError("experiment Program data must be an object")
    if data.get("plan_digest") != study_plan_digest(experiment_compilation_plan(compiled)):
        raise ValueError("experiment report state belongs to another plan")
    observations = tuple(
        _observation_from_json(row) for row in _encoded_observation_rows(data)
    )
    aggregates = tuple(_aggregate_from_json(row) for row in data.get("aggregates", ()))
    if not aggregates:
        raise ValueError("experiment Program has not completed aggregation")
    return StudyMatrixExecutionReport(
        study_protocol_digest(study_plan_protocol(plan)),
        observations,
        aggregates,
        binding_digest=study_plan_binding_digest(experiment_compilation_plan(compiled)),
        plan_digest=study_plan_digest(experiment_compilation_plan(compiled)),
    )


__all__ = [
    "EXPERIMENT_COMPILATION_TRAIT", "experiment_compilation_graph", "require_experiment_compilation", "experiment_compilation_plan", "experiment_compilation_execution_graph", "experiment_compilation_batches", "experiment_compilation_batch_digest", "experiment_compilation_initial_data",
    "ExperimentBatch",
    "ExperimentProgramBinding",
    "compile_experiment_program",
    "experiment_report_from_data",
]
