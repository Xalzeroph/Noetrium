from __future__ import annotations

from dataclasses import replace
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    study_plan_binding_at,
    study_plan_intervention_at,
    study_plan_provider_id,
    study_plan_digest,
    study_protocol_digest,
    study_assignment_text,
    study_assignment_variant_index,
    study_assignment_workload,
    study_assignment_digest,
    assignment_workload_digest,
    assignment_workload_task_ids,
    assignment_workload,
    assignment_workload_dependencies_for,
    assignment_workload_prerequisites_for,
    assignment_workload_retry_sources_for,
    validate_assignment_workload,
    BoundStudyExecutionPort,
    MeasurementValueKind,
    StudyExecutionUnit,
    StudyMetricObservation,
    TaskVerifierPort,
    TrialExecutionReceipt,
    TrialExecutionRequest,
    TrialPreparationPort,
    TrialProviderPort,
    VariantBinding,
)
from noetrium_platform.research.experimentation.api.research_compiler import research_plan_study, research_plan_protocol, research_plan_value, research_plan_digest, compile_research_participant_schedule, research_plan_study_identity, research_plan_trial_protocol_identity
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    benchmark_selected_tasks,
    measurement_definitions,
    measurement_id,
    measurement_value_kind,
    study_benchmark,
    study_benchmark_split_id,
    study_execution_policy,
    study_experiment_id,
    study_measurement_protocol,
    task_id,
    participant_schedule_digest,
)
"""Canonical TrialProvider -> BoundStudyExecution bridge for Research execution.

The bridge is composition only. Trial providers own domain execution, verifier
providers own verifier truth, ExperimentProgram owns scheduling, and Research execution
owns the durable execution cut. No second execution loop is introduced here.
"""



from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_digest, freeze_json, require_sha256
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort
from noetrium_platform.evidence.observability.api import DiagnosticDegradationPort
from noetrium_platform.composition.diagnostic_degradation import record_diagnostic_degradation
from noetrium_platform.research.experimentation.lifecycle.study.providers.trial import (
    TrialVerifierOrchestrator,
)

from .research_experiment import (
    ResearchExperimentExecutionBindingView,
    require_experiment_execution_binding,
)
from .shared_host_pressure import ResourceCompetitionDemand

from .research_experiment_runtime_binding import (
    ResearchExperimentStudyExecutionBinding,
    ResearchExperimentStudyExecutionResolverPort,
)


def _study_scalar_metric_names(measurement_protocol: NoetriumUnit) -> tuple[str, ...]:
    """Project scalar aggregation names without collapsing measurement truth.

    Trial receipts remain authoritative for every declared MeasurementValue kind.
    StudyMetricObservation is intentionally scalar-only, so its projection must
    select only scalar definitions instead of rejecting valid structured,
    sequence, categorical, or other measurement families.
    """

    return tuple(
        measurement_id(definition)
        for definition in measurement_definitions(measurement_protocol)
        if MeasurementValueKind(measurement_value_kind(definition))
        is MeasurementValueKind.SCALAR
    )


