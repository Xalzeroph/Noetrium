from __future__ import annotations

from contextlib import contextmanager

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
import time

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext, MachineJournalPort, MachineKind, MachineStatus, canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    ChildFailurePolicy,
    ChildResearchHostRegistry,
    ChildResearchMachineBatchItem,
    ChildResearchMachineBatchRequest,
    ChildResearchMachineRequest,
    ProgramNode,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram,
    ResearchProgramHost,
    execute_child_research_machine_batch,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodProgram, MethodRunStatus, analyze_method_runtime_requirements,
)
from noetrium_platform.research.execution.workflow.composition.program_lowering import (
    lower_method_program, method_program_lowering_digest, method_program_operations,
)
from noetrium_platform.research.execution.workflow.runtime import project_method_host_execution
from noetrium_platform.research.experimentation.lifecycle.api import (
    ExperimentTaskSpec, ParticipantSchedule,
)
from noetrium_platform.research.experimentation.workload.api import (
    WorkloadMethodReceipt,
    WorkloadTaskResult,
    workload_method_receipt_from_payload,
    workload_method_receipt_payload,
)
from noetrium_platform.research.experimentation.workload.composition.declarative import (
    MethodRuntimeBindings, TaskFieldProjection,
)

from .research_child_machine_batch import PooledChildResearchBatchMechanics
from .research_execution_pool import ResearchExecutionPool


