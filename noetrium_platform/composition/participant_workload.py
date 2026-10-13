from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.universal import (
    UNIT_STATE_KEY, unit_operation_next_node,
)

from contextlib import contextmanager

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
import time

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext, MachineJournalPort, MachineStatus, canonical_digest,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionControlPort,
    SingleFlightCache,
    TaskDeadlineExceeded,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel.unit_activation import (
    UnitActivationFailurePolicy,
    UnitActivationRegistry,
    UnitActivationRequest,
)
from noetrium_platform.foundation.kernel.kernel.unit_activation_batch import (
    UnitActivationBatchItem,
    UnitActivationBatchRequest,
    execute_unit_activation_batch,
)
from noetrium_platform.foundation.kernel.kernel.unit_host import (
    BoundExecutableUnit,
    UnitOperationBinding,
)
from noetrium_platform.foundation.kernel.kernel.universal import (
    UnitStepContext,
    UnitTransition,
    executable_unit,
    unit_flow,
    unit_operation,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodRunStatus, analyze_method_runtime_requirements, method_program_identity,
)
from noetrium_platform.research.execution.workflow.runtime.program_lowering import (
    method_program_operations,
)
from noetrium_platform.research.execution.workflow.runtime import (
    project_method_accepted_evidence, project_method_host_execution,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    participant_schedule_digest,
    participant_schedule_waves,
    require_task_unit,
    task_family,
    task_id,
    task_lineage_id,
    task_payload,
)
from noetrium_platform.research.experimentation.workload.api import (
    WorkloadMethodReceipt,
    WorkloadTaskDeadlineExceeded,
    WorkloadTaskPartialMeasurement,
    WorkloadTaskResult,
    workload_method_receipt_from_payload,
    workload_method_receipt_payload,
)
from noetrium_platform.research.experimentation.workload.composition.declarative import (
    MethodRuntimeBindings, TaskFieldProjection, observed_method_event_costs,
    observed_method_execution_costs,
)

from .unit_activation_pool import PooledUnitActivationMechanics
from .research_execution_pool import ResearchExecutionPool


@dataclass(frozen=True, slots=True)
class ParticipantMethodBinding:
    role: str
    participant_kind: str
    treatment_id: str
    program: NoetriumUnit
    runtime: MethodRuntimeBindings
    _runtime_binding_digest: str = field(init=False, repr=False, compare=False)
    _operations: tuple[UnitOperationBinding, ...] = field(
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
        if not isinstance(self.program, NoetriumUnit):
            raise TypeError("participant Method runtime requires NoetriumUnit")
        if not isinstance(self.runtime, MethodRuntimeBindings):
            raise TypeError("participant Method runtime requires MethodRuntimeBindings")
        runtime_binding_digest = self.runtime.resolved_runtime_binding_digest()
        operations = method_program_operations(self.program)
        requirements = analyze_method_runtime_requirements(self.program)
        identity_digest = canonical_digest({
            "role": self.role,
            "participant_kind": self.participant_kind,
            "treatment_id": self.treatment_id,
            "method_program_digest": self.program.unit_digest,
            "runtime_binding_digest": runtime_binding_digest,
        })
        object.__setattr__(
            self,
            "_runtime_binding_digest",
            runtime_binding_digest,
        )
        object.__setattr__(self, "_operations", operations)
        object.__setattr__(self, "_runtime_requirements", requirements)
        object.__setattr__(self, "_identity_digest", identity_digest)

    @property
    def identity_digest(self) -> str:
        return self._identity_digest


@dataclass(frozen=True, slots=True)
class _TaskBinding:
    task: NoetriumUnit
    context: ExecutionContext
    task_input: object
    schedule: NoetriumUnit
    activation_runtime: object
    activation_mechanics: object
    requests: tuple[tuple[str, UnitActivationRequest], ...]
    _requests_by_role: Mapping[str, UnitActivationRequest] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        by_role = {role: request for role, request in self.requests}
        if len(by_role) != len(self.requests):
            raise ValueError("participant task binding request roles must be unique")
        object.__setattr__(self, "_requests_by_role", by_role)

    def request_for(
        self,
        role: str,
        *,
        participant_context: object | None = None,
        participant_context_digest: str | None = None,
    ) -> UnitActivationRequest:
        try:
            base = self._requests_by_role[role]
        except KeyError as exc:
            raise KeyError(role) from exc
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
            failure_policy=UnitActivationFailurePolicy.COLLECT,
        )


