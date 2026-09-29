from __future__ import annotations

from collections.abc import Callable
import re

from noetrium_platform.capabilities.model.api.project import (
    ModelBindingDiagnostic,
    ModelBindingDiagnosticCode,
    ModelBindingDiagnosticSeverity,
    ModelCapabilityRequirement,
    ModelProjectBindingError,
    ModelProviderProfile,
    ProjectModelBinding,
)
from noetrium_platform.capabilities.model.serving.api import (
    AdaptiveModelEndpointPoolPort,
    ModelEndpointReplicaSet,
    QualifiedModelEndpointBinding,
    QualifiedModelEndpointBindingPort,
)


ReplicaPoolFactory = Callable[[ModelEndpointReplicaSet], AdaptiveModelEndpointPoolPort]

_DIAGNOSTIC_URL = re.compile(r"(?i)\b(?:https?|wss?)://[^\s<>\"']+")
_DIAGNOSTIC_SECRET = re.compile(
    r"(?i)\b(?:token|api[_-]?key|password|passwd|secret|authorization)\s*=\s*[^\s,;]+"
)


def safe_diagnostic_detail(value: str) -> str:
    value = _DIAGNOSTIC_URL.sub("<redacted-url>", value)
    return _DIAGNOSTIC_SECRET.sub(
        lambda match: match.group(0).split("=", 1)[0] + "=<redacted>",
        value,
    )


def exception_detail(exc: Exception) -> str:
    detail = " ".join(str(exc).split())
    if not detail:
        return type(exc).__name__
    return f"{type(exc).__name__}: {safe_diagnostic_detail(detail[:512])}"


def binding_diagnostic(
    profile: ModelProviderProfile,
    requirement: ModelCapabilityRequirement,
    code: ModelBindingDiagnosticCode,
    message: str,
) -> ModelBindingDiagnostic:
    return ModelBindingDiagnostic(
        code=code,
        severity=ModelBindingDiagnosticSeverity.ERROR,
        message=message,
        requirement_digest=requirement.digest(),
        provider_id=profile.provider_id,
    )


def resolve_qualified_model_requirement(
    profile: ModelProviderProfile,
    bindings: QualifiedModelEndpointBindingPort,
    requirement: ModelCapabilityRequirement,
) -> tuple[
    QualifiedModelEndpointBinding | None,
    tuple[ModelBindingDiagnostic, ...],
]:
    """Resolve one typed capability against one exact runtime-qualified deployment."""

    if not isinstance(profile, ModelProviderProfile):
        raise TypeError("qualified requirement resolver profile must be typed")
    if not isinstance(requirement, ModelCapabilityRequirement):
        raise TypeError("qualified requirement resolver requirement must be typed")

    required_protocols = tuple(dict.fromkeys(
        (requirement.capability_id, *requirement.required_capabilities)
    ))
    missing = tuple(
        capability
        for capability in required_protocols
        if capability not in profile.capabilities
    )
    if missing:
        return None, (
            binding_diagnostic(
                profile,
                requirement,
                ModelBindingDiagnosticCode.CAPABILITY_MISSING,
                "qualified model provider lacks capabilities: "
                + ", ".join(missing),
            ),
        )

    try:
        binding = bindings.binding_for(
            role=requirement.role,
            capability_id=requirement.capability_id,
            input_schema_id=requirement.input_schema_id,
            output_schema_id=requirement.output_schema_id,
            prompt_generation=requirement.prompt_generation_id,
        )
    except Exception as exc:
        return None, (
            binding_diagnostic(
                profile,
                requirement,
                ModelBindingDiagnosticCode.QUALIFIED_BINDING_UNAVAILABLE,
                "qualified model binding unavailable: "
                + exception_detail(exc),
            ),
        )

    runtime_missing = tuple(
        capability
        for capability in required_protocols
        if capability not in binding.verified_capabilities
    )
    if runtime_missing:
        return None, (
            binding_diagnostic(
                profile,
                requirement,
                ModelBindingDiagnosticCode.CAPABILITY_MISSING,
                "qualified deployment has not runtime-verified capabilities: "
                + ", ".join(runtime_missing),
            ),
        )

    if (
        binding.role != requirement.role
        or binding.capability_id != requirement.capability_id
        or binding.input_schema_id != requirement.input_schema_id
        or binding.output_schema_id != requirement.output_schema_id
        or binding.prompt_generation != requirement.prompt_generation_id
    ):
        return None, (
            binding_diagnostic(
                profile,
                requirement,
                ModelBindingDiagnosticCode.BINDING_PROVENANCE_DRIFT,
                "qualified model binding changed requested role or prompt generation",
            ),
        )
    if binding.model.context_length < requirement.minimum_context_tokens:
        return None, (
            binding_diagnostic(
                profile,
                requirement,
                ModelBindingDiagnosticCode.CONTEXT_INSUFFICIENT,
                "qualified model context length is below the project requirement",
            ),
        )
    return binding, ()


