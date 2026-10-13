from __future__ import annotations

"""Canonical ResearchMethod -> participant binding composition."""

from collections.abc import Mapping
from functools import lru_cache

from noetrium_platform.capabilities.participant.api import (
    ParticipantProviderProfile,
    ParticipantRuntimeBinding,
    ParticipantSessionRuntimeIdentity,
    ProjectParticipantBinding,
)
from noetrium_platform.capabilities.participant.core.api import (
    participant_implementation_digest,
    participant_implementation_id,
    participant_implementation_kind,
)
from noetrium_platform.composition.method_runtime import METHOD_RUNTIME_BINDER_DIGEST
from noetrium_platform.composition.research_lowering import (
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
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.structure import is_implementation
from noetrium_platform.product.research_implementation import (
    METHOD_IMPLEMENTATION_TYPE,
)
from noetrium_platform.product.research_traits import TRAIT_METHOD
from noetrium_platform.research.execution.workflow.runtime import METHOD_EXECUTION_IDENTITY
from noetrium_platform.research.execution.workflow.api import (
    method_program_digest,
    method_program_identity,
    method_program_configuration_digest,
)
from noetrium_platform.research.experimentation.binding import (
    participant_requirement_capabilities,
    participant_requirement_kind,
    participant_requirement_method_id,
    participant_requirement_role,
    participant_requirement_treatment_id,
    require_participant_requirement,
)


_METHOD_PROVIDER_ID = "noetrium.method-runtime"
_PARTICIPANT_BINDING_OWNER = CompositionSubject.system_subject(SystemIdentity("participant"))


def exact_method_programs(program: NoetriumUnit) -> dict[str, object]:
    """Resolve every canonical Method owned by one frozen NoetriumUnit."""

    if type(program) is not NoetriumUnit:
        raise TypeError("exact method participant binding requires NoetriumUnit")
    rows: dict[str, object] = {}
    for definition in program.symbols:
        if not definition.has_trait(TRAIT_METHOD):
            continue
        if not is_implementation(
            definition.implementation,
            METHOD_IMPLEMENTATION_TYPE,
        ):
            continue
        resolved = resolve_research_method_implementation(definition)
        method_program = resolved.method
        identity = method_program_identity(method_program)
        method_id = participant_implementation_id(identity)
        previous = rows.get(method_id)
        if (
            previous is not None
            and method_program_digest(previous) != method_program_digest(method_program)
        ):
            raise ValueError(
                "NoetriumUnit declares multiple exact MethodPrograms for "
                f"method_id={method_id!r}"
            )
        rows[method_id] = method_program
    return rows


def method_implementation_identity(
    method_program: object,
    participant_kind: str,
) -> NoetriumUnit:
    if type(participant_kind) is not str or not participant_kind.strip():
        raise ValueError("method participant kind must be non-empty text")
    if type(method_program) is not NoetriumUnit:
        raise TypeError("method participant binding requires NoetriumUnit")
    method = method_program_identity(method_program)
    if participant_implementation_kind(method) != participant_kind:
        raise ValueError(
            "method participant kind drifted from Method implementation Unit"
        )
    return method


@lru_cache(maxsize=1)
def standard_method_session_runtime_identity() -> ParticipantSessionRuntimeIdentity:
    """Intern the process-wide immutable Method session runtime identity."""

    return ParticipantSessionRuntimeIdentity(
        "noetrium.universal-method-machine",
        METHOD_EXECUTION_IDENTITY.implementation_version,
        "method-runtime.v1",
        canonical_digest(
            {
                "component": METHOD_EXECUTION_IDENTITY,
                "runtime_binder": METHOD_RUNTIME_BINDER_DIGEST,
            }
        ),
    )


@lru_cache(maxsize=1)
def _standard_method_session_runtime_digest() -> str:
    return standard_method_session_runtime_identity().digest()


@lru_cache(maxsize=8192)
def _method_runtime_binding(
    role: str,
    implementation: NoetriumUnit,
    configuration_digest: str | None,
) -> ParticipantRuntimeBinding:
    """Intern exact runtime bindings; scientific requirement truth stays external."""

    return ParticipantRuntimeBinding(
        role,
        implementation,
        standard_method_session_runtime_identity(),
        configuration_digest,
    )


@lru_cache(maxsize=256)
def _method_provider_profile(
    participant_kind: str,
    capabilities: tuple[str, ...],
) -> tuple[ParticipantProviderProfile, str]:
    """Intern immutable provider capability profiles by exact semantics."""

    profile = ParticipantProviderProfile(
        _METHOD_PROVIDER_ID,
        (participant_kind,),
        capabilities,
    )
    return profile, profile.digest()


def _missing_resolution(
    requirement: NoetriumUnit,
    subject: CompositionSubject,
) -> BindingResolution:
    return BindingResolution.diagnosed(
        (
            BindingDiagnostic(
                code=BindingDiagnosticCode("participant.runtime_unavailable"),
                severity=BindingDiagnosticSeverity.ERROR,
                blocking=True,
                owner=_PARTICIPANT_BINDING_OWNER,
                subject=subject,
                requirement_digest=Sha256Digest(requirement.unit_digest),
                summary=(
                    "no exact frozen NoetriumUnit is available for "
                    f"method_id={participant_requirement_method_id(requirement)!r}"
                ),
                provider_identity=None,
                remediation=BindingRemediationCategory.OWNER_ACTION,
            ),
        )
    )


def resolve_exact_method_participant(
    program: NoetriumUnit,
    requirement: NoetriumUnit,
    subject: CompositionSubject,
    *,
    method_programs: Mapping[str, object] | None = None,
) -> BindingResolution:
    """Resolve one Study participant from the exact frozen NoetriumUnit IR."""

    require_participant_requirement(requirement)
    if not isinstance(subject, CompositionSubject):
        raise TypeError("exact method participant binding requires CompositionSubject")

    if type(program) is not NoetriumUnit:
        raise TypeError("exact method participant binding requires NoetriumUnit")
    programs = exact_method_programs(program) if method_programs is None else method_programs
    if not isinstance(programs, Mapping):
        raise TypeError("pre-resolved method programs must be a mapping")

    # The requirement Unit is immutable and has just been validated. Read its
    # frozen parameter cut once instead of re-validating it through each public
    # accessor. This preserves fail-close semantics while making the hot binding
    # path proportional only to the information actually consumed.
    requirement_params = requirement.parameters
    method_id = str(requirement_params["method_id"])
    participant_kind = str(requirement_params["participant_kind"])
    role = str(requirement_params["role"])
    capabilities = tuple(requirement_params["capability_requirement_ids"])
    method_program = programs.get(method_id)
    if method_program is None:
        return _missing_resolution(requirement, subject)

    # method_program_identity() performs the complete cached Method validator.
    # After that proof, configuration and implementation projections may be read
    # directly from the same immutable Unit without repeating validation.
    implementation = method_program_identity(method_program)
    if participant_implementation_kind(implementation) != participant_kind:
        raise ValueError(
            "method participant kind drifted from Method implementation Unit"
        )
    configuration = method_program.parameters.get("configuration", {})
    configuration_digest = canonical_digest(configuration)
    profile, profile_digest = _method_provider_profile(
        participant_kind, capabilities
    )
    runtime_binding = _method_runtime_binding(
        role, implementation, configuration_digest
    )
    project_binding = ProjectParticipantBinding(
        requirement.unit_digest,
        profile.provider_id,
        profile_digest,
        runtime_binding,
    )
    proof = BindingProof(
        owner=_PARTICIPANT_BINDING_OWNER,
        subject=subject,
        requirement_digest=Sha256Digest(project_binding.requirement_digest),
        provider_identity=profile.provider_id,
        provider_profile_digest=Sha256Digest(profile_digest),
        binding_generation=(
            "participant-" + _standard_method_session_runtime_digest()
        ),
    )
    return BindingResolution.bound(project_binding, proof)


def exact_method_requirement_implementation_digest(
    program: NoetriumUnit,
    requirement: NoetriumUnit,
    *,
    method_programs: Mapping[str, object] | None = None,
) -> str:
    """Digest the exact scientific implementation, independent of treatment binding."""

    require_participant_requirement(requirement)
    if type(program) is not NoetriumUnit:
        raise TypeError("exact method requirement requires NoetriumUnit")
    programs = exact_method_programs(program) if method_programs is None else method_programs
    if not isinstance(programs, Mapping):
        raise TypeError("pre-resolved method programs must be a mapping")
    method_program = programs.get(participant_requirement_method_id(requirement))
    if method_program is None:
        return canonical_digest(
            {
                "schema": "noetrium.unresolved-method-requirement.v1",
                "graph_digest": program.unit_digest,
                "method_id": participant_requirement_method_id(requirement),
                "treatment_id": participant_requirement_treatment_id(requirement),
            }
        )
    return participant_implementation_digest(
        method_implementation_identity(
            method_program,
            participant_requirement_kind(requirement),
        )
    )


__all__ = [
    "exact_method_programs",
    "exact_method_requirement_implementation_digest",
    "method_implementation_identity",
    "resolve_exact_method_participant",
    "standard_method_session_runtime_identity",
]