@dataclass(frozen=True, slots=True)
class ResearchExperimentTrialProviderBinding:
    """Exact Trial provider/verifier authority for one Experiment execution."""

    provider_identity: str
    provider: TrialProviderPort
    provider_identity_digest: str
    verifier: TaskVerifierPort | None = None
    verifier_identity_digest: str | None = None
    binding_digest: str = ""
    resource_demand: ResourceCompetitionDemand | None = None

    def __post_init__(self) -> None:
        if (
            type(self.provider_identity) is not str
            or not self.provider_identity.strip()
            or self.provider_identity != self.provider_identity.strip()
        ):
            raise ValueError(
                "Experiment Trial provider_identity must be canonical text"
            )
        if not isinstance(self.provider, TrialProviderPort):
            raise TypeError(
                "Experiment Trial provider binding requires TrialProviderPort"
            )
        require_sha256(
            self.provider_identity_digest,
            "Experiment Trial provider identity",
        )
        if self.resource_demand is not None and not isinstance(
            self.resource_demand, ResourceCompetitionDemand
        ):
            raise TypeError(
                "Experiment Trial provider resource_demand must be ResourceCompetitionDemand"
            )
        if self.verifier is None:
            if self.verifier_identity_digest is not None:
                raise ValueError(
                    "Experiment Trial verifier identity requires verifier"
                )
        else:
            if not callable(getattr(self.verifier, "verify", None)):
                raise TypeError(
                    "Experiment Trial verifier must satisfy TaskVerifierPort"
                )
            if self.verifier_identity_digest is None:
                raise ValueError(
                    "Experiment Trial verifier requires identity digest"
                )
            require_sha256(
                self.verifier_identity_digest,
                "Experiment Trial verifier identity",
            )
        expected = canonical_digest(
            {
                "provider_identity": self.provider_identity,
                "provider_identity_digest": self.provider_identity_digest,
                "verifier_identity_digest": self.verifier_identity_digest,
                "resource_demand_digest": (
                    None
                    if self.resource_demand is None
                    else canonical_digest(self.resource_demand)
                ),
            }
        )
        if self.binding_digest:
            require_sha256(
                self.binding_digest,
                "Experiment Trial provider binding digest",
            )
            if self.binding_digest != expected:
                raise ValueError(
                    "Experiment Trial provider binding digest drifted"
                )
        else:
            object.__setattr__(self, "binding_digest", expected)


@dataclass(frozen=True, slots=True)
class ResearchExperimentTrialProviderRegistration:
    """One owner-system Trial provider registration with exact scientific identity."""

    provider_identity: str
    provider: TrialProviderPort
    provider_identity_digest: str
    verifier: TaskVerifierPort | None = None
    verifier_identity_digest: str | None = None
    registration_digest: str = ""

    def __post_init__(self) -> None:
        binding = ResearchExperimentTrialProviderBinding(
            self.provider_identity,
            self.provider,
            self.provider_identity_digest,
            self.verifier,
            self.verifier_identity_digest,
            resource_demand=None,
        )
        expected = canonical_digest(
            {
                "provider_binding_digest": binding.binding_digest,
                "protocol_identity_digest": self.provider.protocol_identity.unit_digest,
            }
        )
        if self.registration_digest:
            require_sha256(
                self.registration_digest,
                "Experiment Trial provider registration digest",
            )
            if self.registration_digest != expected:
                raise ValueError(
                    "Experiment Trial provider registration digest drifted"
                )
        else:
            object.__setattr__(self, "registration_digest", expected)


class ResearchExperimentTrialProviderRegistry:
    """Exact Trial provider registry keyed by Research-selected provider identity."""

    def __init__(
        self,
        registrations: tuple[
            ResearchExperimentTrialProviderRegistration, ...
        ],
    ) -> None:
        if type(registrations) is not tuple:
            raise TypeError(
                "Experiment Trial provider registry requires typed tuple"
            )
        if any(
            type(row) is not ResearchExperimentTrialProviderRegistration
            for row in registrations
        ):
            raise TypeError(
                "Experiment Trial provider registry registrations must be typed"
            )
        ordered = tuple(
            sorted(
                registrations,
                key=lambda row: (
                    row.provider_identity,
                    row.provider.protocol_identity.unit_digest,
                    row.registration_digest,
                ),
            )
        )
        keys = tuple(
            (
                row.provider_identity,
                row.provider.protocol_identity.unit_digest,
            )
            for row in ordered
        )
        if len(keys) != len(set(keys)):
            raise ValueError(
                "Experiment Trial provider registry contains duplicate "
                "provider/protocol authority"
            )
        self._registrations = ordered
        self._by_key = {
            (
                row.provider_identity,
                row.provider.protocol_identity.unit_digest,
            ): row
            for row in ordered
        }
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.experiment-trial-provider-registry.v1",
                "registrations": tuple(
                    row.registration_digest for row in ordered
                ),
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def resolve(
        self,
        execution: ResearchExperimentExecutionBindingView,
    ) -> ResearchExperimentTrialProviderBinding:
        execution = require_experiment_execution_binding(execution)
        provider_identity = study_plan_provider_id(
            research_plan_study(execution.research_plan)
        )
        protocol_digest = research_plan_trial_protocol_identity(execution.research_plan).unit_digest
        row = self._by_key.get((provider_identity, protocol_digest))
        if row is None:
            raise LookupError(
                "no unique Trial provider registration for "
                f"provider={provider_identity!r} protocol={protocol_digest}"
            )
        return ResearchExperimentTrialProviderBinding(
            row.provider_identity,
            row.provider,
            row.provider_identity_digest,
            row.verifier,
            row.verifier_identity_digest,
        )


