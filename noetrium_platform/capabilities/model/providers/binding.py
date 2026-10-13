from __future__ import annotations

from noetrium_platform.capabilities.model.api.unit_semantics import (
    MODEL_CAPABILITY_REQUIREMENT_TRAIT,
    model_capability_requirement_capabilities,
    model_capability_requirement_capability,
    model_capability_requirement_digest,
    model_capability_requirement_input_schema,
    model_capability_requirement_is_generation,
    model_capability_requirement_minimum_context,
    model_capability_requirement_output_schema,
    model_capability_requirement_prompt_digest,
    model_capability_requirement_prompt_generation,
    model_capability_requirement_prompt_id,
    model_capability_requirement_role,
    model_capability_requirement_tool_schema,
    require_model_capability_requirement,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit

from collections.abc import Callable
import re

from noetrium_platform.capabilities.model.api.project import (
    ModelBindingDiagnostic,
    ModelBindingDiagnosticCode,
    ModelBindingDiagnosticSeverity,
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
    requirement: NoetriumUnit,
    code: ModelBindingDiagnosticCode,
    message: str,
) -> ModelBindingDiagnostic:
    return ModelBindingDiagnostic(
        code=code,
        severity=ModelBindingDiagnosticSeverity.ERROR,
        message=message,
        requirement_digest=model_capability_requirement_digest(requirement),
        provider_id=profile.provider_id,
    )


def resolve_qualified_model_requirement(
    profile: ModelProviderProfile,
    bindings: QualifiedModelEndpointBindingPort,
    requirement: NoetriumUnit,
) -> tuple[
    QualifiedModelEndpointBinding | None,
    tuple[ModelBindingDiagnostic, ...],
]:
    """Resolve one typed capability against one exact runtime-qualified deployment."""

    if not isinstance(profile, ModelProviderProfile):
        raise TypeError("qualified requirement resolver profile must be typed")
    if not (type(requirement) is NoetriumUnit and requirement.has_trait(MODEL_CAPABILITY_REQUIREMENT_TRAIT)):
        raise TypeError("qualified requirement resolver requirement must be typed")

    required_protocols = tuple(dict.fromkeys(
        (model_capability_requirement_capability(requirement), *model_capability_requirement_capabilities(requirement))
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
            role=model_capability_requirement_role(requirement),
            capability_id=model_capability_requirement_capability(requirement),
            input_schema_id=model_capability_requirement_input_schema(requirement),
            output_schema_id=model_capability_requirement_output_schema(requirement),
            prompt_generation=model_capability_requirement_prompt_generation(requirement),
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
        binding.role != model_capability_requirement_role(requirement)
        or binding.capability_id != model_capability_requirement_capability(requirement)
        or binding.input_schema_id != model_capability_requirement_input_schema(requirement)
        or binding.output_schema_id != model_capability_requirement_output_schema(requirement)
        or binding.prompt_generation != model_capability_requirement_prompt_generation(requirement)
    ):
        return None, (
            binding_diagnostic(
                profile,
                requirement,
                ModelBindingDiagnosticCode.BINDING_PROVENANCE_DRIFT,
                "qualified model binding changed requested role or prompt generation",
            ),
        )
    if binding.model.context_length < model_capability_requirement_minimum_context(requirement):
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
    requirement: NoetriumUnit,
    binding: QualifiedModelEndpointBinding,
    request_tokenization_digest: str | None = None,
) -> ProjectModelBinding:
    if model_capability_requirement_is_generation(requirement) and request_tokenization_digest is None:
        raise ValueError(
            "generation project binding requires request tokenization provenance"
        )
    if not model_capability_requirement_is_generation(requirement) and request_tokenization_digest is not None:
        raise ValueError(
            "non-generation project binding cannot carry request tokenization"
        )
    return ProjectModelBinding(
        requirement_digest=model_capability_requirement_digest(requirement),
        provider_id=profile.provider_id,
        provider_profile_digest=profile.digest(),
        role=model_capability_requirement_role(requirement),
        model=binding.model,
        deployment_id=binding.deployment_id,
        deployment_generation=binding.deployment_generation,
        model_stack_digest=binding.model_stack_digest,
        qualification_certificate_digest=binding.qualification_certificate_digest,
        runtime_qualification_digest=binding.runtime_qualification_digest,
        host_identity_digest=binding.host_identity_digest,
        prompt_generation_id=model_capability_requirement_prompt_generation(requirement),
        prompt_id=model_capability_requirement_prompt_id(requirement),
        prompt_digest=model_capability_requirement_prompt_digest(requirement),
        capabilities=binding.verified_capabilities,
        runtime_canary_evidence_digests=binding.runtime_canary_evidence_digests,
        request_tokenization_digest=request_tokenization_digest,
        capability_id=model_capability_requirement_capability(requirement),
        input_schema_id=model_capability_requirement_input_schema(requirement),
        output_schema_id=model_capability_requirement_output_schema(requirement),
    )


def materialize_qualified_replica_pool(
    *,
    profile: ModelProviderProfile,
    requirement: NoetriumUnit,
    bindings: QualifiedModelEndpointBindingPort,
    replica_pool_factory: ReplicaPoolFactory,
) -> AdaptiveModelEndpointPoolPort:
    try:
        replica_set = bindings.replica_set_for(
            role=model_capability_requirement_role(requirement),
            capability_id=model_capability_requirement_capability(requirement),
            input_schema_id=model_capability_requirement_input_schema(requirement),
            output_schema_id=model_capability_requirement_output_schema(requirement),
            prompt_generation=model_capability_requirement_prompt_generation(requirement),
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