@dataclass(frozen=True, slots=True)
class ParticipantMethodRuntime:
    role: str
    participant_kind: str
    treatment_id: str
    program: MethodProgram
    runtime: MethodRuntimeBindings
    _runtime_binding_digest: str = field(init=False, repr=False, compare=False)
    _lowered_program: ResearchProgram = field(init=False, repr=False, compare=False)
    _lowering_digest: str = field(init=False, repr=False, compare=False)
    _operations: tuple[ResearchHostOperation, ...] = field(
        init=False, repr=False, compare=False
    )
    _runtime_requirements: object = field(init=False, repr=False, compare=False)
    _identity_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.role) is not str or not self.role.strip():
            raise ValueError("participant Method role must be non-empty text")
        for name, value in (
            ("participant_kind", self.participant_kind),
            ("treatment_id", self.treatment_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"participant Method {name} must be non-empty text")
        if not isinstance(self.program, MethodProgram):
            raise TypeError("participant Method runtime requires MethodProgram")
        if not isinstance(self.runtime, MethodRuntimeBindings):
            raise TypeError("participant Method runtime requires MethodRuntimeBindings")
        runtime_binding_digest = self.runtime.resolved_runtime_binding_digest()
        lowered_program = lower_method_program(self.program)
        lowering_digest = method_program_lowering_digest(self.program)
        operations = method_program_operations(self.program)
        requirements = analyze_method_runtime_requirements(self.program)
        identity_digest = canonical_digest({
            "role": self.role,
            "participant_kind": self.participant_kind,
            "treatment_id": self.treatment_id,
            "method_program_digest": self.program.program_digest,
            "runtime_binding_digest": runtime_binding_digest,
        })
        object.__setattr__(
            self,
            "_runtime_binding_digest",
            runtime_binding_digest,
        )
        object.__setattr__(self, "_lowered_program", lowered_program)
        object.__setattr__(self, "_lowering_digest", lowering_digest)
        object.__setattr__(self, "_operations", operations)
        object.__setattr__(self, "_runtime_requirements", requirements)
        object.__setattr__(self, "_identity_digest", identity_digest)

    @property
    def identity_digest(self) -> str:
        return self._identity_digest


@dataclass(frozen=True, slots=True)
class _TaskBinding:
    task: ExperimentTaskSpec
    context: ExecutionContext
    task_input: object
    schedule: ParticipantSchedule
    executor: object
    mechanics: object
    requests: tuple[tuple[str, ChildResearchMachineRequest], ...]

    def request_for(
        self,
        role: str,
        *,
        participant_context: object | None = None,
        participant_context_digest: str | None = None,
    ) -> ChildResearchMachineRequest:
        base = None
        for candidate, request in self.requests:
            if candidate == role:
                base = request
                break
        if base is None:
            raise KeyError(role)
        context = {} if participant_context is None else participant_context
        if not isinstance(context, Mapping):
            raise TypeError("participant context must be an object")
        identity = dict(base.instance_identity)
        identity["participant_context"] = dict(context)
        resolved_context_digest = (
            canonical_digest(context)
            if participant_context_digest is None
            else participant_context_digest
        )
        identity["participant_context_digest"] = resolved_context_digest
        return replace(
            base,
            instance_identity=identity,
            failure_policy=ChildFailurePolicy.COLLECT,
        )


class ScheduledParticipantWorkloadBinding:
    """Compile one participant schedule onto the universal ResearchProgram Machine."""

    def __init__(
        self,
        *,
        schedule: ParticipantSchedule,
        participants: tuple[ParticipantMethodRuntime, ...],
        journal: MachineJournalPort,
        execution_pool: ResearchExecutionPool,
        input_projection: TaskFieldProjection | None = None,
        clock=time.monotonic,
    ) -> None:
        if not isinstance(schedule, ParticipantSchedule):
            raise TypeError("scheduled participant workload requires ParticipantSchedule")
        if type(participants) is not tuple or not participants or any(
            not isinstance(row, ParticipantMethodRuntime) for row in participants
        ):
            raise TypeError("scheduled participant workload requires participant runtimes")
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("scheduled participant workload requires MachineJournalPort")
        if not isinstance(execution_pool, ResearchExecutionPool):
            raise TypeError("scheduled participant workload requires ResearchExecutionPool")
        projection = TaskFieldProjection() if input_projection is None else input_projection
        if not isinstance(projection, TaskFieldProjection):
            raise TypeError("scheduled participant workload requires TaskFieldProjection")
        if not callable(clock):
            raise TypeError("scheduled participant workload clock must be callable")
        roles = tuple(row.role for row in participants)
        scheduled = tuple(role for wave in schedule.waves for role in wave)
        if len(roles) != len(set(roles)) or set(scheduled) != set(roles) or len(scheduled) != len(roles):
            raise ValueError("participant schedule coverage drifted from participant runtimes")

        self._schedule = schedule
        self._participants = tuple(sorted(participants, key=lambda row: row.role))
        self._by_role = {row.role: row for row in self._participants}
        self._journal = journal
        self._execution_pool = execution_pool
        self._input_projection = projection
        self._clock = clock
        self._program = self._build_program(schedule)
        self._host = ResearchProgramHost(
            host_id="workload:participant-schedule:" + schedule.schedule_digest[:24],
            program=self._program,
            operations=(ResearchHostOperation(
                "participant.wave",
                self._execute_wave,
                canonical_digest({
                    "operation": "participant.wave",
                    "version": 1,
                    "schedule_digest": schedule.schedule_digest,
                }),
            ),),
            journal=journal,
            max_steps=len(schedule.waves) + 1,
            dependency_identity={
                "schema": "noetrium.participant-scheduled-workload.v1",
                "schedule_digest": schedule.schedule_digest,
                "participants": tuple((row.role, row.identity_digest) for row in self._participants),
            },
        )
        self.identity_digest = canonical_digest({
            "binding": "participant-scheduled-workload.v1",
            "schedule_digest": schedule.schedule_digest,
            "participants": tuple((row.role, row.identity_digest) for row in self._participants),
            "program_digest": self._program.program_digest,
            "input_projection_digest": projection.digest,
        })

    @staticmethod
    def _build_program(schedule: ParticipantSchedule) -> ResearchProgram:
        nodes = []
        for index, wave in enumerate(schedule.waves):
            next_node = None if index + 1 == len(schedule.waves) else f"wave-{index + 1}"
            nodes.append(ProgramNode(
                node_id=f"wave-{index}",
                operation="participant.wave",
                configuration={"wave_index": index, "roles": wave},
                next_node=next_node,
                allowed_next_nodes=(() if next_node is None else (next_node,)),
                max_visits=1,
            ))
        return ResearchProgram(
            program_id="participant-schedule:" + schedule.schedule_digest,
            kind=MachineKind.PARTICIPANT,
            version="1",
            state_schema="noetrium.participant-schedule-state.v1",
            entrypoint="wave-0",
            nodes=tuple(nodes),
        )

    @staticmethod
    def _receipt(result) -> WorkloadMethodReceipt:
        return WorkloadMethodReceipt(
            run_id=result.run_id,
            program_digest=result.program_digest,
            run_digest=result.run_digest,
            status=result.status.value,
            step_count=result.step_count,
            evidence_status=result.evidence_status.value,
            evidence_reference=result.evidence_reference,
            failure_id=result.failure_id,
        )

    def _execute_wave(self, request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
        if not isinstance(binding, _TaskBinding):
            raise TypeError("participant wave requires task binding")
        raw_roles = request.node.configuration.get("roles")
        if not isinstance(raw_roles, (tuple, list)) or not raw_roles:
            raise TypeError("participant wave roles must be a non-empty sequence")
        roles = tuple(str(role) for role in raw_roles)
        prior = request.data.get("participants", {})
        if not isinstance(prior, Mapping):
            raise TypeError("participant parent state must contain an object")
        prior = dict(prior)
        prior_digest = canonical_digest(prior)
        wave_requests = {
            role: binding.request_for(
                role,
                participant_context=prior,
                participant_context_digest=prior_digest,
            )
            for role in roles
        }
        batch = ChildResearchMachineBatchRequest(
            batch_id=f"{request.snapshot.machine_id}:{request.node.node_id}:{canonical_digest(roles)[:16]}",
            parent_machine_id=request.snapshot.machine_id,
            selection_digest=canonical_digest({
                "schedule_digest": binding.schedule.schedule_digest,
                "wave": request.node.configuration,
                "task_id": binding.task.task_id,
                "participant_context_digest": prior_digest,
            }),
            items=tuple(
                ChildResearchMachineBatchItem(role, wave_requests[role])
                for role in roles
            ),
            dispatch_parallelism=len(roles),
        )
        execution = execute_child_research_machine_batch(
            binding.executor, binding.mechanics, batch
        )
        merged = dict(prior)
        failed = []
        evidence_refs = list(execution.evidence_digests)
        for role, child in zip(roles, execution.executions, strict=True):
            participant = self._by_role[role]
            child_request = wave_requests[role]
            runtime_context = binding.executor.registry.resolve(
                child_request.host_id
            ).binding_factory(child_request)
            result = project_method_host_execution(
                participant.program, runtime_context, child.execution
            )
            if result.evidence_reference is not None:
                evidence_refs.append(result.evidence_reference.reference_id)
            receipt = self._receipt(result)
            merged[role] = {
                "result": result.value,
                "state": result.state,
                "diagnostics": result.diagnostics,
                "status": result.status.value,
                "run_digest": result.run_digest,
                "machine_cut_digest": child.execution.cut.cut_digest,
                "receipt": workload_method_receipt_payload(receipt),
                "failure": result.failure,
                "failure_code": result.failure_code,
            }
            if result.status is not MethodRunStatus.SUCCEEDED:
                failed.append((role, result.failure or result.failure_code or result.status.value))
        terminal = request.node.next_node is None
        return ProgramNodeResult(
            value={"participants": merged},
            state_update={"participants": merged},
            status=(
                MachineStatus.FAILED if failed
                else MachineStatus.COMPLETED if terminal
                else None
            ),
            semantic_state_update={
                "participant_schedule_digest": binding.schedule.schedule_digest,
                "completed_wave": request.node.node_id,
                "failed_participants": tuple(failed),
            },
            events=({
                "type": "participant.wave.failed" if failed else "participant.wave.completed",
                "roles": roles,
                "batch_execution_digest": execution.execution_digest,
            },),
            evidence_refs=tuple(evidence_refs),
            child_links=execution.links,
        )

    def _task_binding(
        self,
        task: ExperimentTaskSpec,
        context: ExecutionContext,
        *,
        parent_machine_id: str,
    ) -> _TaskBinding:
        registry = ChildResearchHostRegistry()
        requests = []
        task_input = self._input_projection.project(task)
        max_steps = context.trial_budget.get("max_steps")
        resolved_max_steps = 10_000 if max_steps is None else int(max_steps)
        for participant in self._participants:
            binding_plan_digest = canonical_digest({
                "binding": "participant-method-invocation.v1",
                "workload_binding": self.identity_digest,
                "role": participant.role,
                "program_digest": participant.program.program_digest,
                "runtime_binding_digest": participant._runtime_binding_digest,
            })
            participant_context = replace(
                context,
                participant_context={
                    "role": participant.role,
                    "participant_kind": participant.participant_kind,
                    "treatment_id": participant.treatment_id,
                },
            )
            runtime_context, _task_root = participant.runtime.materialize_context(
                program=participant.program,
                task=task,
                context=participant_context,
                binding_plan_digest=binding_plan_digest,
                invocation_id=participant.role,
            )
            participant._runtime_requirements.require(runtime_context)
            lowered = participant._lowered_program
            host_id = f"participant:{participant.role}:{participant.program.program_identity.implementation.method_id}"
            host = ResearchProgramHost(
                host_id=host_id,
                program=lowered,
                operations=participant._operations,
                journal=self._journal,
                max_steps=resolved_max_steps,
                dependency_identity={
                    "schema": "noetrium.participant-method-child.v1",
                    "role": participant.role,
                    "participant_kind": participant.participant_kind,
                    "treatment_id": participant.treatment_id,
                    "method_program_digest": participant.program.program_digest,
                    "lowering_digest": participant._lowering_digest,
                    "binding_plan_digest": runtime_context.binding_plan_digest,
                    "runtime_binding_digest": runtime_context.effective_runtime_binding_digest,
                    "schema_digest": runtime_context.schema_digest,
                    "schedule_digest": self._schedule.schedule_digest,
                },
            )
            base_runtime_context = runtime_context

            def bind_participant_request(
                child_request: ChildResearchMachineRequest,
                *,
                _base=base_runtime_context,
            ):
                identity = child_request.instance_identity
                if not isinstance(identity, Mapping):
                    raise TypeError("participant child instance identity must be an object")
                participant_context = identity.get("participant_context", {})
                if not isinstance(participant_context, Mapping):
                    raise TypeError("participant child context identity must be an object")
                if identity.get("participant_context_digest") != canonical_digest(participant_context):
                    raise ValueError("participant child context identity digest drifted")
                return replace(
                    _base,
                    execution=replace(
                        _base.execution,
                        participant_context=dict(participant_context),
                    ),
                )

            registry.register(
                host,
                bind_participant_request,
                binding_factory_digest=canonical_digest({
                    "binding": "participant-method-runtime-context.v1",
                    "role": participant.role,
                    "binding_plan_digest": runtime_context.binding_plan_digest,
                    "runtime_binding_digest": runtime_context.effective_runtime_binding_digest,
                    "schema_digest": runtime_context.schema_digest,
                    "participant_context_semantics": "prior-schedule-waves",
                }),
            )
            child_machine_id = "participant:" + canonical_digest({
                "parent_machine_id": parent_machine_id,
                "role": participant.role,
                "task_id": task.task_id,
                "program_digest": participant.program.program_digest,
                "run_id": runtime_context.execution.run_id,
            })[:48]
            requests.append((participant.role, ChildResearchMachineRequest(
                host_id=host_id,
                parent_machine_id=parent_machine_id,
                child_machine_id=child_machine_id,
                instance_identity={
                    "schema": "noetrium.participant-method-instance.v1",
                    "role": participant.role,
                    "participant_kind": participant.participant_kind,
                    "treatment_id": participant.treatment_id,
                    "task_id": task.task_id,
                    "run_id": runtime_context.execution.run_id,
                    "method_program_digest": participant.program.program_digest,
                    "lowered_program_digest": lowered.program_digest,
                    "binding_plan_digest": runtime_context.binding_plan_digest,
                    "runtime_binding_digest": runtime_context.effective_runtime_binding_digest,
                    "schema_digest": runtime_context.schema_digest,
                    "assignment_seed": context.assignment_seed,
                    "intervention_values": context.intervention_values,
                    "replay_level": context.replay_level,
                },
                initial_data={},
                payload=task_input,
                failure_policy=ChildFailurePolicy.COLLECT,
                command_id_prefix=f"{parent_machine_id}:{participant.role}",
            )))
        executor = registry.executor()
        mechanics = PooledChildResearchBatchMechanics(
            executor, execution_pool=self._execution_pool
        )
        return _TaskBinding(
            task=task,
            context=context,
            task_input=task_input,
            schedule=self._schedule,
            executor=executor,
            mechanics=mechanics,
            requests=tuple(requests),
        )

    @contextmanager
    def task_group_scope(self, context: ExecutionContext):
        if not isinstance(context, ExecutionContext):
            raise TypeError(
                "participant workload task-group scope requires ExecutionContext"
            )
        group = self._execution_pool.open_machine_group(
            "workload-dag:"
            + canonical_digest({
                "run_id": context.run_id,
                "lifetime_id": context.lifetime_id,
                "span_id": context.span_id,
                "schedule_digest": self._schedule.schedule_digest,
            })[:32],
            resource_id="workload-dag:" + self._schedule.schedule_digest[:24],
        )
        completed = False
        try:
            yield group
            completed = True
        finally:
            self._execution_pool.close_machine_group(
                group,
                cancel_pending=not completed,
            )

    def execute_one(self, task: ExperimentTaskSpec, context: ExecutionContext) -> WorkloadTaskResult:
        if not isinstance(task, ExperimentTaskSpec):
            raise TypeError("participant workload task must be ExperimentTaskSpec")
        if not isinstance(context, ExecutionContext):
            raise TypeError("participant workload context must be ExecutionContext")
        started = self._clock()
        parent_machine_id = "participant-workload:" + canonical_digest({
            "run_id": context.run_id,
            "lifetime_id": context.lifetime_id,
            "task_id": task.task_id,
            "schedule_digest": self._schedule.schedule_digest,
            "binding_digest": self.identity_digest,
        })[:48]
        binding = self._task_binding(task, context, parent_machine_id=parent_machine_id)
        execution = self._host.execute(
            machine_id=parent_machine_id,
            instance_identity={
                "schema": "noetrium.participant-workload-instance.v1",
                "task_id": task.task_id,
                "lineage_id": task.lineage_id,
                "run_id": context.run_id,
                "lifetime_id": context.lifetime_id,
                "schedule_digest": self._schedule.schedule_digest,
                "assignment_seed": context.assignment_seed,
                "intervention_values": context.intervention_values,
                "replay_level": context.replay_level,
                "trial_budget": context.trial_budget,
            },
            binding=binding,
            initial_data={"participants": {}},
            payload=binding.task_input,
            command_id_prefix=parent_machine_id,
        )
        completed = execution.data.get("participants", {})
        if not isinstance(completed, Mapping):
            raise TypeError("participant parent result must contain an object")
        completed_roles = set(completed)
        projected = []
        for participant in self._participants:
            if participant.role not in completed_roles:
                continue
            row = completed[participant.role]
            if not isinstance(row, Mapping):
                raise TypeError("participant parent result row must be an object")
            receipt = workload_method_receipt_from_payload(row["receipt"])
            projected.append((participant.role, receipt, row))
        receipts = tuple(sorted(
            (role, receipt) for role, receipt, _row in projected
        ))
        success = (
            execution.status is MachineStatus.COMPLETED
            and len(projected) == len(self._participants)
            and all(
                receipt.status == MethodRunStatus.SUCCEEDED.value
                for _role, receipt, _row in projected
            )
        )
        failures = tuple(
            (
                role,
                row.get("failure")
                or row.get("failure_code")
                or receipt.status,
            )
            for role, receipt, row in projected
            if receipt.status != MethodRunStatus.SUCCEEDED.value
        )
        duration = self._clock() - started
        return WorkloadTaskResult(
            task_id=task.task_id,
            family=task.family,
            success=success,
            utility=1.0 if success else 0.0,
            steps=sum(receipt.step_count for _, receipt, _ in projected),
            duration_s=duration,
            lineage_id=task.lineage_id,
            failure_reason=(
                "" if success
                else repr(failures) if failures
                else f"participant parent machine stopped with {execution.status.value}"
            ),
            participant_receipts=receipts,
            failure_scope=("task" if success else "branch"),
            diagnostics={
                "participant_schedule_digest": self._schedule.schedule_digest,
                "participant_parent_program_digest": self._program.program_digest,
                "participant_parent_machine_cut_digest": (
                    None if execution.cut is None else execution.cut.cut_digest
                ),
                "participant_child_machine_cuts": tuple(
                    (role, str(row["machine_cut_digest"]))
                    for role, _receipt, row in projected
                ),
            },
            exports={
                "participants": {
                    role: {
                        "result": row.get("result"),
                        "state": row.get("state"),
                        "diagnostics": row.get("diagnostics", {}),
                    }
                    for role, _receipt, row in projected
                }
            },
        )


__all__ = ["ParticipantMethodRuntime", "ScheduledParticipantWorkloadBinding"]