def project_binding_from_qualified(
    *,
    profile: ModelProviderProfile,
    requirement: ModelCapabilityRequirement,
    binding: QualifiedModelEndpointBinding,
    request_tokenization_digest: str | None = None,
) -> ProjectModelBinding:
    if requirement.is_generation and request_tokenization_digest is None:
        raise ValueError(
            "generation project binding requires request tokenization provenance"
        )
    if not requirement.is_generation and request_tokenization_digest is not None:
        raise ValueError(
            "non-generation project binding cannot carry request tokenization"
        )
    return ProjectModelBinding(
        requirement_digest=requirement.digest(),
        provider_id=profile.provider_id,
        provider_profile_digest=profile.digest(),
        role=requirement.role,
        model=binding.model,
        deployment_id=binding.deployment_id,
        deployment_generation=binding.deployment_generation,
        model_stack_digest=binding.model_stack_digest,
        qualification_certificate_digest=binding.qualification_certificate_digest,
        runtime_qualification_digest=binding.runtime_qualification_digest,
        host_identity_digest=binding.host_identity_digest,
        prompt_generation_id=requirement.prompt_generation_id,
        prompt_id=requirement.prompt_id,
        prompt_digest=requirement.prompt_digest,
        capabilities=binding.verified_capabilities,
        runtime_canary_evidence_digests=binding.runtime_canary_evidence_digests,
        request_tokenization_digest=request_tokenization_digest,
        capability_id=requirement.capability_id,
        input_schema_id=requirement.input_schema_id,
        output_schema_id=requirement.output_schema_id,
    )


def materialize_qualified_replica_pool(
    *,
    profile: ModelProviderProfile,
    requirement: ModelCapabilityRequirement,
    bindings: QualifiedModelEndpointBindingPort,
    replica_pool_factory: ReplicaPoolFactory,
) -> AdaptiveModelEndpointPoolPort:
    try:
        replica_set = bindings.replica_set_for(
            role=requirement.role,
            capability_id=requirement.capability_id,
            input_schema_id=requirement.input_schema_id,
            output_schema_id=requirement.output_schema_id,
            prompt_generation=requirement.prompt_generation_id,
        )
        if (
            not isinstance(replica_set, ModelEndpointReplicaSet)
            or not replica_set.qualified
        ):
            raise TypeError(
                "qualified model authority returned an invalid replica set"
            )
        return replica_pool_factory(replica_set)
    except Exception as exc:
        raise ModelProjectBindingError(
            (
                binding_diagnostic(
                    profile,
                    requirement,
                    ModelBindingDiagnosticCode.QUALIFIED_BINDING_UNAVAILABLE,
                    "qualified model replica pool materialization failed: "
                    + exception_detail(exc),
                ),
            )
        ) from exc


__all__ = [
    "ReplicaPoolFactory",
    "binding_diagnostic",
    "exception_detail",
    "materialize_qualified_replica_pool",
    "project_binding_from_qualified",
    "resolve_qualified_model_requirement",
]
