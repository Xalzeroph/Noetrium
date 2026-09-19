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
from noetrium_platform.capabilities.model.api.project import (
    ModelBindingDiagnostic,
    ModelBindingDiagnosticCode,
    ModelBindingDiagnosticSeverity,
    ModelCapabilityRequirement,
    ModelProjectBindingError,
    ProjectModelBinding,
    ProjectModelProviderPort,
)
from noetrium_platform.foundation.kernel.kernel import Sha256Digest


_CODE = {
    ModelBindingDiagnosticCode.CAPABILITY_MISSING: "model.capability_missing",
    ModelBindingDiagnosticCode.QUALIFIED_BINDING_UNAVAILABLE: "model.qualified_binding_unavailable",
    ModelBindingDiagnosticCode.CONTEXT_INSUFFICIENT: "model.context_insufficient",
    ModelBindingDiagnosticCode.BINDING_PROVENANCE_DRIFT: "model.binding_provenance_drift",
    ModelBindingDiagnosticCode.CAPABILITY_PROTOCOL_UNSUPPORTED: "model.capability_protocol_unsupported",
}

_REMEDIATION = {
    ModelBindingDiagnosticCode.CAPABILITY_MISSING: BindingRemediationCategory.CAPABILITY,
    ModelBindingDiagnosticCode.QUALIFIED_BINDING_UNAVAILABLE: BindingRemediationCategory.QUALIFICATION,
    ModelBindingDiagnosticCode.CONTEXT_INSUFFICIENT: BindingRemediationCategory.CAPABILITY,
    ModelBindingDiagnosticCode.BINDING_PROVENANCE_DRIFT: BindingRemediationCategory.QUALIFICATION,
    ModelBindingDiagnosticCode.CAPABILITY_PROTOCOL_UNSUPPORTED: BindingRemediationCategory.INTERFACE,
}


def _severity(value: ModelBindingDiagnosticSeverity) -> BindingDiagnosticSeverity:
    return BindingDiagnosticSeverity(value.value)


def _evidence_refs(values: tuple[str, ...]) -> tuple[BindingDiagnosticReference, ...]:
    return tuple(
        BindingDiagnosticReference(BindingDiagnosticReferenceKind.EVIDENCE, value)
        for value in values
    )


def project_model_diagnostic(
    diagnostic: ModelBindingDiagnostic,
    *,
    owner: CompositionSubject,
    subject: CompositionSubject,
    requirement_id: str,
    provider_profile_digest: str,
) -> BindingDiagnostic:
    if not isinstance(diagnostic, ModelBindingDiagnostic):
        raise TypeError("model diagnostic projection requires ModelBindingDiagnostic")
    requirement = RequirementAddress(subject, requirement_id)
    return BindingDiagnostic(
        code=BindingDiagnosticCode(_CODE[diagnostic.code]),
        severity=_severity(diagnostic.severity),
        blocking=diagnostic.severity is ModelBindingDiagnosticSeverity.ERROR,
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


class ModelBindingResolutionAdapter:
    """Project the Model-owned binding API into the neutral PSC-03 envelope."""

    def __init__(
        self,
        provider: ProjectModelProviderPort,
        *,
        owner: CompositionSubject,
        subject: CompositionSubject,
        requirement_id: str,
    ) -> None:
        if not isinstance(provider, ProjectModelProviderPort):
            raise TypeError("model binding resolution requires ProjectModelProviderPort")
        self._provider = provider
        self._owner = owner
        self._subject = subject
        self._requirement_id = RequirementAddress(subject, requirement_id).requirement_id
        if not isinstance(owner, CompositionSubject) or not isinstance(subject, CompositionSubject):
            raise TypeError("model binding resolution owner/subject must be CompositionSubject")

    def resolve(
        self, requirement: ModelCapabilityRequirement
    ) -> BindingResolution[ProjectModelBinding]:
        if not isinstance(requirement, ModelCapabilityRequirement):
            raise TypeError("model binding resolution requires ModelCapabilityRequirement")
        try:
            client = self._provider.bind(requirement)
        except ModelProjectBindingError as exc:
            profile_digest = self._provider.profile.digest()
            diagnostics = tuple(
                project_model_diagnostic(
                    item,
                    owner=self._owner,
                    subject=self._subject,
                    requirement_id=self._requirement_id,
                    provider_profile_digest=profile_digest,
                )
                for item in exc.diagnostics
            )
            return BindingResolution.diagnosed(diagnostics)
        binding = client.binding
        if binding.requirement_digest != requirement.digest():
            raise ValueError("model binding resolution requirement drift")
        proof = BindingProof(
            owner=self._owner,
            subject=self._subject,
            requirement_digest=Sha256Digest(binding.requirement_digest),
            provider_identity=binding.provider_id,
            provider_profile_digest=Sha256Digest(binding.provider_profile_digest),
            binding_generation=f"model-{binding.deployment_generation}",
            evidence_refs=_evidence_refs(
                tuple(f"sha256:{digest}" for digest in binding.runtime_canary_evidence_digests)
            ),
        )
        return BindingResolution.bound(binding, proof)


__all__ = ["ModelBindingResolutionAdapter", "project_model_diagnostic"]
