from __future__ import annotations
from noetrium_platform.research.experimentation.lifecycle.study.api.contracts import study_assignment_digest, study_assignment_text, study_assignment_workload
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
"""Neutral trial lifecycle shared by arbitrary paper-general loops."""


from noetrium_platform.research.experimentation.lifecycle.study.api.contracts import (
    assignment_workload,
    assignment_workload_dependencies_for,
    assignment_workload_digest,
    assignment_workload_prerequisites_for,
    assignment_workload_retry_sources_for,
    assignment_workload_task_ids,
    validate_assignment_workload,
)

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from noetrium_platform.research.execution.api import ArtifactReference
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_digest, freeze_json
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort

from .benchmark import TaskVerifierIsolation
from .contracts import NoetriumUnit
from .measurement import MeasurementRecord, MeasurementValue
from .unit_semantics import (
    execution_policy_replay_level,
    intervention_digest,
    measurement_definitions,
    measurement_id as measurement_unit_id,
    measurement_protocol_semantic_digest,
    measurement_schema_id,
    measurement_semantic_digest,
    participant_schedule_digest,
    require_task_unit,
    task_id,
    task_package,
    trial_protocol_digest,
)
from .plan import VariantBinding

_HEX = frozenset("0123456789abcdef")


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _sha(value: object, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(ch not in _HEX for ch in text):
        raise ValueError(f"{field} must be lowercase SHA-256")
    return text


def _optional_sha(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    return _sha(value, field)


def _artifact_declaration(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("verifier artifact declaration must be a mapping")
    artifact_id = _text(value.get("artifact_id"), "verifier artifact id")
    relative_path = _text(value.get("relative_path"), "verifier artifact relative_path")
    required = value.get("required", True)
    if type(required) is not bool:
        raise TypeError("verifier artifact required must be boolean")
    return freeze_json({
        "artifact_id": artifact_id,
        "relative_path": relative_path,
        "required": required,
    })


def _artifact_id(value: Mapping[str, object]) -> str:
    return str(value["artifact_id"])


@dataclass(frozen=True, slots=True)
class TaskVerifierArtifact:
    """One explicitly declared artifact crossing into verifier execution."""

    declaration: Mapping[str, object]
    reference: ArtifactReference
    artifact_digest: str = field(init=False)

    def __post_init__(self) -> None:
        declaration = _artifact_declaration(self.declaration)
        object.__setattr__(self, "declaration", declaration)
        if type(self.reference) is not ArtifactReference:
            raise TypeError("verifier artifact reference must be ArtifactReference")
        object.__setattr__(
            self,
            "artifact_digest",
            canonical_digest(
                {
                    "declaration": dict(self.declaration),
                    "reference": self.reference,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class TaskVerifierRequest:
    """Minimal scientific context plus artifact-only verifier handoff.

    The verifier receives enough frozen identity to emit valid MeasurementRecord
    values, but never receives the execution environment, participant session,
    method state, work directory, or arbitrary trial-provider internals.
    """

    source_trial_request_digest: str
    project_id: str
    study_id: str
    run_id: str
    assignment_digest: str
    variant_id: str
    intervention: str | None
    revision: str | None
    task_digest: str
    task_package_digest: str
    verifier_requirement_id: str
    verifier_isolation: TaskVerifierIsolation
    verifier_environment_requirement_id: str | None
    measurement_protocol: NoetriumUnit
    artifacts: tuple[TaskVerifierArtifact, ...]
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha(self.source_trial_request_digest, "verifier request source trial digest")
        for field_name in ("project_id", "study_id", "run_id", "variant_id"):
            _text(getattr(self, field_name), f"verifier request {field_name}")
        _sha(self.assignment_digest, "verifier request assignment_digest")
        _optional_sha(self.intervention, "verifier request intervention")
        _optional_sha(self.revision, "verifier request revision")
        _sha(self.task_digest, "verifier request task_digest")
        _sha(self.task_package_digest, "verifier request task_package_digest")
        _text(self.verifier_requirement_id, "verifier request verifier requirement")
        if not isinstance(self.verifier_isolation, TaskVerifierIsolation):
            raise TypeError("verifier request isolation must be TaskVerifierIsolation")
        if self.verifier_environment_requirement_id is not None:
            _text(
                self.verifier_environment_requirement_id,
                "verifier request verifier environment requirement",
            )
        measurement_protocol_semantic_digest(self.measurement_protocol)
        if type(self.artifacts) is not tuple or any(
            type(row) is not TaskVerifierArtifact for row in self.artifacts
        ):
            raise TypeError(
                "verifier request artifacts must contain TaskVerifierArtifact"
            )
        artifact_ids = tuple(_artifact_id(row.declaration) for row in self.artifacts)
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("verifier request artifact declarations must be unique")
        object.__setattr__(
            self,
            "request_digest",
            canonical_digest(
                {
                    "source_trial_request_digest": self.source_trial_request_digest,
                    "project_id": self.project_id,
                    "study_id": self.study_id,
                    "run_id": self.run_id,
                    "assignment_digest": self.assignment_digest,
                    "variant_id": self.variant_id,
                    "intervention": self.intervention,
                    "revision": self.revision,
                    "task_digest": self.task_digest,
                    "task_package_digest": self.task_package_digest,
                    "verifier_requirement_id": self.verifier_requirement_id,
                    "verifier_isolation": self.verifier_isolation.value,
                    "verifier_environment_requirement_id": (
                        self.verifier_environment_requirement_id
                    ),
                    "measurement_protocol_digest": self.measurement_protocol.unit_digest,
                    "artifacts": tuple(row.artifact_digest for row in self.artifacts),
                }
            ),
        )

    @property
    def measurement_protocol_digest(self) -> str:
        return self.measurement_protocol.unit_digest

    def measurement(
        self,
        measurement_id: str,
        value: MeasurementValue,
        *,
        producer_id: str,
        producer_revision_digest: str,
        logical_time: str,
        lineage_refs: tuple[ArtifactReference, ...] = (),
    ) -> MeasurementRecord:
        """Create a measurement bound to this exact verifier execution context."""

        if type(value) is not MeasurementValue:
            raise TypeError("verifier measurement value must be MeasurementValue")
        definitions = tuple(
            row
            for row in measurement_definitions(self.measurement_protocol)
            if measurement_unit_id(row) == measurement_id
        )
        if len(definitions) != 1:
            raise KeyError(f"measurement protocol has no unique {measurement_id!r}")
        definition = definitions[0]
        return MeasurementRecord(
            project_id=self.project_id,
            study_id=self.study_id,
            run_id=self.run_id,
            assignment_digest=self.assignment_digest,
            variant_id=self.variant_id,
            producer_id=producer_id,
            producer_revision_digest=producer_revision_digest,
            measurement_id=measurement_id,
            schema_id=measurement_schema_id(definition),
            measurement_semantic_digest=measurement_semantic_digest(definition),
            measurement_protocol_semantic_digest=measurement_protocol_semantic_digest(self.measurement_protocol),
            value=value,
            logical_time=logical_time,
            intervention=self.intervention,
            revision=self.revision,
            lineage_refs=lineage_refs,
        )

    @classmethod
    def for_trial(
        cls,
        *,
        trial_request: "TrialExecutionRequest",
        artifacts: tuple[TaskVerifierArtifact, ...],
    ) -> "TaskVerifierRequest":
        if type(trial_request) is not TrialExecutionRequest:
            raise TypeError("verifier handoff requires TrialExecutionRequest")
        verifier_tasks = tuple(
            task
            for task in trial_request.task_definitions
            if task_package(task) is not None
            and task_package(task).get("verifier_requirement_id") is not None
        )
        if len(verifier_tasks) != 1:
            raise ValueError(
                "verifier handoff requires exactly one verifier-backed frozen task"
            )
        task = verifier_tasks[0]
        package = task_package(task)
        assert package is not None and package.get("verifier_requirement_id") is not None
        if type(artifacts) is not tuple or any(
            type(row) is not TaskVerifierArtifact for row in artifacts
        ):
            raise TypeError("verifier handoff artifacts must be typed")
        declared = {
            str(row["artifact_id"]): row
            for row in package.get("artifacts", ())
        }
        provided = {_artifact_id(row.declaration): row for row in artifacts}
        undeclared = set(provided) - set(declared)
        if undeclared:
            raise ValueError(
                f"verifier handoff contains undeclared artifacts: {sorted(undeclared)}"
            )
        for artifact_id, row in provided.items():
            if row.declaration != declared[artifact_id]:
                raise ValueError(
                    f"verifier artifact declaration drifted: {artifact_id}"
                )
        missing = tuple(
            str(row["artifact_id"])
            for row in package.get("artifacts", ())
            if bool(row.get("required", True))
            and str(row["artifact_id"]) not in provided
        )
        if missing:
            raise ValueError(
                f"verifier handoff is missing required artifacts: {missing}"
            )
        ordered = tuple(
            provided[str(row["artifact_id"])]
            for row in package.get("artifacts", ())
            if str(row["artifact_id"]) in provided
        )
        return cls(
            source_trial_request_digest=trial_request.request_digest,
            project_id=trial_request.project_id,
            study_id=study_assignment_text(trial_request.assignment, "study_id"),
            run_id=trial_request.run_id,
            assignment_digest=study_assignment_digest(trial_request.assignment),
            variant_id=study_assignment_text(trial_request.assignment, "variant_id"),
            intervention=trial_request.intervention,
            revision=trial_request.revision,
            task_digest=task.unit_digest,
            task_package_digest=str(package["package_digest"]),
            verifier_requirement_id=str(package["verifier_requirement_id"]),
            verifier_isolation=TaskVerifierIsolation(str(package.get("verifier_isolation", TaskVerifierIsolation.SEPARATE.value))),
            verifier_environment_requirement_id=(
                None
                if package.get("verifier_environment_requirement_id") is None
                else str(package["verifier_environment_requirement_id"])
            ),
            measurement_protocol=trial_request.measurement_protocol,
            artifacts=ordered,
        )


@dataclass(frozen=True, slots=True)
class TaskVerifierReceipt:
    """Verifier outcome plus evidence that declared isolation was honored."""

    request: TaskVerifierRequest
    measurements: tuple[MeasurementRecord, ...]
    evidence_refs: tuple[ArtifactReference, ...] = ()
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.request) is not TaskVerifierRequest:
            raise TypeError("verifier receipt request must be TaskVerifierRequest")
        if type(self.measurements) is not tuple or any(
            type(row) is not MeasurementRecord for row in self.measurements
        ):
            raise TypeError(
                "verifier receipt measurements must contain MeasurementRecord"
            )
        if type(self.evidence_refs) is not tuple or any(
            type(row) is not ArtifactReference for row in self.evidence_refs
        ):
            raise TypeError(
                "verifier receipt evidence_refs must contain ArtifactReference"
            )
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("verifier receipt evidence_refs must be unique")
        if (
            self.request.verifier_isolation is TaskVerifierIsolation.SEPARATE
            and not self.evidence_refs
        ):
            raise ValueError(
                "separate verifier execution requires isolation evidence"
            )
        object.__setattr__(
            self,
            "receipt_digest",
            canonical_digest(
                {
                    "request_digest": self.request.request_digest,
                    "measurements": tuple(
                        row.record_digest for row in self.measurements
                    ),
                    "evidence_refs": self.evidence_refs,
                }
            ),
        )


class TaskVerifierPort(Protocol):
    def verify(self, request: TaskVerifierRequest) -> TaskVerifierReceipt: ...


@dataclass(frozen=True, slots=True)
class TrialExecutionRequest:
    project_id: str
    experiment_id: str
    run_id: str
    research_plan_digest: str
    revision: str | None
    participant_schedule: str | None
    participant_schedule_spec: NoetriumUnit | None
    execution_policy: NoetriumUnit
    intervention_spec: NoetriumUnit
    assignment: NoetriumUnit
    binding: VariantBinding
    measurement_protocol: NoetriumUnit
    protocol_identity: NoetriumUnit
    task_definitions: tuple[NoetriumUnit, ...]
    execution_context: ExecutionContext
    scientific_inputs: Mapping[str, object] = field(default_factory=dict)
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.project_id, "trial request project_id")
        _text(self.experiment_id, "trial request experiment_id")
        _text(self.run_id, "trial request run_id")
        if not isinstance(self.execution_context, ExecutionContext):
            raise TypeError("trial request execution_context must be ExecutionContext")
        if self.execution_context.run_id != self.run_id:
            raise ValueError("trial request execution context/run identity drift")
        if self.execution_context.experiment_id != self.experiment_id:
            raise ValueError("trial request execution context/experiment identity drift")
        _sha(self.research_plan_digest, "trial request research_plan_digest")
        _optional_sha(self.revision, "trial request revision")
        _optional_sha(self.participant_schedule, "trial request participant_schedule")
        if self.participant_schedule_spec is not None:
            participant_schedule_digest(self.participant_schedule_spec)
        if (
            (self.participant_schedule is not None)
            != (self.participant_schedule_spec is not None)
        ):
            raise ValueError(
                "trial request participant schedule identity/spec applicability drifted"
            )
        if (
            self.participant_schedule_spec is not None
            and self.participant_schedule
            != participant_schedule_digest(self.participant_schedule_spec)
        ):
            raise ValueError(
                "trial request participant schedule identity/spec digest drifted"
            )
        execution_policy_replay_level(self.execution_policy)
        intervention_digest(self.intervention_spec)
        if type(self.assignment) is not NoetriumUnit:
            raise TypeError("trial request assignment must be NoetriumUnit")
        if type(self.binding) is not VariantBinding:
            raise TypeError("trial request binding must be VariantBinding")
        if study_assignment_text(self.assignment, "variant_id") != self.binding.variant.unit_id:
            raise ValueError("trial request binding does not match assignment")
        if self.binding.intervention_digest != intervention_digest(self.intervention_spec):
            raise ValueError(
                "trial request intervention does not match variant binding"
            )
        measurement_protocol_semantic_digest(self.measurement_protocol)
        trial_protocol_digest(self.protocol_identity)
        if (
            type(self.task_definitions) is not tuple
            or not self.task_definitions
            or any(type(row) is not NoetriumUnit for row in self.task_definitions)
        ):
            raise TypeError(
                "trial request task_definitions must be a non-empty Unit tuple"
            )
        for row in self.task_definitions:
            require_task_unit(row)
        if not isinstance(self.scientific_inputs, Mapping):
            raise TypeError("trial request scientific_inputs must be an object")
        object.__setattr__(
            self,
            "scientific_inputs",
            freeze_json(dict(self.scientific_inputs)),
        )
        task_ids = tuple(task_id(row) for row in self.task_definitions)
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("trial request task definition ids must be unique")
        if task_ids != assignment_workload_task_ids(study_assignment_workload(self.assignment)):
            raise ValueError(
                "trial request task definitions do not match assignment workload"
            )
        object.__setattr__(
            self,
            "request_digest",
            canonical_digest(
                {
                    "project_id": self.project_id,
                    "experiment_id": self.experiment_id,
                    "run_id": self.run_id,
                    "research_plan_digest": self.research_plan_digest,
                    "revision": self.revision,
                    "participant_schedule": self.participant_schedule,
                    "participant_schedule_spec": self.participant_schedule_spec,
                    "execution_policy_digest": self.execution_policy.unit_digest,
                    "intervention_spec_digest": (
                        intervention_digest(self.intervention_spec)
                    ),
                    "assignment_digest": study_assignment_digest(self.assignment),
                    "binding_digest": self.binding.binding_digest,
                    "measurement_protocol_digest": (
                        self.measurement_protocol.unit_digest
                    ),
                    "protocol_identity_digest": trial_protocol_digest(self.protocol_identity),
                    "task_definition_digests": tuple(
                        row.unit_digest for row in self.task_definitions
                    ),
                    "scientific_inputs": self.scientific_inputs,
                }
            ),
        )

    @property
    def assignment_lifetime_id(self) -> str:
        """Physical lifetime identity for one assignment inside one execution.

        NoetriumUnit identity is intentionally stable across independent
        executions. Stateful runtime resources must not be: they may be reused
        only while the same execution is continuing or resuming.
        """
        return canonical_digest(
            {
                "schema": "noetrium.trial-assignment-lifetime.v1",
                "run_id": self.run_id,
                "assignment_digest": study_assignment_digest(self.assignment),
            }
        )

    @property
    def intervention(self) -> str:
        return intervention_digest(self.intervention_spec)



@dataclass(frozen=True, slots=True)
class TrialExecutionStageReceipt:
    """Provider output before any task-declared verifier is allowed to run.

    Execution-owned measurements may accompany the explicitly declared verifier
    artifacts. The verifier owns only its disjoint measurement identities.
    """

    request_digest: str
    assignment_digest: str
    measurements: tuple[MeasurementRecord, ...] = ()
    verifier_artifacts: tuple[TaskVerifierArtifact, ...] = ()
    evidence_refs: tuple[ArtifactReference, ...] = ()
    unobserved_measurement_ids: tuple[str, ...] = ()
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha(self.request_digest, "trial stage request_digest")
        _sha(self.assignment_digest, "trial stage assignment_digest")
        if type(self.measurements) is not tuple or any(
            type(row) is not MeasurementRecord for row in self.measurements
        ):
            raise TypeError("trial stage measurements must contain MeasurementRecord")
        if type(self.verifier_artifacts) is not tuple or any(
            type(row) is not TaskVerifierArtifact for row in self.verifier_artifacts
        ):
            raise TypeError(
                "trial stage verifier_artifacts must contain TaskVerifierArtifact"
            )
        artifact_ids = tuple(
            _artifact_id(row.declaration) for row in self.verifier_artifacts
        )
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("trial stage verifier artifacts must be unique")
        if type(self.evidence_refs) is not tuple or any(
            type(row) is not ArtifactReference for row in self.evidence_refs
        ):
            raise TypeError("trial stage evidence_refs must contain ArtifactReference")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("trial stage evidence_refs must be unique")
        missing = self.unobserved_measurement_ids
        if (type(missing) is not tuple or len(missing) != len(set(missing))
            or any(type(v) is not str or not v for v in missing)
            or set(missing) & {v.measurement_id for v in self.measurements}):
            raise ValueError("trial stage unobserved measurements invalid")
        object.__setattr__(
            self,
            "receipt_digest",
            canonical_digest(
                {
                    "request_digest": self.request_digest,
                    "assignment_digest": self.assignment_digest,
                    "measurements": tuple(
                        row.record_digest for row in self.measurements
                    ),
                    "unobserved_measurement_ids": self.unobserved_measurement_ids,
                    "verifier_artifacts": tuple(
                        row.artifact_digest for row in self.verifier_artifacts
                    ),
                    "evidence_refs": self.evidence_refs,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class TrialExecutionReceipt:
    request_digest: str
    assignment_digest: str
    measurements: tuple[MeasurementRecord, ...]
    evidence_refs: tuple[ArtifactReference, ...] = ()
    verifier_receipt: TaskVerifierReceipt | None = None
    unobserved_measurement_ids: tuple[str, ...] = ()
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha(self.request_digest, "trial receipt request_digest")
        _sha(self.assignment_digest, "trial receipt assignment_digest")
        if type(self.measurements) is not tuple:
            raise TypeError("trial receipt measurements must be a tuple")
        if any(type(row) is not MeasurementRecord for row in self.measurements):
            raise TypeError(
                "trial receipt measurements must contain MeasurementRecord"
            )
        measurement_by_id = {
            row.measurement_id: row for row in self.measurements
        }
        if len(measurement_by_id) != len(self.measurements):
            raise ValueError("trial receipt measurement identities must be unique")
        missing = self.unobserved_measurement_ids
        if (type(missing) is not tuple or len(missing) != len(set(missing))
            or any(type(v) is not str or not v for v in missing)
            or set(missing) & set(measurement_by_id)):
            raise ValueError("trial unobserved measurements invalid")
        if type(self.evidence_refs) is not tuple or any(
            type(row) is not ArtifactReference for row in self.evidence_refs
        ):
            raise TypeError(
                "trial receipt evidence_refs must contain ArtifactReference"
            )
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("trial receipt evidence_refs must be unique")
        if self.verifier_receipt is not None:
            if type(self.verifier_receipt) is not TaskVerifierReceipt:
                raise TypeError(
                    "trial receipt verifier_receipt must be TaskVerifierReceipt or None"
                )
            if (
                self.verifier_receipt.request.source_trial_request_digest
                != self.request_digest
            ):
                raise ValueError("trial receipt verifier does not bind the trial request")
            for row in self.verifier_receipt.measurements:
                if measurement_by_id.get(row.measurement_id) != row:
                    raise ValueError(
                        "trial receipt must preserve verifier measurements exactly"
                    )
        object.__setattr__(
            self,
            "receipt_digest",
            canonical_digest(
                {
                    "request_digest": self.request_digest,
                    "assignment_digest": self.assignment_digest,
                    "measurements": tuple(
                        row.record_digest for row in self.measurements
                    ),
                    "evidence_refs": self.evidence_refs,
                    "unobserved_measurement_ids": self.unobserved_measurement_ids,
                    "verifier_receipt_digest": (
                        None
                        if self.verifier_receipt is None
                        else self.verifier_receipt.receipt_digest
                    ),
                }
            ),
        )


@runtime_checkable
class TrialMeasurementProjectionPort(Protocol):
    """Project extension seam from an execution result into frozen Study measurements."""

    @property
    def identity_digest(self) -> str: ...

    def project(
        self,
        request: TrialExecutionRequest,
        result: object,
    ) -> tuple[MeasurementRecord, ...]: ...


@runtime_checkable
class TrialPreparationPort(Protocol):
    """Optional pre-execution preparation under the caller-owned control."""

    def prepare_trial(
        self,
        request: TrialExecutionRequest,
        control: ExecutionControlPort,
    ) -> None: ...


@runtime_checkable
class TrialProviderPort(Protocol):
    protocol_identity: NoetriumUnit

    def run_trial(
        self,
        request: TrialExecutionRequest,
        control: ExecutionControlPort,
    ) -> TrialExecutionReceipt | TrialExecutionStageReceipt: ...


__all__ = [
    "TaskVerifierArtifact",
    "TaskVerifierPort",
    "TaskVerifierReceipt",
    "TaskVerifierRequest",
    "TrialExecutionReceipt",
    "TrialExecutionRequest",
    "TrialExecutionStageReceipt",
    "TrialMeasurementProjectionPort",
    "TrialProviderPort",
]
