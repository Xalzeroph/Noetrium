from __future__ import annotations

from noetrium_platform.foundation.governance.architecture.api import (
    BindingDiagnostic,
    BindingDiagnosticCode,
    BindingDiagnosticReference,
    BindingDiagnosticReferenceKind,
    BindingDiagnosticSeverity,
    BindingProof,
    BindingRemediationCategory,
    BindingResolution,
    CompositionSubject,
    RequirementAddress,
)
from noetrium_platform.capabilities.participant.api.project import (
    ParticipantBindingDiagnostic,
    ParticipantBindingDiagnosticCode,
    ParticipantBindingDiagnosticSeverity,
    ParticipantProjectBindingError,
    ParticipantRequirement,
    ProjectParticipantBinding,
    ProjectParticipantProviderPort,
)
from noetrium_platform.foundation.kernel.kernel import Sha256Digest


_CODE = {
    ParticipantBindingDiagnosticCode.KIND_UNSUPPORTED: "participant.kind_unsupported",
    ParticipantBindingDiagnosticCode.CAPABILITY_MISSING: "participant.capability_missing",
    ParticipantBindingDiagnosticCode.RUNTIME_UNAVAILABLE: "participant.runtime_unavailable",
    ParticipantBindingDiagnosticCode.BINDING_PROVENANCE_DRIFT: "participant.binding_provenance_drift",
}

_REMEDIATION = {
    ParticipantBindingDiagnosticCode.KIND_UNSUPPORTED: BindingRemediationCategory.PROVIDER_SELECTION,
    ParticipantBindingDiagnosticCode.CAPABILITY_MISSING: BindingRemediationCategory.CAPABILITY,
    ParticipantBindingDiagnosticCode.RUNTIME_UNAVAILABLE: BindingRemediationCategory.OWNER_ACTION,
    ParticipantBindingDiagnosticCode.BINDING_PROVENANCE_DRIFT: BindingRemediationCategory.INTERFACE,
}


def _severity(value: ParticipantBindingDiagnosticSeverity) -> BindingDiagnosticSeverity:
    return BindingDiagnosticSeverity(value.value)


def _evidence_refs(values: tuple[str, ...]) -> tuple[BindingDiagnosticReference, ...]:
    return tuple(
        BindingDiagnosticReference(BindingDiagnosticReferenceKind.EVIDENCE, value)
        for value in values
    )


def project_participant_diagnostic(
    diagnostic: ParticipantBindingDiagnostic,
    *,
    owner: CompositionSubject,
    subject: CompositionSubject,
    requirement_id: str,
    provider_profile_digest: str,
) -> BindingDiagnostic:
    if not isinstance(diagnostic, ParticipantBindingDiagnostic):
        raise TypeError("participant diagnostic projection requires ParticipantBindingDiagnostic")
    requirement = RequirementAddress(subject, requirement_id)
    return BindingDiagnostic(
        code=BindingDiagnosticCode(_CODE[diagnostic.code]),
        severity=_severity(diagnostic.severity),
        blocking=diagnostic.severity is ParticipantBindingDiagnosticSeverity.ERROR,
        owner=owner,
        subject=subject,
        requirement_digest=Sha256Digest(diagnostic.requirement_digest),
        summary=diagnostic.message,
        requirement=requirement,
        provider_identity=diagnostic.provider_id,
        provider_profile_digest=Sha256Digest(provider_profile_digest),
        related_refs=_evidence_refs(diagnostic.evidence_refs),
        remediation=_REMEDIATION[diagnostic.code],
    )


class ParticipantBindingResolutionAdapter:
    """Project Participant binding into the neutral PSC-03 envelope."""

    def __init__(
        self,
        provider: ProjectParticipantProviderPort,
        *,
        owner: CompositionSubject,
        subject: CompositionSubject,
        requirement_id: str,
    ) -> None:
        if not isinstance(provider, ProjectParticipantProviderPort):
            raise TypeError("participant binding resolution requires ProjectParticipantProviderPort")
        if not isinstance(owner, CompositionSubject) or not isinstance(subject, CompositionSubject):
            raise TypeError("participant binding resolution owner/subject must be CompositionSubject")
        self._provider = provider
        self._owner = owner
        self._subject = subject
        self._requirement_id = RequirementAddress(subject, requirement_id).requirement_id
    def resolve(
        self, requirement: ParticipantRequirement
    ) -> BindingResolution[ProjectParticipantBinding]:
        if not isinstance(requirement, ParticipantRequirement):
            raise TypeError("participant binding resolution requires ParticipantRequirement")
        try:
            binding = self._provider.bind(requirement)
        except ParticipantProjectBindingError as exc:
            profile_digest = self._provider.profile.digest()
            diagnostics = tuple(
                project_participant_diagnostic(
                    item,
                    owner=self._owner,
                    subject=self._subject,
                    requirement_id=self._requirement_id,
                    provider_profile_digest=profile_digest,
                )
                for item in exc.diagnostics
            )
            return BindingResolution.diagnosed(diagnostics)
        if binding.requirement_digest != requirement.digest():
            raise ValueError("participant binding resolution requirement drift")
        proof = BindingProof(
            owner=self._owner,
            subject=self._subject,
            requirement_digest=Sha256Digest(binding.requirement_digest),
            provider_identity=binding.provider_id,
            provider_profile_digest=Sha256Digest(binding.provider_profile_digest),
            binding_generation=f"participant-{binding.binding.runtime.digest()}",
        )
        return BindingResolution.bound(binding, proof)


__all__ = [
    "ParticipantBindingResolutionAdapter",
    "project_participant_diagnostic",
]
