from __future__ import annotations

"""Canonical ResearchMethod -> participant binding composition."""

from noetrium_platform.capabilities.participant.api import (
    ParticipantImplementationIdentity,
    ParticipantProviderProfile,
    ParticipantRequirement,
    ParticipantRuntimeBinding,
    ParticipantSessionRuntimeIdentity,
    ProjectParticipantBinding,
)
from noetrium_platform.composition.method_runtime import standard_method_runtime_binder
from noetrium_platform.composition.research_os_lowering import (
    resolve_research_method_implementation,
)
from noetrium_platform.foundation.governance.architecture.api import (
    BindingDiagnostic,
    BindingDiagnosticCode,
    BindingDiagnosticSeverity,
    BindingProof,
    BindingRemediationCategory,
    BindingResolution,
    CompositionSubject,
)
from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.foundation.kernel.kernel import Sha256Digest, canonical_digest
from noetrium_platform.product.research_os import (
    ResearchDefinitionKind,
    ResearchMethodImplementation,
    ResearchProgram,
)
from noetrium_platform.research.execution.workflow.runtime import METHOD_MACHINE_IDENTITY
from noetrium_platform.research.experimentation.api import ResearchParticipantRequirement


_METHOD_PROVIDER_ID = "noetrium.method-runtime"


def exact_method_programs(program: ResearchProgram) -> dict[str, object]:
    """Resolve every canonical Method owned by one frozen ResearchProgram."""

    if type(program) is not ResearchProgram:
        raise TypeError("exact method participant binding requires ResearchProgram")
    rows: dict[str, object] = {}
    for definition in program.definitions:
        if definition.kind is not ResearchDefinitionKind.METHOD:
            continue
        if type(definition.implementation) is not ResearchMethodImplementation:
            continue
        resolved = resolve_research_method_implementation(definition)
        method_program = resolved.method.program
        method_id = method_program.program_identity.implementation.method_id
        previous = rows.get(method_id)
        if (
            previous is not None
            and getattr(previous, "program_digest", None)
            != method_program.program_digest
        ):
            raise ValueError(
                "ResearchProgram declares multiple exact MethodPrograms for "
                f"method_id={method_id!r}"
            )
        rows[method_id] = method_program
    return rows


def method_implementation_identity(
    method_program: object,
    participant_kind: str,
) -> ParticipantImplementationIdentity:
    if type(participant_kind) is not str or not participant_kind.strip():
        raise ValueError("method participant kind must be non-empty text")
    identity = getattr(method_program, "program_identity", None)
    method = getattr(identity, "implementation", None)
    if method is None:
        raise TypeError("method participant binding requires MethodProgram identity")
    return ParticipantImplementationIdentity(
        participant_kind,
        method.method_id,
        method.implementation_version,
        method.abi_version,
        method.schema_version,
        method.artifact_digest,
    )


def standard_method_session_runtime_identity() -> ParticipantSessionRuntimeIdentity:
    return ParticipantSessionRuntimeIdentity(
        "noetrium.universal-method-machine",
        METHOD_MACHINE_IDENTITY.implementation_version,
        "method-runtime.v1",
        canonical_digest(
            {
                "component": METHOD_MACHINE_IDENTITY,
                "runtime_binder": standard_method_runtime_binder().identity_digest,
            }
        ),
    )


def _missing_resolution(
    requirement: ResearchParticipantRequirement,
    subject: CompositionSubject,
) -> BindingResolution:
    return BindingResolution.diagnosed(
        (
            BindingDiagnostic(
                code=BindingDiagnosticCode("participant.runtime_unavailable"),
                severity=BindingDiagnosticSeverity.ERROR,
                blocking=True,
                owner=CompositionSubject.system_subject(SystemIdentity("participant")),
                subject=subject,
                requirement_digest=Sha256Digest(requirement.requirement_digest),
                summary=(
                    "no exact frozen MethodProgram is available for "
                    f"method_id={requirement.method_id!r}"
                ),
                provider_identity=None,
                remediation=BindingRemediationCategory.OWNER_ACTION,
            ),
        )
    )


def resolve_exact_method_participant(
    program: ResearchProgram,
    requirement: ResearchParticipantRequirement,
    subject: CompositionSubject,
) -> BindingResolution:
    """Resolve one Study participant from the exact frozen MethodProgram IR."""

    if type(requirement) is not ResearchParticipantRequirement:
        raise TypeError(
            "exact method participant binding requires ResearchParticipantRequirement"
        )
    if not isinstance(subject, CompositionSubject):
        raise TypeError("exact method participant binding requires CompositionSubject")

    method_program = exact_method_programs(program).get(requirement.method_id)
    if method_program is None:
        return _missing_resolution(requirement, subject)

    implementation = method_implementation_identity(
        method_program,
        requirement.participant_kind,
    )
    configuration_digest = method_program.program_identity.configuration_digest
    participant_requirement = ParticipantRequirement(
        requirement.role,
        implementation,
        configuration_digest,
        requirement.capability_requirement_ids,
    )
    profile = ParticipantProviderProfile(
        _METHOD_PROVIDER_ID,
        (requirement.participant_kind,),
        requirement.capability_requirement_ids,
    )
    runtime_binding = ParticipantRuntimeBinding(
        requirement.role,
        implementation,
        standard_method_session_runtime_identity(),
        configuration_digest,
    )
    project_binding = ProjectParticipantBinding.from_runtime(
        participant_requirement,
        profile,
        runtime_binding,
    )
    proof = BindingProof(
        owner=CompositionSubject.system_subject(SystemIdentity("participant")),
        subject=subject,
        requirement_digest=Sha256Digest(requirement.requirement_digest),
        provider_identity=profile.provider_id,
        provider_profile_digest=Sha256Digest(profile.digest()),
        binding_generation="method-" + method_program.program_digest[:16],
    )
    return BindingResolution.bound(project_binding, proof)


def exact_method_requirement_implementation_digest(
    program: ResearchProgram,
    requirement: ResearchParticipantRequirement,
) -> str:
    """Digest the exact scientific implementation, independent of treatment binding."""

    if type(requirement) is not ResearchParticipantRequirement:
        raise TypeError(
            "method implementation digest requires ResearchParticipantRequirement"
        )
    method_program = exact_method_programs(program).get(requirement.method_id)
    if method_program is None:
        return canonical_digest(
            {
                "schema": "noetrium.unresolved-method-requirement.v1",
                "program_digest": program.program_digest,
                "method_id": requirement.method_id,
                "treatment_id": requirement.treatment_id,
            }
        )
    return method_implementation_identity(
        method_program,
        requirement.participant_kind,
    ).digest()


__all__ = [
    "exact_method_programs",
    "exact_method_requirement_implementation_digest",
    "method_implementation_identity",
    "resolve_exact_method_participant",
    "standard_method_session_runtime_identity",
]
