"""Canonical TrialProvider -> BoundStudyExecution bridge for Research OS.

The bridge is composition only. Trial providers own domain execution, verifier
providers own verifier truth, ExperimentProgram owns scheduling, and Research OS
owns the durable execution cut. No second execution loop is introduced here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.lifecycle.api import (
    BoundStudyExecutionPort,
    MeasurementValueKind,
    StudyAssignment,
    StudyExecutionUnit,
    StudyMetricObservation,
    TaskVerifierPort,
    TrialExecutionReceipt,
    TrialExecutionRequest,
    TrialProviderPort,
    VariantBinding,
)
from noetrium_platform.research.experimentation.lifecycle.study.providers.trial import (
    TrialVerifierOrchestrator,
)

from .research_os_experiment import ResearchOSExperimentClosure
from .research_os_experiment_runtime_binding import (
    ResearchOSExperimentStudyExecutionBinding,
    ResearchOSExperimentStudyExecutionResolverPort,
)


@dataclass(frozen=True, slots=True)
class ResearchOSExperimentTrialProviderBinding:
    """Exact Trial provider/verifier authority for one Experiment closure."""

    provider_identity: str
    provider: TrialProviderPort
    provider_identity_digest: str
    verifier: TaskVerifierPort | None = None
    verifier_identity_digest: str | None = None
    binding_digest: str = ""

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
class ResearchOSExperimentTrialProviderRegistration:
    """One owner-system Trial provider registration with exact scientific identity."""

    provider_identity: str
    provider: TrialProviderPort
    provider_identity_digest: str
    verifier: TaskVerifierPort | None = None
    verifier_identity_digest: str | None = None
    registration_digest: str = ""

    def __post_init__(self) -> None:
        binding = ResearchOSExperimentTrialProviderBinding(
            self.provider_identity,
            self.provider,
            self.provider_identity_digest,
            self.verifier,
            self.verifier_identity_digest,
        )
        expected = canonical_digest(
            {
                "provider_binding_digest": binding.binding_digest,
                "protocol_identity_digest": self.provider.protocol_identity.digest(),
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


class ResearchOSExperimentTrialProviderRegistry:
    """Exact Trial provider registry keyed by Research-selected provider identity."""

    def __init__(
        self,
        registrations: tuple[
            ResearchOSExperimentTrialProviderRegistration, ...
        ],
    ) -> None:
        if type(registrations) is not tuple:
            raise TypeError(
                "Experiment Trial provider registry requires typed tuple"
            )
        if any(
            type(row) is not ResearchOSExperimentTrialProviderRegistration
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
                    row.provider.protocol_identity.digest(),
                    row.registration_digest,
                ),
            )
        )
        keys = tuple(
            (
                row.provider_identity,
                row.provider.protocol_identity.digest(),
            )
            for row in ordered
        )
        if len(keys) != len(set(keys)):
            raise ValueError(
                "Experiment Trial provider registry contains duplicate "
                "provider/protocol authority"
            )
        self._registrations = ordered
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
        closure: ResearchOSExperimentClosure,
    ) -> ResearchOSExperimentTrialProviderBinding:
        if type(closure) is not ResearchOSExperimentClosure:
            raise TypeError(
                "Experiment Trial provider registry requires "
                "ResearchOSExperimentClosure"
            )
        provider_ids = {
            row.provider_id
            for row in closure.research_plan.experiment_plan.bindings
        }
        if len(provider_ids) != 1:
            raise ValueError(
                "Experiment closure must select exactly one Trial provider identity"
            )
        provider_identity = next(iter(provider_ids))
        protocol_digest = closure.research_plan.trial_protocol_identity.digest()
        matches = tuple(
            row
            for row in self._registrations
            if row.provider_identity == provider_identity
            and row.provider.protocol_identity.digest() == protocol_digest
        )
        if len(matches) != 1:
            raise LookupError(
                "no unique Trial provider registration for "
                f"provider={provider_identity!r} protocol={protocol_digest}"
            )
        row = matches[0]
        return ResearchOSExperimentTrialProviderBinding(
            row.provider_identity,
            row.provider,
            row.provider_identity_digest,
            row.verifier,
            row.verifier_identity_digest,
        )


@runtime_checkable
class ResearchOSExperimentTrialProviderResolverPort(Protocol):
    """Resolve Trial/provider authority owned by the concrete execution system."""

    def resolve(
        self,
        closure: ResearchOSExperimentClosure,
    ) -> ResearchOSExperimentTrialProviderBinding: ...


@runtime_checkable
class ResearchOSExperimentTrialReceiptPublisherPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def publish(
        self,
        request: TrialExecutionRequest,
        receipt: TrialExecutionReceipt,
    ): ...


@runtime_checkable
class ResearchOSExperimentTrialObservationPort(Protocol):
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
        closure: ResearchOSExperimentClosure,
        provider_binding: ResearchOSExperimentTrialProviderBinding,
        observation: ResearchOSExperimentTrialObservationPort | None = None,
        receipt_publisher: ResearchOSExperimentTrialReceiptPublisherPort | None = None,
    ) -> None:
        self._closure = closure
        self._provider_binding = provider_binding
        if observation is not None and not isinstance(
            observation, ResearchOSExperimentTrialObservationPort
        ):
            raise TypeError("Trial Study observation must satisfy typed side-plane port")
        self._observation_sink = observation
        if receipt_publisher is not None and not isinstance(
            receipt_publisher, ResearchOSExperimentTrialReceiptPublisherPort
        ):
            raise TypeError(
                "Trial Study receipt_publisher must satisfy typed publisher port"
            )
        self._receipt_publisher = receipt_publisher
        provider_protocol = provider_binding.provider.protocol_identity
        if provider_protocol != closure.research_plan.trial_protocol_identity:
            raise ValueError(
                "Trial provider protocol identity does not match Research closure"
            )
        self._binding_by_variant = {
            row.variant.variant_id: row
            for row in closure.research_plan.experiment_plan.bindings
        }
        selected_provider_ids = {
            row.provider_id for row in self._binding_by_variant.values()
        }
        if selected_provider_ids != {provider_binding.provider_identity}:
            raise ValueError(
                "Trial provider identity does not match Research binding authority"
            )
        self._intervention_by_variant = {
            row.intervention_id: row
            for row in closure.research_plan.interventions
        }
        self._metric_names = tuple(
            closure.research_plan.protocol.metric_names
        )
        if not self._metric_names:
            raise ValueError(
                "canonical Trial Study execution requires at least one scalar "
                "measurement metric"
            )

    def _request(
        self,
        assignment: StudyAssignment,
        binding: VariantBinding,
        plan_digest: str,
        *,
        execution_id: str,
    ) -> TrialExecutionRequest:
        require_sha256(plan_digest, "Trial Study plan_digest")
        require_sha256(execution_id, "Trial Study execution_id")
        plan = self._closure.research_plan
        if plan_digest != plan.experiment_plan.plan_digest:
            raise ValueError("Trial Study execution plan digest drifted")
        expected_binding = self._binding_by_variant.get(assignment.variant_id)
        if expected_binding != binding:
            raise ValueError("Trial Study VariantBinding drifted")
        intervention = self._intervention_by_variant.get(assignment.variant_id)
        if intervention is None:
            raise ValueError(
                "Trial Study assignment has no matching intervention identity"
            )
        task_definitions = tuple(
            plan.task_for(task_id)
            for task_id in assignment.workload.task_ids
        )
        return TrialExecutionRequest(
            project_id=self._closure.definition.project_id,
            run_id=execution_id,
            research_plan_digest=plan.research_plan_digest,
            revision=plan.research_semantics.revision,
            participant_schedule=plan.research_semantics.participant_schedule,
            participant_schedule_spec=plan.participant_schedule,
            execution_policy=self._closure.definition.execution_policy,
            intervention_spec=intervention,
            assignment=assignment,
            binding=binding,
            measurement_protocol=plan.measurement_protocol,
            protocol_identity=plan.trial_protocol_identity,
            task_definitions=task_definitions,
        )

    def _observation(
        self,
        request: TrialExecutionRequest,
        receipt: TrialExecutionReceipt,
        receipt_reference,
    ) -> StudyMetricObservation:
        if receipt.request_digest != request.request_digest:
            raise ValueError("Trial receipt does not bind Study request")
        if receipt.assignment_digest != request.assignment.assignment_digest:
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
        if missing:
            raise ValueError(
                f"Trial receipt is missing Study scalar metrics: {missing}"
            )
        return StudyMetricObservation(
            request.assignment,
            tuple((name, values[name]) for name in self._metric_names),
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

    def execute_bound_variant(
        self,
        assignment: StudyAssignment,
        binding: VariantBinding,
        plan_digest: str,
        *,
        execution_id: str,
    ) -> StudyMetricObservation:
        request = self._request(
            assignment,
            binding,
            plan_digest,
            execution_id=execution_id,
        )
        provider_receipt = self._provider_binding.provider.run_trial(request)
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
            except Exception:
                # Observability is a side plane and cannot mutate Trial truth.
                pass
        return observation

    def execute_bound(
        self,
        unit: StudyExecutionUnit,
        bindings: tuple[VariantBinding, ...],
        plan_digest: str,
        *,
        execution_id: str,
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
                execution_id=execution_id,
            )
            for assignment, binding in zip(
                unit.assignments,
                bindings,
                strict=True,
            )
        )


class ResearchOSExperimentTrialStudyExecutionResolver(
    ResearchOSExperimentStudyExecutionResolverPort
):
    """Canonical Study execution resolver over owner-supplied Trial providers."""

    def __init__(
        self,
        providers: ResearchOSExperimentTrialProviderResolverPort,
        *,
        observation: ResearchOSExperimentTrialObservationPort | None = None,
        receipt_publisher: ResearchOSExperimentTrialReceiptPublisherPort | None = None,
    ) -> None:
        if not isinstance(
            providers,
            ResearchOSExperimentTrialProviderResolverPort,
        ):
            raise TypeError(
                "Trial Study execution resolver requires Trial provider resolver"
            )
        self._providers = providers
        if observation is not None and not isinstance(
            observation, ResearchOSExperimentTrialObservationPort
        ):
            raise TypeError("Experiment Trial observation must satisfy typed port")
        self._observation = observation
        if receipt_publisher is not None and not isinstance(
            receipt_publisher, ResearchOSExperimentTrialReceiptPublisherPort
        ):
            raise TypeError(
                "Experiment Trial receipt publisher must satisfy typed port"
            )
        self._receipt_publisher = receipt_publisher

    def resolve(
        self,
        closure: ResearchOSExperimentClosure,
    ) -> ResearchOSExperimentStudyExecutionBinding:
        if type(closure) is not ResearchOSExperimentClosure:
            raise TypeError(
                "Trial Study execution resolver requires ResearchOSExperimentClosure"
            )
        binding = self._providers.resolve(closure)
        if type(binding) is not ResearchOSExperimentTrialProviderBinding:
            raise TypeError(
                "Trial provider resolver returned invalid binding"
            )
        adapter = _TrialBoundStudyExecution(
            closure,
            binding,
            self._observation,
            self._receipt_publisher,
        )
        identity = canonical_digest(
            {
                "schema": "noetrium.trial-bound-study-execution.v2",
                "closure_digest": closure.closure_digest,
                "trial_provider_binding_digest": binding.binding_digest,
                "receipt_publisher": (
                    None
                    if self._receipt_publisher is None
                    else self._receipt_publisher.identity_digest
                ),
            }
        )
        return ResearchOSExperimentStudyExecutionBinding(
            adapter,
            identity,
        )


__all__ = [
    "ResearchOSExperimentTrialProviderBinding",
    "ResearchOSExperimentTrialProviderRegistry",
    "ResearchOSExperimentTrialProviderRegistration",
    "ResearchOSExperimentTrialProviderResolverPort",
    "ResearchOSExperimentTrialObservationPort",
    "ResearchOSExperimentTrialReceiptPublisherPort",
    "ResearchOSExperimentTrialStudyExecutionResolver",
]