@runtime_checkable
class ResearchExperimentTrialProviderResolverPort(Protocol):
    """Resolve Trial/provider authority owned by the concrete execution system."""

    def resolve(
        self,
        execution: ResearchExperimentExecutionBindingView,
    ) -> ResearchExperimentTrialProviderBinding: ...


@runtime_checkable
class ResearchExperimentTrialReceiptPublisherPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def publish(
        self,
        request: TrialExecutionRequest,
        receipt: TrialExecutionReceipt,
    ): ...


@runtime_checkable
class ResearchExperimentTrialObservationPort(Protocol):
    """Side-plane projection only; never owns Trial/Study truth."""

    def publish(
        self,
        request: TrialExecutionRequest,
        receipt: TrialExecutionReceipt,
        observation: StudyMetricObservation,
    ) -> None: ...


class _TrialBoundStudyExecution(BoundStudyExecutionPort):
    def __init__(
        self,
        execution: ResearchExperimentExecutionBindingView,
        provider_binding: ResearchExperimentTrialProviderBinding,
        observation: ResearchExperimentTrialObservationPort | None = None,
        receipt_publisher: ResearchExperimentTrialReceiptPublisherPort | None = None,
        degradation_sink: DiagnosticDegradationPort | None = None,
        scientific_inputs: Mapping[str, object] | None = None,
    ) -> None:
        self._execution = execution
        self._provider_binding = provider_binding
        if observation is not None and not isinstance(
            observation, ResearchExperimentTrialObservationPort
        ):
            raise TypeError("Trial Study observation must satisfy typed side-plane port")
        self._observation_sink = observation
        if receipt_publisher is not None and not isinstance(
            receipt_publisher, ResearchExperimentTrialReceiptPublisherPort
        ):
            raise TypeError(
                "Trial Study receipt_publisher must satisfy typed publisher port"
            )
        self._receipt_publisher = receipt_publisher
        if degradation_sink is not None and not isinstance(
            degradation_sink, DiagnosticDegradationPort
        ):
            raise TypeError("Trial Study degradation sink must satisfy typed port")
        self._degradation_sink = degradation_sink
        if scientific_inputs is None:
            scientific_inputs = {}
        if not isinstance(scientific_inputs, Mapping):
            raise TypeError("Trial Study scientific_inputs must be an object")
        self._scientific_inputs = freeze_json(dict(scientific_inputs))
        provider_protocol = provider_binding.provider.protocol_identity
        if provider_protocol != research_plan_trial_protocol_identity(execution.research_plan):
            raise ValueError(
                "Trial provider protocol identity does not match Research execution"
            )
        selected_provider_id = study_plan_provider_id(
            research_plan_study(execution.research_plan)
        )
        if selected_provider_id != provider_binding.provider_identity:
            raise ValueError(
                "Trial provider identity does not match Research binding authority"
            )
        self._metric_names = _study_scalar_metric_names(
            study_measurement_protocol(execution.experiment_definition)
        )
        if not self._metric_names:
            raise ValueError(
                "canonical Trial Study execution requires at least one scalar "
                "measurement metric"
            )

        # Participant scheduling is immutable Study semantics.  Compile it once
        # for this bound Study rather than once per assignment/trial request.
        participant_schedule = compile_research_participant_schedule(
            execution.experiment_definition,
            execution.experiment_binding,
        )
        observed_schedule_digest = (
            None
            if participant_schedule is None
            else participant_schedule_digest(participant_schedule)
        )
        expected_schedule_digest = research_plan_value(
            execution.research_plan,
            "participant_schedule_digest",
        )
        if observed_schedule_digest != expected_schedule_digest:
            raise ValueError(
                "Trial Study participant schedule drifted from frozen ResearchPlan"
            )
        self._participant_schedule_spec = participant_schedule

        # Freeze every Study-level projection once.  Trial requests are the hot
        # path and may number in the millions; they must only pay for
        # assignment-specific work, never repeat immutable Study traversal.
        plan = execution.research_plan
        definition = execution.experiment_definition
        self._plan = plan
        self._plan_study = research_plan_study(plan)
        self._plan_digest = research_plan_digest(plan)
        self._revision_digest = research_plan_value(plan, "revision_digest")
        self._participant_schedule_digest = expected_schedule_digest
        self._protocol_identity = research_plan_trial_protocol_identity(plan)
        self._project_id = str(research_plan_study_identity(plan)["project_id"])
        self._experiment_id = study_experiment_id(definition)
        self._execution_policy = study_execution_policy(definition)
        self._measurement_protocol = study_measurement_protocol(definition)
        self._task_by_id = {
            task_id(row): row
            for row in benchmark_selected_tasks(
                study_benchmark(definition),
                study_benchmark_split_id(definition),
            )
        }

    def bind_scientific_inputs(
        self,
        inputs: Mapping[str, object],
    ) -> "_TrialBoundStudyExecution":
        if not isinstance(inputs, Mapping):
            raise TypeError("Trial Study scientific_inputs must be an object")
        # The execution/provider closure is immutable and already validated.
        # Clone only the per-invocation scientific input projection rather than
        # reconstructing the Study adapter and all of its static indexes.
        bound = object.__new__(_TrialBoundStudyExecution)
        bound.__dict__ = self.__dict__.copy()
        bound._scientific_inputs = freeze_json(dict(inputs))
        return bound

    def _request(
        self,
        assignment: NoetriumUnit,
        binding: VariantBinding,
        plan_digest: str,
        *,
        execution_context: ExecutionContext,
    ) -> TrialExecutionRequest:
        require_sha256(plan_digest, "Trial Study plan_digest")
        if not isinstance(execution_context, ExecutionContext):
            raise TypeError("Trial Study execution_context must be ExecutionContext")
        require_sha256(execution_context.run_id, "Trial Study execution run_id")
        plan = self._plan
        if plan_digest != study_plan_digest(self._plan_study):
            raise ValueError("Trial Study execution plan digest drifted")
        variant_index = study_assignment_variant_index(assignment)
        plan_study = self._plan_study
        expected_binding = study_plan_binding_at(plan_study, variant_index)
        if expected_binding != binding:
            raise ValueError("Trial Study VariantBinding drifted")
        if expected_binding.variant.unit_id != study_assignment_text(
            assignment, "variant_id"
        ):
            raise ValueError("Trial Study assignment variant identity drifted")
        intervention = study_plan_intervention_at(plan_study, variant_index)
        if intervention.unit_id != study_assignment_text(assignment, "variant_id"):
            raise ValueError(
                "Trial Study assignment has no matching intervention identity"
            )
        task_definitions = tuple(
            self._task_by_id[task_name]
            for task_name in assignment_workload_task_ids(
                study_assignment_workload(assignment)
            )
        )
        trial_context = replace(
            execution_context,
            experiment_id=self._experiment_id,
        )
        return TrialExecutionRequest(
            project_id=self._project_id,
            experiment_id=self._experiment_id,
            run_id=trial_context.run_id,
            execution_context=trial_context,
            research_plan_digest=self._plan_digest,
            revision=self._revision_digest,
            participant_schedule=self._participant_schedule_digest,
            participant_schedule_spec=self._participant_schedule_spec,
            execution_policy=self._execution_policy,
            intervention_spec=intervention,
            assignment=assignment,
            binding=binding,
            measurement_protocol=self._measurement_protocol,
            protocol_identity=self._protocol_identity,
            task_definitions=task_definitions,
            scientific_inputs=self._scientific_inputs,
        )

    def _observation(
        self,
        request: TrialExecutionRequest,
        receipt: TrialExecutionReceipt,
        receipt_reference,
    ) -> StudyMetricObservation:
        if receipt.request_digest != request.request_digest:
            raise ValueError("Trial receipt does not bind Study request")
        if receipt.assignment_digest != study_assignment_digest(request.assignment):
            raise ValueError("Trial receipt assignment identity drifted")

        values: dict[str, float] = {}
        for record in receipt.measurements:
            record.validate_against(request.measurement_protocol)
            if record.measurement_id not in self._metric_names:
                continue
            if record.value.kind is not MeasurementValueKind.SCALAR:
                raise ValueError(
                    "Study scalar metric received non-scalar MeasurementValue"
                )
            if record.value.scalar is None:
                raise ValueError("Study scalar metric has no scalar carrier")
            if record.measurement_id in values:
                raise ValueError(
                    "Trial receipt contains duplicate Study scalar metric"
                )
            values[record.measurement_id] = float(record.value.scalar)

        missing = tuple(
            metric for metric in self._metric_names if metric not in values
        )
        if set(missing) != (set(receipt.unobserved_measurement_ids) & set(self._metric_names)):
            raise ValueError(
                "Trial receipt is missing unexplained Study scalar metrics: "
                f"{tuple(sorted(set(missing) - set(receipt.unobserved_measurement_ids)))}"
            )
        return StudyMetricObservation(
            request.assignment,
            tuple((name, values[name]) for name in self._metric_names if name in values),
            unobserved_metric_names=missing,
            trial_request_digest=request.request_digest,
            trial_receipt_digest=receipt.receipt_digest,
            trial_receipt_reference=receipt_reference,
            measurement_record_digests=tuple(
                row.record_digest for row in receipt.measurements
            ),
            evidence_refs=receipt.evidence_refs,
            verifier_receipt_digest=(
                None
                if receipt.verifier_receipt is None
                else receipt.verifier_receipt.receipt_digest
            ),
        )

    def _prepare_request(
        self,
        request: TrialExecutionRequest,
        control: ExecutionControlPort,
    ) -> None:
        if not isinstance(control, ExecutionControlPort):
            raise TypeError("Trial Study preparation requires ExecutionControlPort")
        control.checkpoint()
        provider = self._provider_binding.provider
        if isinstance(provider, TrialPreparationPort):
            provider.prepare_trial(request, control)

    def execute_bound_variant(
        self,
        assignment: NoetriumUnit,
        binding: VariantBinding,
        plan_digest: str,
        *,
        execution_context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> StudyMetricObservation:
        if not isinstance(control, ExecutionControlPort):
            raise TypeError("Trial Study execution requires ExecutionControlPort")
        control.checkpoint()
        request = self._request(
            assignment,
            binding,
            plan_digest,
            execution_context=execution_context,
        )
        self._prepare_request(request, control)
        provider = self._provider_binding.provider
        provider_receipt = provider.run_trial(request, control)
        receipt = TrialVerifierOrchestrator().finalize(
            request,
            provider_receipt,
            verifier=self._provider_binding.verifier,
        )
        if self._receipt_publisher is None:
            raise RuntimeError(
                "canonical Trial Study execution requires authoritative Trial receipt publication"
            )
        receipt_reference = self._receipt_publisher.publish(request, receipt)
        observation = self._observation(request, receipt, receipt_reference)
        if self._observation_sink is not None:
            try:
                self._observation_sink.publish(request, receipt, observation)
            except Exception as exc:
                # Scientific truth remains the authoritative Trial receipt, but
                # side-plane loss is itself a durable graph-bound diagnostic fact.
                record_diagnostic_degradation(
                    self._degradation_sink,
                    request.execution_context,
                    subsystem="research.trial-observation",
                    stage="publish",
                    exc=exc,
                    correlation_refs=(
                        request.request_digest,
                        receipt.receipt_digest,
                        observation.observation_digest,
                    ),
                )
        return observation

    def execute_bound(
        self,
        unit: StudyExecutionUnit,
        bindings: tuple[VariantBinding, ...],
        plan_digest: str,
        *,
        execution_context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> tuple[StudyMetricObservation, ...]:
        if len(unit.assignments) != len(bindings):
            raise ValueError(
                "Trial Study execution unit/binding cardinality mismatch"
            )
        return tuple(
            self.execute_bound_variant(
                assignment,
                binding,
                plan_digest,
                execution_context=execution_context,
                control=control,
            )
            for assignment, binding in zip(
                unit.assignments,
                bindings,
                strict=True,
            )
        )


class ResearchExperimentTrialStudyExecutionResolver(
    ResearchExperimentStudyExecutionResolverPort
):
    """Canonical Study execution resolver over owner-supplied Trial providers."""

    def __init__(
        self,
        providers: ResearchExperimentTrialProviderResolverPort,
        *,
        observation: ResearchExperimentTrialObservationPort | None = None,
        receipt_publisher: ResearchExperimentTrialReceiptPublisherPort | None = None,
        degradation_sink: DiagnosticDegradationPort | None = None,
    ) -> None:
        if not isinstance(
            providers,
            ResearchExperimentTrialProviderResolverPort,
        ):
            raise TypeError(
                "Trial Study execution resolver requires Trial provider resolver"
            )
        self._providers = providers
        if observation is not None and not isinstance(
            observation, ResearchExperimentTrialObservationPort
        ):
            raise TypeError("Experiment Trial observation must satisfy typed port")
        self._observation = observation
        if receipt_publisher is not None and not isinstance(
            receipt_publisher, ResearchExperimentTrialReceiptPublisherPort
        ):
            raise TypeError(
                "Experiment Trial receipt publisher must satisfy typed port"
            )
        self._receipt_publisher = receipt_publisher
        if degradation_sink is not None and not isinstance(
            degradation_sink, DiagnosticDegradationPort
        ):
            raise TypeError("Experiment Trial degradation sink must satisfy typed port")
        self._degradation_sink = degradation_sink

    def resolve(
        self,
        execution: ResearchExperimentExecutionBindingView,
    ) -> ResearchExperimentStudyExecutionBinding:
        execution = require_experiment_execution_binding(execution)
        binding = self._providers.resolve(execution)
        if type(binding) is not ResearchExperimentTrialProviderBinding:
            raise TypeError(
                "Trial provider resolver returned invalid binding"
            )
        adapter = _TrialBoundStudyExecution(
            execution,
            binding,
            self._observation,
            self._receipt_publisher,
            self._degradation_sink,
        )
        identity = canonical_digest(
            {
                "schema": "noetrium.trial-bound-study-execution.v2",
                "execution_binding_digest": execution.binding_digest,
                "trial_provider_binding_digest": binding.binding_digest,
                "receipt_publisher": (
                    None
                    if self._receipt_publisher is None
                    else self._receipt_publisher.identity_digest
                ),
            }
        )
        return ResearchExperimentStudyExecutionBinding(
            adapter,
            identity,
            binding.resource_demand,
        )


__all__ = [
    "ResearchExperimentTrialProviderBinding",
    "ResearchExperimentTrialProviderRegistry",
    "ResearchExperimentTrialProviderRegistration",
    "ResearchExperimentTrialProviderResolverPort",
    "ResearchExperimentTrialObservationPort",
    "ResearchExperimentTrialReceiptPublisherPort",
    "ResearchExperimentTrialStudyExecutionResolver",
]
