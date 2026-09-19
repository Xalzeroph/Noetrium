"""Neutral trial lifecycle shared by arbitrary paper-general loops."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from noetrium_platform.evidence.artifact.reference.api import ArtifactReference
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentTrialProtocolIdentity,
)
from noetrium_platform.research.experimentation.identity import OptionalIdentityFacet

from .benchmark import TaskArtifactSpec, TaskDefinition, TaskVerifierIsolation
from .contracts import StudyAssignment
from .measurement import MeasurementProtocol, MeasurementRecord, MeasurementValue
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


@dataclass(frozen=True, slots=True)
class TaskVerifierArtifact:
    """One explicitly declared artifact crossing into verifier execution."""

    declaration: TaskArtifactSpec
    reference: ArtifactReference
    artifact_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.declaration) is not TaskArtifactSpec:
            raise TypeError("verifier artifact declaration must be TaskArtifactSpec")
        if type(self.reference) is not ArtifactReference:
            raise TypeError("verifier artifact reference must be ArtifactReference")
        object.__setattr__(
            self,
            "artifact_digest",
            canonical_digest(
                {
                    "declaration": self.declaration,
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
    intervention: OptionalIdentityFacet
    revision: OptionalIdentityFacet
    task_digest: str
    task_package_digest: str
    verifier_requirement_id: str
    verifier_isolation: TaskVerifierIsolation
    verifier_environment_requirement_id: str | None
    measurement_protocol: MeasurementProtocol
    artifacts: tuple[TaskVerifierArtifact, ...]
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha(self.source_trial_request_digest, "verifier request source trial digest")
        for field_name in ("project_id", "study_id", "run_id", "variant_id"):
            _text(getattr(self, field_name), f"verifier request {field_name}")
        _sha(self.assignment_digest, "verifier request assignment_digest")
        if type(self.intervention) is not OptionalIdentityFacet:
            raise TypeError("verifier request intervention must be OptionalIdentityFacet")
        if type(self.revision) is not OptionalIdentityFacet:
            raise TypeError("verifier request revision must be OptionalIdentityFacet")
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
        if type(self.measurement_protocol) is not MeasurementProtocol:
            raise TypeError("verifier request measurement_protocol must be MeasurementProtocol")
        if type(self.artifacts) is not tuple or any(
            type(row) is not TaskVerifierArtifact for row in self.artifacts
        ):
            raise TypeError(
                "verifier request artifacts must contain TaskVerifierArtifact"
            )
        artifact_ids = tuple(row.declaration.artifact_id for row in self.artifacts)
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
                    "measurement_protocol_digest": self.measurement_protocol.protocol_digest,
                    "artifacts": tuple(row.artifact_digest for row in self.artifacts),
                }
            ),
        )

    @property
    def measurement_protocol_digest(self) -> str:
        return self.measurement_protocol.protocol_digest

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
        definition = self.measurement_protocol.definition(measurement_id)
        return MeasurementRecord(
            project_id=self.project_id,
            study_id=self.study_id,
            run_id=self.run_id,
            assignment_digest=self.assignment_digest,
            variant_id=self.variant_id,
            producer_id=producer_id,
            producer_revision_digest=producer_revision_digest,
            measurement_id=measurement_id,
            schema_id=definition.schema_id,
            measurement_semantic_digest=definition.semantic_contract_digest,
            measurement_protocol_semantic_digest=self.measurement_protocol.semantic_digest,
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
        task = trial_request.task
        if task is None:
            raise ValueError("verifier handoff requires a frozen task")
        package = task.package
        if package is None or package.verifier_requirement_id is None:
            raise ValueError("task package does not declare a verifier")
        if type(artifacts) is not tuple or any(
            type(row) is not TaskVerifierArtifact for row in artifacts
        ):
            raise TypeError("verifier handoff artifacts must be typed")
        declared = {row.artifact_id: row for row in package.artifacts}
        provided = {row.declaration.artifact_id: row for row in artifacts}
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
            row.artifact_id
            for row in package.artifacts
            if row.required and row.artifact_id not in provided
        )
        if missing:
            raise ValueError(
                f"verifier handoff is missing required artifacts: {missing}"
            )
        ordered = tuple(
            provided[row.artifact_id]
            for row in package.artifacts
            if row.artifact_id in provided
        )
        return cls(
            source_trial_request_digest=trial_request.request_digest,
            project_id=trial_request.project_id,
            study_id=trial_request.assignment.study_id,
            run_id=trial_request.run_id,
            assignment_digest=trial_request.assignment.assignment_digest,
            variant_id=trial_request.assignment.variant_id,
            intervention=trial_request.intervention,
            revision=trial_request.revision,
            task_digest=task.task_digest,
            task_package_digest=package.package_digest,
            verifier_requirement_id=package.verifier_requirement_id,
            verifier_isolation=package.verifier_isolation,
            verifier_environment_requirement_id=(
                package.verifier_environment_requirement_id
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
    run_id: str
    research_plan_digest: str
    revision: OptionalIdentityFacet
    participant_schedule: OptionalIdentityFacet
    intervention: OptionalIdentityFacet
    assignment: StudyAssignment
    binding: VariantBinding
    measurement_protocol: MeasurementProtocol
    protocol_identity: ExperimentTrialProtocolIdentity
    task: TaskDefinition | None = None
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.project_id, "trial request project_id")
        _text(self.run_id, "trial request run_id")
        _sha(self.research_plan_digest, "trial request research_plan_digest")
        if type(self.revision) is not OptionalIdentityFacet:
            raise TypeError("trial request revision must be OptionalIdentityFacet")
        if type(self.participant_schedule) is not OptionalIdentityFacet:
            raise TypeError(
                "trial request participant_schedule must be OptionalIdentityFacet"
            )
        if type(self.intervention) is not OptionalIdentityFacet:
            raise TypeError(
                "trial request intervention must be OptionalIdentityFacet"
            )
        if type(self.assignment) is not StudyAssignment:
            raise TypeError("trial request assignment must be StudyAssignment")
        if type(self.binding) is not VariantBinding:
            raise TypeError("trial request binding must be VariantBinding")
        if self.assignment.variant_id != self.binding.variant.variant_id:
            raise ValueError("trial request binding does not match assignment")
        if type(self.measurement_protocol) is not MeasurementProtocol:
            raise TypeError(
                "trial request measurement_protocol must be MeasurementProtocol"
            )
        if type(self.protocol_identity) is not ExperimentTrialProtocolIdentity:
            raise TypeError(
                "trial request protocol_identity must be ExperimentTrialProtocolIdentity"
            )
        if self.task is not None:
            if type(self.task) is not TaskDefinition:
                raise TypeError("trial request task must be TaskDefinition or None")
            if self.assignment.task_id != self.task.task_id:
                raise ValueError("trial request task does not match assignment")
        object.__setattr__(
            self,
            "request_digest",
            canonical_digest(
                {
                    "project_id": self.project_id,
                    "run_id": self.run_id,
                    "research_plan_digest": self.research_plan_digest,
                    "revision": self.revision,
                    "participant_schedule": self.participant_schedule,
                    "intervention": self.intervention,
                    "assignment_digest": self.assignment.assignment_digest,
                    "binding_digest": self.binding.binding_digest,
                    "measurement_protocol_digest": (
                        self.measurement_protocol.protocol_digest
                    ),
                    "protocol_identity_digest": self.protocol_identity.digest(),
                    "task_digest": (
                        None if self.task is None else self.task.task_digest
                    ),
                    "task_package_digest": (
                        None
                        if self.task is None or self.task.package is None
                        else self.task.package.package_digest
                    ),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class TrialExecutionStageReceipt:
    """Provider output before any task-declared verifier is allowed to run.

    For verifier-backed tasks the core requires measurements to be empty and
    transfers only the declared verifier artifacts across the boundary.
    """

    request_digest: str
    assignment_digest: str
    measurements: tuple[MeasurementRecord, ...] = ()
    verifier_artifacts: tuple[TaskVerifierArtifact, ...] = ()
    evidence_refs: tuple[ArtifactReference, ...] = ()
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
            row.declaration.artifact_id for row in self.verifier_artifacts
        )
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("trial stage verifier artifacts must be unique")
        if type(self.evidence_refs) is not tuple or any(
            type(row) is not ArtifactReference for row in self.evidence_refs
        ):
            raise TypeError("trial stage evidence_refs must contain ArtifactReference")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("trial stage evidence_refs must be unique")
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
            if self.verifier_receipt.measurements != self.measurements:
                raise ValueError(
                    "trial receipt measurements must equal verifier measurements"
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
                    "verifier_receipt_digest": (
                        None
                        if self.verifier_receipt is None
                        else self.verifier_receipt.receipt_digest
                    ),
                }
            ),
        )


class TrialProviderPort(Protocol):
    protocol_identity: ExperimentTrialProtocolIdentity

    def run_trial(
        self, request: TrialExecutionRequest
    ) -> TrialExecutionReceipt | TrialExecutionStageReceipt: ...


@dataclass(frozen=True, slots=True)
class TrialMatrixExecutionReport:
    project_id: str
    run_id: str
    research_plan_digest: str
    records: tuple[MeasurementRecord, ...]
    trial_receipt_digests: tuple[str, ...]
    report_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.project_id, "trial report project_id")
        _text(self.run_id, "trial report run_id")
        _sha(self.research_plan_digest, "trial report research_plan_digest")
        if type(self.records) is not tuple or any(
            type(row) is not MeasurementRecord for row in self.records
        ):
            raise TypeError(
                "trial report records must contain MeasurementRecord"
            )
        if type(self.trial_receipt_digests) is not tuple or any(
            type(row) is not str for row in self.trial_receipt_digests
        ):
            raise TypeError("trial report receipt digests must be strings")
        for digest in self.trial_receipt_digests:
            _sha(digest, "trial report receipt digest")
        object.__setattr__(
            self,
            "report_digest",
            canonical_digest(
                {
                    "project_id": self.project_id,
                    "run_id": self.run_id,
                    "research_plan_digest": self.research_plan_digest,
                    "records": tuple(
                        row.record_digest for row in self.records
                    ),
                    "receipts": self.trial_receipt_digests,
                }
            ),
        )


__all__ = [
    "TaskVerifierArtifact",
    "TaskVerifierPort",
    "TaskVerifierReceipt",
    "TaskVerifierRequest",
    "TrialExecutionReceipt",
    "TrialExecutionRequest",
    "TrialExecutionStageReceipt",
    "TrialMatrixExecutionReport",
    "TrialProviderPort",
]
