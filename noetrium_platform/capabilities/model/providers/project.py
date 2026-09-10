from __future__ import annotations

from collections.abc import Callable

from noetrium_platform.capabilities.model.api.project import (
    ModelBindingDiagnostic,
    ModelBindingDiagnosticCode,
    ModelBindingDiagnosticSeverity,
    ModelCapabilityRequirement,
    ModelProjectBindingError,
    ModelProviderProfile,
    ProjectModelBinding,
    ProjectModelClientPort,
    ProjectModelProviderPort,
    ProjectModelRequest,
    ProjectModelResponse,
)
from noetrium_platform.capabilities.model.request.api import ModelRequestRecorderPort
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointPort,
    ModelEndpointRequest,
    QualifiedModelEndpointBinding,
    QualifiedModelEndpointBindingPort,
)


EndpointFactory = Callable[[QualifiedModelEndpointBinding], ModelEndpointPort]


def _exception_detail(exc: Exception) -> str:
    """Return a compact, actionable detail without embedding a traceback."""
    detail = " ".join(str(exc).split())
    if not detail:
        return type(exc).__name__
    return f"{type(exc).__name__}: {detail[:512]}"


def _diagnostic(
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


class _QualifiedProjectModelClient:
    __slots__ = ("_binding", "_requirement", "_endpoint", "_model_requests")

    def __init__(
        self,
        binding: ProjectModelBinding,
        requirement: ModelCapabilityRequirement,
        endpoint: ModelEndpointPort,
        model_requests: ModelRequestRecorderPort,
    ) -> None:
        self._binding = binding
        self._requirement = requirement
        self._endpoint = endpoint
        self._model_requests = model_requests

    @property
    def binding(self) -> ProjectModelBinding:
        return self._binding

    def complete(self, request: ProjectModelRequest) -> ProjectModelResponse:
        if not isinstance(request, ProjectModelRequest):
            raise TypeError("project model request must be typed")
        if request.requirement_digest != self._binding.requirement_digest:
            raise ValueError("project model request requirement drift")
        envelope = request.envelope
        if envelope.role != self._binding.role or envelope.model != self._binding.model:
            raise ValueError("project model request model binding drift")
        if (
            envelope.prompt_generation_id != self._requirement.prompt_generation_id
            or envelope.prompt_id != self._requirement.prompt_id
            or envelope.prompt_digest != self._requirement.prompt_digest
        ):
            raise ValueError("project model request prompt provenance drift")
        if self._requirement.tool_schema_sha256 is not None:
            if (
                envelope.tool_schema_bundle is None
                or envelope.tool_schema_bundle.sha256 != self._requirement.tool_schema_sha256
            ):
                raise ValueError("project model request tool schema provenance drift")
        self._model_requests.verify_visible_request(envelope, request.body)
        route = self._endpoint.route
        if (
            route.deployment_id != self._binding.deployment_id
            or route.deployment_generation != self._binding.deployment_generation
        ):
            raise ValueError("project model endpoint route provenance drift")
        response = self._endpoint.complete(
            ModelEndpointRequest(
                request=envelope,
                deployment_id=self._binding.deployment_id,
                deployment_generation=self._binding.deployment_generation,
                body=request.body,
            )
        )
        if (
            response.request_id != envelope.request_id
            or response.deployment_id != self._binding.deployment_id
        ):
            raise ValueError("project model response provenance drift")
        return ProjectModelResponse(
            request_digest=request.request_digest,
            binding_digest=self._binding.digest(),
            response_digest=response.response_digest,
            text=response.text,
            finish_reason=response.finish_reason,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )


class QualifiedModelProjectProvider(ProjectModelProviderPort):
    """Reference adapter from qualified Model authorities to the project seam."""

    def __init__(
        self,
        profile: ModelProviderProfile,
        bindings: QualifiedModelEndpointBindingPort,
        endpoint_factory: EndpointFactory,
        model_requests: ModelRequestRecorderPort,
    ) -> None:
        if not isinstance(profile, ModelProviderProfile):
            raise TypeError("project model provider profile must be typed")
        self._profile = profile
        self._bindings = bindings
        self._endpoint_factory = endpoint_factory
        self._model_requests = model_requests
        # A provider lifetime is the run-scoped qualification boundary. Keep one
        # immutable project client per typed requirement so repeated downstream
        # binds do not reload receipts or rematerialize the endpoint.
        self._client_cache: dict[str, ProjectModelClientPort] = {}

    @property
    def profile(self) -> ModelProviderProfile:
        return self._profile

    def _resolve(
        self, requirement: ModelCapabilityRequirement
    ) -> tuple[QualifiedModelEndpointBinding | None, tuple[ModelBindingDiagnostic, ...]]:
        if not isinstance(requirement, ModelCapabilityRequirement):
            raise TypeError("project model requirement must be typed")
        if not requirement.is_generation:
            return None, (
                _diagnostic(
                    self._profile,
                    requirement,
                    ModelBindingDiagnosticCode.CAPABILITY_PROTOCOL_UNSUPPORTED,
                    "qualified text-generation provider cannot bind non-generation capability protocol",
                ),
            )
        missing = tuple(
            capability
            for capability in requirement.required_capabilities
            if capability not in self._profile.capabilities
        )
        if missing:
            return None, (
                _diagnostic(
                    self._profile,
                    requirement,
                    ModelBindingDiagnosticCode.CAPABILITY_MISSING,
                    "qualified model provider lacks capabilities: " + ", ".join(missing),
                ),
            )
        try:
            binding = self._bindings.binding_for(
                role=requirement.role,
                prompt_generation=requirement.prompt_generation_id,
            )
        except Exception as exc:
            return None, (
                _diagnostic(
                    self._profile,
                    requirement,
                    ModelBindingDiagnosticCode.QUALIFIED_BINDING_UNAVAILABLE,
                    f"qualified model binding unavailable: {_exception_detail(exc)}",
                ),
            )
        if (
            binding.role != requirement.role
            or binding.prompt_generation != requirement.prompt_generation_id
        ):
            return None, (
                _diagnostic(
                    self._profile,
                    requirement,
                    ModelBindingDiagnosticCode.BINDING_PROVENANCE_DRIFT,
                    "qualified model binding changed requested role or prompt generation",
                ),
            )
        if binding.model.context_length < requirement.minimum_context_tokens:
            return None, (
                _diagnostic(
                    self._profile,
                    requirement,
                    ModelBindingDiagnosticCode.CONTEXT_INSUFFICIENT,
                    "qualified model context length is below the project requirement",
                ),
            )
        return binding, ()

    def diagnose(
        self, requirement: ModelCapabilityRequirement
    ) -> tuple[ModelBindingDiagnostic, ...]:
        _, diagnostics = self._resolve(requirement)
        return diagnostics

    def bind(self, requirement: ModelCapabilityRequirement) -> ProjectModelClientPort:
        if not isinstance(requirement, ModelCapabilityRequirement):
            raise TypeError("project model requirement must be typed")
        cache_key = requirement.digest()
        cached = self._client_cache.get(cache_key)
        if cached is not None:
            return cached
        binding, diagnostics = self._resolve(requirement)
        if diagnostics or binding is None:
            raise ModelProjectBindingError(diagnostics)
        project_binding = ProjectModelBinding(
            requirement_digest=requirement.digest(),
            provider_id=self._profile.provider_id,
            provider_profile_digest=self._profile.digest(),
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
            capabilities=self._profile.capabilities,
            runtime_canary_evidence_digests=binding.runtime_canary_evidence_digests,
            capability_id=requirement.capability_id,
            input_schema_id=requirement.input_schema_id,
            output_schema_id=requirement.output_schema_id,
        )
        try:
            endpoint = self._endpoint_factory(binding)
        except Exception as exc:
            raise ModelProjectBindingError(
                (
                    _diagnostic(
                        self._profile,
                        requirement,
                        ModelBindingDiagnosticCode.QUALIFIED_BINDING_UNAVAILABLE,
                        f"qualified model endpoint materialization failed: {_exception_detail(exc)}",
                    ),
                )
            ) from exc
        if (
            endpoint.route.deployment_id != binding.deployment_id
            or endpoint.route.deployment_generation != binding.deployment_generation
        ):
            raise ModelProjectBindingError(
                (
                    _diagnostic(
                        self._profile,
                        requirement,
                        ModelBindingDiagnosticCode.BINDING_PROVENANCE_DRIFT,
                        "materialized model endpoint does not match qualified deployment generation",
                    ),
                )
            )
        client = _QualifiedProjectModelClient(
            project_binding, requirement, endpoint, self._model_requests
        )
        self._client_cache[cache_key] = client
        return client


__all__ = ["EndpointFactory", "QualifiedModelProjectProvider"]