def _participant_method_failure_scope(statuses) -> str:
    """A Method failure is a measured trial outcome; interruption escapes.

    A failed planner/model reply must not terminate unrelated treatments or
    hide per-task zero-reward evidence. Only a cancelled or interrupted
    participant can invalidate its owning execution branch.
    """
    return (
        "branch"
        if any(status == MethodRunStatus.INTERRUPTED.value for status in statuses)
        else "task"
    )


class ScheduledParticipantWorkloadBinding:
    """Compile one participant schedule onto the universal NoetriumUnit Machine."""

    def __init__(
        self,
        *,
        schedule: NoetriumUnit,
        participants: tuple[ParticipantMethodBinding, ...],
        journal: MachineJournalPort,
        execution_pool: ResearchExecutionPool,
        input_projection: TaskFieldProjection | None = None,
        run_finalizer: Callable[[str], None] | None = None,
        task_finalizer: Callable[[ExecutionContext], None] | None = None,
        task_finalizer_identity_digest: str | None = None,
        clock=time.monotonic,
    ) -> None:
        waves = participant_schedule_waves(schedule)
        if type(participants) is not tuple or not participants or any(
            not isinstance(row, ParticipantMethodBinding) for row in participants
        ):
            raise TypeError("scheduled participant workload requires participant runtimes")
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("scheduled participant workload requires MachineJournalPort")
        if not isinstance(execution_pool, ResearchExecutionPool):
            raise TypeError("scheduled participant workload requires ResearchExecutionPool")
        projection = TaskFieldProjection() if input_projection is None else input_projection
        if not isinstance(projection, TaskFieldProjection):
            raise TypeError("scheduled participant workload requires TaskFieldProjection")
        if run_finalizer is not None and not callable(run_finalizer):
            raise TypeError(
                "scheduled participant workload run_finalizer must be callable"
            )
        if task_finalizer is not None and not callable(task_finalizer):
            raise TypeError(
                "scheduled participant workload task_finalizer must be callable"
            )
        if (task_finalizer is None) != (task_finalizer_identity_digest is None):
            raise ValueError(
                "task_finalizer and task_finalizer_identity_digest must be declared together"
            )
        if task_finalizer_identity_digest is not None and (
            type(task_finalizer_identity_digest) is not str
            or len(task_finalizer_identity_digest) != 64
        ):
            raise ValueError("task_finalizer_identity_digest must be SHA-256")
        if not callable(clock):
            raise TypeError("scheduled participant workload clock must be callable")
        roles = tuple(row.role for row in participants)
        scheduled = tuple(role for wave in waves for role in wave)
        if len(roles) != len(set(roles)) or set(scheduled) != set(roles) or len(scheduled) != len(roles):
            raise ValueError("participant schedule coverage drifted from participant runtimes")

        self._schedule = schedule
        self._participants = tuple(sorted(participants, key=lambda row: row.role))
        self._by_role = {row.role: row for row in self._participants}
        self._journal = journal
        self._execution_pool = execution_pool
        self._input_projection = projection
        self._run_finalizer = run_finalizer
        self._task_finalizer = task_finalizer
        self._task_finalizer_identity_digest = task_finalizer_identity_digest
        self._clock = clock
        self._participant_host_cache: SingleFlightCache[
            BoundExecutableUnit
        ] = SingleFlightCache()
        self._task_input_cache: SingleFlightCache[object] = SingleFlightCache(
            max_entries=16384
        )
        self._program = self._build_program(schedule)
        self._host = BoundExecutableUnit(
            host_id="workload:participant-schedule:" + participant_schedule_digest(schedule)[:24],
            unit=self._program,
            operations=(UnitOperationBinding(
                "participant.wave",
                self._execute_wave,
                canonical_digest({
                    "operation": "participant.wave",
                    "version": 1,
                    "schedule_digest": participant_schedule_digest(schedule),
                }),
            ),),
            journal=journal,
            max_steps=len(waves) + 1,
            dependency_identity={
                "schema": "noetrium.participant-scheduled-workload.v1",
                "schedule_digest": participant_schedule_digest(schedule),
                "participants": tuple((row.role, row.identity_digest) for row in self._participants),
            },
        )
        self.identity_digest = canonical_digest({
            "binding": "participant-scheduled-workload.v1",
            "schedule_digest": participant_schedule_digest(schedule),
            "participants": tuple((row.role, row.identity_digest) for row in self._participants),
            "program_digest": self._program.unit_digest,
            "input_projection_digest": projection.digest,
            "task_finalizer_identity_digest": task_finalizer_identity_digest,
        })
        self._binding_plan_digest_by_role = {
            participant.role: canonical_digest({
                "binding": "participant-method-invocation.v1",
                "workload_binding": self.identity_digest,
                "role": participant.role,
                "program_digest": participant.program.unit_digest,
                "runtime_binding_digest": participant._runtime_binding_digest,
            })
            for participant in self._participants
        }

    @staticmethod
    def _build_program(schedule: NoetriumUnit) -> NoetriumUnit:
        waves = participant_schedule_waves(schedule)
        schedule_digest = participant_schedule_digest(schedule)
        members = tuple(
            unit_operation(
                f"wave-{index}",
                "participant.wave",
                configuration={"wave_index": index, "roles": wave},
                max_visits=1,
            )
            for index, wave in enumerate(waves)
        )
        relations = tuple(
            unit_flow(
                f"wave-{index}",
                f"wave-{index + 1}",
                default=True,
            )
            for index in range(len(waves) - 1)
        )
        return executable_unit(
            "participant-schedule:" + schedule_digest,
            domain="participant",
            version="1",
            state_schema="noetrium.participant-schedule-state.v1",
            entrypoint="wave-0",
            members=members,
            relations=relations,
        )


    def _participant_host(
        self,
        participant: ParticipantMethodBinding,
        runtime_context,
        *,
        max_steps: int | None,
    ) -> BoundExecutableUnit:
        dependency_identity = {
            "schema": "noetrium.participant-method-activation.v2",
            "role": participant.role,
            "participant_kind": participant.participant_kind,
            "treatment_id": participant.treatment_id,
            "method_program_digest": participant.program.unit_digest,
            "binding_plan_digest": runtime_context.binding_plan_digest,
            "runtime_binding_digest": runtime_context.effective_runtime_binding_digest,
            "schema_digest": runtime_context.schema_digest,
            "schedule_digest": participant_schedule_digest(self._schedule),
        }
        host_id = (
            f"participant:{participant.role}:"
            f"{method_program_identity(participant.program).unit_id}"
        )
        cache_key = canonical_digest({
            "host_id": host_id,
            "execution_unit_digest": participant.program.unit_digest,
            "max_steps": max_steps,
            "dependency_identity": dependency_identity,
        })
        return self._participant_host_cache.get_or_create(
            cache_key,
            lambda: BoundExecutableUnit(
                host_id=host_id,
                unit=participant.program,
                operations=participant._operations,
                journal=self._journal,
                max_steps=max_steps,
                dependency_identity=dependency_identity,
            ),
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

    @staticmethod
    def _accepted_partial_measurement(
        binding: _TaskBinding,
    ) -> WorkloadTaskPartialMeasurement | None:
        """Read already committed participant work without resuming any child."""
        totals = {"model_tokens": 0, "physical_child_effects": 0}
        total_steps = 0
        child_rows = []
        accepted_event_count = 0
        for role, request in binding.requests:
            registered = binding.activation_runtime.registry.resolve(request.host_id)
            commits = registered.host.accepted_commits(request.child_machine_id)
            if not commits:
                continue
            latest = commits[-1]
            unit_state = latest.state.get(UNIT_STATE_KEY)
            if not isinstance(unit_state, Mapping):
                raise TypeError("accepted participant commit lacks Unit state")
            visits = unit_state.get("visits", {})
            if not isinstance(visits, Mapping):
                raise TypeError("accepted participant Unit visits must be an object")
            steps = 0
            for count in visits.values():
                if type(count) is not int or count < 0:
                    raise TypeError("accepted participant Unit visit count must be non-negative integer")
                steps += count
            events, _effects = project_method_accepted_evidence(
                registered.host, request.child_machine_id
            )
            costs = observed_method_event_costs(events)
            total_steps += steps
            accepted_event_count += len(events)
            for key in totals:
                totals[key] += costs[key]
            child_rows.append((
                role, request.child_machine_id, latest.revision,
                latest.commit_id, steps, len(events),
            ))
        if not child_rows:
            return None
        return WorkloadTaskPartialMeasurement(
            steps=total_steps,
            diagnostics={
                **totals,
                "partial_measurement_source": "accepted_method_journal",
                "partial_participant_count": len(child_rows),
                "partial_accepted_event_count": accepted_event_count,
                "partial_participant_machine_cuts": tuple(child_rows),
            },
        )

    def _execute_wave(self, request: UnitStepContext, binding: object) -> UnitTransition:
        if not isinstance(binding, _TaskBinding):
            raise TypeError("participant wave requires task binding")
        raw_roles = request.configuration.get("roles")
        if not isinstance(raw_roles, (tuple, list)) or not raw_roles:
            raise TypeError("participant wave roles must be a non-empty sequence")
        roles = tuple(str(role) for role in raw_roles)
        prior = request.data.get("participants", {})
        if not isinstance(prior, Mapping):
            raise TypeError("participant parent state must contain an object")
        prior_costs = request.data.get("evaluator_execution_costs", {})
        if not isinstance(prior_costs, Mapping):
            raise TypeError("participant evaluator execution costs must be an object")
        prior_digest = canonical_digest(prior)
        wave_requests = {
            role: binding.request_for(
                role,
                participant_context=prior,
                participant_context_digest=prior_digest,
            )
            for role in roles
        }
        batch = UnitActivationBatchRequest(
            batch_id=f"{request.snapshot.machine_id}:{request.node.unit_id}:{canonical_digest(roles)[:16]}",
            parent_machine_id=request.snapshot.machine_id,
            selection_digest=canonical_digest({
                "schedule_digest": participant_schedule_digest(binding.schedule),
                "wave": request.configuration,
                "task_id": task_id(binding.task),
                "participant_context_digest": prior_digest,
            }),
            items=tuple(
                UnitActivationBatchItem(role, wave_requests[role])
                for role in roles
            ),
        )
        execution = execute_unit_activation_batch(
            binding.activation_runtime, binding.activation_mechanics, batch
        )
        merged = dict(prior)
        merged_costs = {str(role): dict(costs) for role, costs in prior_costs.items() if isinstance(costs, Mapping)}
        hard_failures = []
        limited = []
        evidence_refs = list(execution.evidence_digests)
        for role, child in zip(roles, execution.executions, strict=True):
            participant = self._by_role[role]
            child_request = wave_requests[role]
            runtime_context = binding.activation_runtime.registry.resolve(
                child_request.host_id
            ).binding_factory(child_request)
            result = project_method_host_execution(
                participant.program, runtime_context, child.execution
            )
            if result.evidence_reference is not None:
                evidence_refs.append(result.evidence_reference.reference_id)
            receipt = self._receipt(result)
            merged_costs[role] = observed_method_execution_costs(result)
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
            if result.status in {MethodRunStatus.FAILED, MethodRunStatus.INTERRUPTED}:
                hard_failures.append(
                    (role, result.failure or result.failure_code or result.status.value)
                )
            elif result.status is MethodRunStatus.LIMIT_REACHED:
                limited.append(
                    (role, result.failure or result.failure_code or result.status.value)
                )
        terminal = unit_operation_next_node(request.unit, request.node) is None
        transition_kwargs = {
            "value": {"participants": merged},
            "state_delta": {
                "participants": merged,
                "evaluator_execution_costs": merged_costs,
            },
            "semantic_delta": {
                "participant_schedule_digest": participant_schedule_digest(binding.schedule),
                "completed_wave": request.node.unit_id,
                "failed_participants": tuple(hard_failures),
                "limited_participants": tuple(limited),
            },
            "events": ({
                "type": (
                    "participant.wave.failed"
                    if hard_failures
                    else (
                        "participant.wave.limited"
                        if limited
                        else "participant.wave.completed"
                    )
                ),
                "roles": roles,
                "batch_execution_digest": execution.execution_digest,
            },),
            "evidence_refs": tuple(evidence_refs),
            "child_links": execution.links,
        }
        if hard_failures:
            return UnitTransition.halt(failed=True, **transition_kwargs)
        if terminal:
            return UnitTransition.halt(**transition_kwargs)
        return UnitTransition.goto(**transition_kwargs)

    def _task_binding(
        self,
        task: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
        *,
        parent_machine_id: str,
    ) -> _TaskBinding:
        registry = UnitActivationRegistry()
        requests = []
        task_input_key = canonical_digest({
            "projection_digest": self._input_projection.digest,
            "task": task,
        })
        task_input = self._task_input_cache.get_or_create(
            task_input_key,
            lambda: self._input_projection.project(task),
        )
        max_steps = context.trial_budget.get("max_steps")
        resolved_max_steps = None if max_steps is None else int(max_steps)
        for participant in self._participants:
            binding_plan_digest = self._binding_plan_digest_by_role[
                participant.role
            ]
            inherited_context = dict(context.participant_context)
            inherited_context.update({
                "role": participant.role,
                "participant_kind": participant.participant_kind,
                "treatment_id": participant.treatment_id,
            })
            if isinstance(task_payload(task), Mapping):
                environment_setup = task_payload(task).get("environment_setup")
                if environment_setup is not None:
                    inherited_context["environment_task_setup"] = environment_setup
                    if isinstance(environment_setup, Mapping):
                        pairing_id = environment_setup.get("pairing_id")
                        if isinstance(pairing_id, str) and pairing_id.strip():
                            inherited_context["environment_pairing_id"] = pairing_id.strip()
            participant_context = replace(
                context,
                participant_context=inherited_context,
            )
            runtime_context, _task_root = participant.runtime.materialize_context(
                program=participant.program,
                task=task,
                context=participant_context,
                control=control,
                binding_plan_digest=binding_plan_digest,
                invocation_id=participant.role,
            )
            participant._runtime_requirements.require(runtime_context)
            host = self._participant_host(
                participant,
                runtime_context,
                max_steps=resolved_max_steps,
            )
            host_id = host.host_id
            base_runtime_context = runtime_context

            def bind_participant_request(
                child_request: UnitActivationRequest,
                *,
                _base=base_runtime_context,
                _host=host,
            ):
                identity = child_request.instance_identity
                if not isinstance(identity, Mapping):
                    raise TypeError("participant child instance identity must be an object")
                participant_context = identity.get("participant_context", {})
                if not isinstance(participant_context, Mapping):
                    raise TypeError("participant child context identity must be an object")
                if identity.get("participant_context_digest") != canonical_digest(participant_context):
                    raise ValueError("participant child context identity digest drifted")
                merged_context = dict(_base.execution.participant_context)
                for key, value in participant_context.items():
                    if key in merged_context:
                        raise ValueError(
                            "participant prior context collides with inherited execution context: "
                            + str(key)
                        )
                    merged_context[str(key)] = value
                return replace(
                    _base,
                    execution=replace(
                        _base.execution,
                        participant_context=merged_context,
                    ),
                    program_binding=_host,
                    machine_id=child_request.child_machine_id,
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
            base_child_machine_id = "participant:" + canonical_digest({
                "parent_machine_id": parent_machine_id,
                "role": participant.role,
                "task_id": task_id(task),
                "program_digest": participant.program.unit_digest,
                "run_id": runtime_context.execution.run_id,
            })[:48]
            child_machine_id = host.terminal_replay_machine_id(
                base_child_machine_id
            )
            requests.append((participant.role, UnitActivationRequest(
                host_id=host_id,
                parent_machine_id=parent_machine_id,
                child_machine_id=child_machine_id,
                instance_identity={
                    "schema": "noetrium.participant-method-instance.v1",
                    "role": participant.role,
                    "participant_kind": participant.participant_kind,
                    "treatment_id": participant.treatment_id,
                    "task_id": task_id(task),
                    "run_id": runtime_context.execution.run_id,
                    "method_program_digest": participant.program.unit_digest,
                    "binding_plan_digest": runtime_context.binding_plan_digest,
                    "runtime_binding_digest": runtime_context.effective_runtime_binding_digest,
                    "schema_digest": runtime_context.schema_digest,
                    "assignment_seed": context.assignment_seed,
                    "intervention_values": context.intervention_values,
                    "replay_level": context.replay_level,
                },
                initial_data={},
                payload=task_input,
                failure_policy=UnitActivationFailurePolicy.COLLECT,
                command_id_prefix=f"{parent_machine_id}:{participant.role}",
            )))
        activation_runtime = registry.runtime()
        activation_mechanics = PooledUnitActivationMechanics(
            activation_runtime,
            execution_pool=self._execution_pool,
            execution_tenant_id=context.execution_tenant_id,
            parent_control=control,
        )
        return _TaskBinding(
            task=task,
            context=context,
            task_input=task_input,
            schedule=self._schedule,
            activation_runtime=activation_runtime,
            activation_mechanics=activation_mechanics,
            requests=tuple(requests),
        )


    @contextmanager
    def task_group_scope(self, context: ExecutionContext):
        if not isinstance(context, ExecutionContext):
            raise TypeError(
                "participant workload task-group scope requires ExecutionContext"
            )
        group = self._execution_pool.open_workload_group(
            "workload-dag:"
            + canonical_digest({
                "run_id": context.run_id,
                "lifetime_id": context.lifetime_id,
                "span_id": context.span_id,
                "schedule_digest": participant_schedule_digest(self._schedule),
            })[:32],
            tenant_id=context.execution_tenant_id,
            resource_id="workload-dag:" + participant_schedule_digest(self._schedule)[:24],
        )
        completed = False
        try:
            yield group
            completed = True
        finally:
            self._execution_pool.close_workload_group(
                group,
                cancel_pending=not completed,
            )

    def execute_one(
        self,
        task: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> WorkloadTaskResult:
        require_task_unit(task)
        if not isinstance(context, ExecutionContext):
            raise TypeError("participant workload context must be ExecutionContext")
        started = self._clock()
        base_parent_machine_id = "participant-workload:" + canonical_digest({
            "run_id": context.run_id,
            "lifetime_id": context.lifetime_id,
            "task_id": task_id(task),
            "schedule_digest": participant_schedule_digest(self._schedule),
            "binding_digest": self.identity_digest,
        })[:48]
        parent_machine_id = self._host.terminal_replay_machine_id(
            base_parent_machine_id
        )
        binding = self._task_binding(
            task,
            context,
            control,
            parent_machine_id=parent_machine_id,
        )
        invocation_run_ids = tuple(
            str(request.instance_identity["run_id"])
            for _role, request in binding.requests
        )
        try:
            try:
                execution = self._host.execute(
                    machine_id=parent_machine_id,
                    instance_identity={
                        "schema": "noetrium.participant-workload-instance.v1",
                        "task_id": task_id(task),
                        "lineage_id": task_lineage_id(task),
                        "run_id": context.run_id,
                        "lifetime_id": context.lifetime_id,
                        "schedule_digest": participant_schedule_digest(self._schedule),
                        "assignment_seed": context.assignment_seed,
                        "intervention_values": context.intervention_values,
                        "replay_level": context.replay_level,
                        "trial_budget": context.trial_budget,
                    },
                    binding=binding,
                    initial_data={"participants": {}, "evaluator_execution_costs": {}},
                    payload=binding.task_input,
                    command_id_prefix=parent_machine_id,
                )
            except TaskDeadlineExceeded as exc:
                partial = self._accepted_partial_measurement(binding)
                if partial is None:
                    raise
                raise WorkloadTaskDeadlineExceeded(
                    str(exc), partial_measurement=partial
                ) from exc
        finally:
            if self._run_finalizer is not None:
                for run_id in invocation_run_ids:
                    self._run_finalizer(run_id)
            if self._task_finalizer is not None:
                self._task_finalizer(context)
        completed = execution.data.get("participants", {})
        if not isinstance(completed, Mapping):
            raise TypeError("participant parent result must contain an object")
        completed_roles = set(completed)
        raw_costs = execution.data.get("evaluator_execution_costs", {})
        if not isinstance(raw_costs, Mapping):
            raise TypeError("participant parent execution costs must contain an object")
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
        complete = (
            execution.status is MachineStatus.COMPLETED
            and len(projected) == len(self._participants)
            and all(
                receipt.status == MethodRunStatus.SUCCEEDED.value
                for _role, receipt, _row in projected
            )
        )
        # Participant execution health and task-goal success are distinct.
        # Research Methods that expose an explicit verified task outcome own
        # ``result.success``; execution completion must never substitute for it.
        explicit_success = []
        missing_explicit_success = []
        for role, _receipt, row in projected:
            participant_result = row.get("result")
            if (
                isinstance(participant_result, Mapping)
                and type(participant_result.get("success")) is bool
            ):
                explicit_success.append(bool(participant_result["success"]))
            else:
                missing_explicit_success.append(role)
        if missing_explicit_success and complete:
            raise ValueError(
                "completed participant workload requires explicit boolean "
                "result.success for every participant; execution completion "
                "is not task-goal success authority"
            )
        task_success_authority = "participant_result.success"
        success = complete and bool(explicit_success) and all(explicit_success)

        explicit_steps = []
        missing_explicit_steps = []
        for role, _receipt, row in projected:
            participant_result = row.get("result")
            value = (
                participant_result.get("steps")
                if isinstance(participant_result, Mapping)
                else None
            )
            if type(value) is int and value >= 0:
                explicit_steps.append(value)
            else:
                missing_explicit_steps.append(role)
        if missing_explicit_steps and complete:
            raise ValueError(
                "completed participant workload requires explicit nonnegative "
                "result.steps for every participant; Method-machine step_count "
                "is not environment-step authority"
            )
        task_steps = sum(explicit_steps)
        execution_steps = sum(receipt.step_count for _, receipt, _ in projected)
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
        # A Method failure is an observed failed *episode*, not evidence
        # that its enclosing Experiment/Study has become invalid. Otherwise
        # one malformed model response aborts the whole treatment arm and
        # prevents unbiased per-task failure accounting. True interruption
        # still belongs to the wider control/lifecycle authority.
        failure_scope = _participant_method_failure_scope(
            receipt.status for _role, receipt, _row in projected
        )
        evaluator_costs = {"model_tokens": 0, "physical_child_effects": 0}
        for role, _receipt, _row in projected:
            costs = raw_costs.get(role)
            if not isinstance(costs, Mapping):
                raise ValueError(
                    "participant parent result lacks evaluator-only execution costs for role "
                    + role
                )
            for key in evaluator_costs:
                value = costs.get(key)
                if type(value) is not int or value < 0:
                    raise TypeError(
                        f"participant evaluator execution cost {role}.{key} must be a nonnegative integer"
                    )
                evaluator_costs[key] += value
        duration = self._clock() - started
        return WorkloadTaskResult(
            task_id=task_id(task),
            family=task_family(task),
            complete=complete,
            success=success,
            utility=1.0 if success else 0.0,
            steps=task_steps,
            duration_s=duration,
            lineage_id=task_lineage_id(task),
            failure_reason=(
                "" if success
                else repr(failures) if failures
                else "participant task success predicate not satisfied"
                if complete
                else f"participant parent machine stopped with {execution.status.value}"
            ),
            participant_receipts=receipts,
            failure_scope=failure_scope,
            diagnostics={
                "participant_schedule_digest": participant_schedule_digest(self._schedule),
                "participant_execution_complete": complete,
                "participant_task_success_authority": task_success_authority,
                "participant_task_steps_authority": "participant_result.steps",
                "participant_execution_steps": execution_steps,
                "participant_parent_program_digest": self._program.unit_digest,
                "participant_parent_machine_cut_digest": (
                    None if execution.cut is None else execution.cut.cut_digest
                ),
                "participant_child_machine_cuts": tuple(
                    (role, str(row["machine_cut_digest"]))
                    for role, _receipt, row in projected
                ),
                **evaluator_costs,
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


__all__ = ["ParticipantMethodBinding", "ScheduledParticipantWorkloadBinding"]
