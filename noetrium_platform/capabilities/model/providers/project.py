from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from noetrium_platform.capabilities.model.api.capability import (
    ModelCapabilityInput,
    ModelCapabilityInvocation,
    ModelCapabilityOutput,
    ModelCapabilityResponse,
    ProjectModelCapabilityClientPort,
    StructuredGenerationDecoderPort,
    StructuredGenerationOutput,
)
from noetrium_platform.capabilities.model.api.project import (
    ModelBindingDiagnostic,
    ModelBindingDiagnosticCode,
    ModelCapabilityRequirement,
    ModelProjectBindingError,
    ModelProviderProfile,
    ProjectModelBinding,
    ProjectModelRequest,
    ProjectModelResponse,
    StructuredGenerationInput,
)
from noetrium_platform.capabilities.model.api.tokenization import (
    ModelRequestContextExceeded,
    ModelRequestTokenizationPort,
    ModelRequestTokenizationProviderPort,
)
from noetrium_platform.capabilities.model.request.api import ModelRequestRecorderPort
from noetrium_platform.capabilities.model.serving.api import (
    AdaptiveModelEndpointPoolPort,
    QualifiedModelEndpointBinding,
    QualifiedModelEndpointBindingPort,
)
from .binding import (
    ReplicaPoolFactory,
    binding_diagnostic,
    exception_detail,
    materialize_qualified_replica_pool,
    project_binding_from_qualified,
    resolve_qualified_model_requirement,
)
from .qualified_capability import (
    QualifiedCapabilityCodec,
    _QualifiedOperationCapabilityProvider,
)
from noetrium_platform.foundation.kernel.concurrency.api import SingleFlightCache


class _GenerationTransportClient:
    __slots__=("_binding","_requirement","_pool","_model_requests","_tokenization")

    def __init__(
        self,
        binding: ProjectModelBinding,
        requirement: ModelCapabilityRequirement,
        pool: AdaptiveModelEndpointPoolPort,
        model_requests: ModelRequestRecorderPort,
        tokenization: ModelRequestTokenizationPort,
    ) -> None:
        self._binding=binding
        self._requirement=requirement
        self._pool=pool
        self._model_requests=model_requests
        self._tokenization=tokenization

    @property
    def binding(self) -> ProjectModelBinding:
        return self._binding

    def complete(self, request: ProjectModelRequest) -> ProjectModelResponse:
        if not isinstance(request,ProjectModelRequest):
            raise TypeError("generation transport request must be ProjectModelRequest")
        if request.requirement_digest != self._binding.requirement_digest:
            raise ValueError("generation request requirement drift")
        envelope=request.envelope
        if envelope.role != self._binding.role or envelope.model != self._binding.model:
            raise ValueError("generation request model binding drift")
        if (
            envelope.prompt_generation_id != self._requirement.prompt_generation_id
            or envelope.prompt_id != self._requirement.prompt_id
            or envelope.prompt_digest != self._requirement.prompt_digest
        ):
            raise ValueError("generation request prompt provenance drift")
        if self._requirement.tool_schema_sha256 is not None:
            if (
                envelope.tool_schema_bundle is None
                or envelope.tool_schema_bundle.content_sha256
                != self._requirement.tool_schema_sha256
            ):
                raise ValueError("generation request tool schema provenance drift")
        self._model_requests.verify_visible_request(envelope,request.body)
        budget=self._tokenization.inspect(
            request.body,context_length=self._binding.model.context_length
        )
        if budget.tokenization_digest != self._binding.request_tokenization_digest:
            raise ValueError("generation request tokenization provenance drift")
        if not budget.fits:
            raise ModelRequestContextExceeded(budget)
        dispatch=self._pool.complete(envelope,request.body)
        response=dispatch.response
        if response.request_id != envelope.request_id:
            raise ValueError("generation response request provenance drift")
        return ProjectModelResponse(
            request_digest=request.request_digest,
            binding_digest=self._binding.digest(),
            response_digest=response.response_digest,
            text=response.text,
            tool_calls=response.tool_calls,
            finish_reason=response.finish_reason,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            operational_deployment_id=dispatch.request.deployment_id,
            operational_deployment_generation=dispatch.request.deployment_generation,
            operational_dispatch_digest=dispatch.dispatch_digest,
        )


@dataclass(slots=True)
class _GenerationCapabilityClient:
    requirement: ModelCapabilityRequirement
    _transport: _GenerationTransportClient

    @property
    def binding(self) -> ProjectModelBinding:
        return self._transport.binding

    def invoke(
        self,
        request: ModelCapabilityInvocation[ProjectModelRequest],
    ) -> ModelCapabilityResponse[ProjectModelResponse]:
        if not isinstance(request,ModelCapabilityInvocation):
            raise TypeError("generation invocation must be typed")
        if request.requirement_digest != self.requirement.digest():
            raise ValueError("generation invocation requirement provenance drift")
        if request.capability_id != "generation":
            raise ValueError("generation invocation capability drift")
        if not isinstance(request.payload,ProjectModelRequest):
            raise TypeError("generation invocation requires ProjectModelRequest")
        raw=self._transport.complete(request.payload)
        return ModelCapabilityResponse(
            request_digest=request.request_digest,
            binding_digest=self.binding.digest(),
            output_schema_id=self.requirement.output_schema_id,
            output=raw,
            operational_deployment_id=raw.operational_deployment_id,
            operational_deployment_generation=raw.operational_deployment_generation,
            operational_dispatch_digest=raw.operational_dispatch_digest,
        )


@dataclass(slots=True)
class _StructuredGenerationCapabilityClient:
    requirement: ModelCapabilityRequirement
    _transport: _GenerationTransportClient
    _decoder: StructuredGenerationDecoderPort

    @property
    def binding(self) -> ProjectModelBinding:
        return self._transport.binding

    def invoke(
        self,
        request: ModelCapabilityInvocation[StructuredGenerationInput],
    ) -> ModelCapabilityResponse[StructuredGenerationOutput]:
        if not isinstance(request,ModelCapabilityInvocation):
            raise TypeError("structured generation invocation must be typed")
        if request.requirement_digest != self.requirement.digest():
            raise ValueError("structured generation requirement provenance drift")
        if request.capability_id != "structured-generation":
            raise ValueError("structured generation capability drift")
        if not isinstance(request.payload,StructuredGenerationInput):
            raise TypeError("structured generation requires StructuredGenerationInput")
        raw_request=ProjectModelRequest(
            requirement_digest=self.requirement.digest(),
            envelope=request.payload.envelope,
            body=request.payload.body,
        )
        raw=self._transport.complete(raw_request)
        document=self._decoder.decode_and_validate(
            raw.text,schema_sha256=request.payload.output_schema_sha256
        )
        output=StructuredGenerationOutput(
            document=document,
            output_schema_sha256=request.payload.output_schema_sha256,
            model_revision=self.binding.model.revision,
            source_response_digest=raw.response_digest,
        )
        return ModelCapabilityResponse(
            request_digest=request.request_digest,
            binding_digest=self.binding.digest(),
            output_schema_id=self.requirement.output_schema_id,
            output=output,
            operational_deployment_id=raw.operational_deployment_id,
            operational_deployment_generation=raw.operational_deployment_generation,
            operational_dispatch_digest=raw.operational_dispatch_digest,
        )


class QualifiedModelProjectProvider:
    """Single qualified provider for all typed model capabilities."""

    capability_id="*"

    def __init__(
        self,
        profile: ModelProviderProfile,
        bindings: QualifiedModelEndpointBindingPort,
        replica_pool_factory: ReplicaPoolFactory,
        model_requests: ModelRequestRecorderPort,
        tokenization_provider: ModelRequestTokenizationProviderPort,
        *,
        structured_generation_decoder: StructuredGenerationDecoderPort | None=None,
        capability_codecs: tuple[QualifiedCapabilityCodec,...]=(),
    ) -> None:
        if not isinstance(profile,ModelProviderProfile):
            raise TypeError("project model provider profile must be typed")
        if not callable(replica_pool_factory):
            raise TypeError("project model provider requires replica_pool_factory")
        if not isinstance(tokenization_provider,ModelRequestTokenizationProviderPort):
            raise TypeError("project model provider requires ModelRequestTokenizationProviderPort")
        if (
            structured_generation_decoder is not None
            and not isinstance(structured_generation_decoder,StructuredGenerationDecoderPort)
        ):
            raise TypeError("structured generation decoder must satisfy its port")
        self._profile=profile
        self._bindings=bindings
        self._replica_pool_factory=replica_pool_factory
        self._model_requests=model_requests
        self._tokenization_provider=tokenization_provider
        self._structured_decoder=structured_generation_decoder
        self._generation_transport_cache: SingleFlightCache[_GenerationTransportClient] = SingleFlightCache()
        self._capability_cache: SingleFlightCache[ProjectModelCapabilityClientPort] = SingleFlightCache()
        self._operations=_QualifiedOperationCapabilityProvider(
            profile=profile,
            bindings=bindings,
            replica_pool_factory=replica_pool_factory,
            model_requests=model_requests,
            codecs=capability_codecs,
        )

    @property
    def profile(self) -> ModelProviderProfile:
        return self._profile

    def _resolve(
        self,requirement: ModelCapabilityRequirement
    ) -> tuple[QualifiedModelEndpointBinding | None,tuple[ModelBindingDiagnostic,...]]:
        return resolve_qualified_model_requirement(
            self._profile,self._bindings,requirement
        )

    def diagnose(
        self,requirement: ModelCapabilityRequirement
    ) -> tuple[ModelBindingDiagnostic,...]:
        if not isinstance(requirement,ModelCapabilityRequirement):
            raise TypeError("project model requirement must be typed")
        if (
            requirement.capability_id=="structured-generation"
            and self._structured_decoder is None
        ):
            return (
                binding_diagnostic(
                    self._profile,
                    requirement,
                    ModelBindingDiagnosticCode.CAPABILITY_PROTOCOL_UNSUPPORTED,
                    "structured generation requires one qualified output decoder",
                ),
            )
        if not requirement.is_generation:
            return self._operations.diagnose(requirement)
        _binding,diagnostics=self._resolve(requirement)
        return diagnostics

    def _generation_transport(
        self,requirement: ModelCapabilityRequirement
    ) -> _GenerationTransportClient:
        digest=requirement.digest()

        def build() -> _GenerationTransportClient:
            binding,diagnostics=self._resolve(requirement)
            if diagnostics or binding is None:
                raise ModelProjectBindingError(diagnostics)
            try:
                tokenization=self._tokenization_provider.bind(
                    model=binding.model,
                    model_stack_digest=binding.model_stack_digest,
                    tokenizer_sha256=binding.tokenizer_sha256,
                    chat_template_sha256=binding.chat_template_sha256,
                )
            except Exception as exc:
                raise ModelProjectBindingError((
                    binding_diagnostic(
                        self._profile,
                        requirement,
                        ModelBindingDiagnosticCode.QUALIFIED_BINDING_UNAVAILABLE,
                        f"model request tokenization unavailable: {exception_detail(exc)}",
                    ),
                )) from exc
            if not isinstance(tokenization,ModelRequestTokenizationPort):
                raise TypeError("model tokenization provider returned an invalid port")
            identity=tokenization.identity
            if (
                identity.model != binding.model
                or identity.model_stack_digest != binding.model_stack_digest
                or identity.tokenizer_sha256 != binding.tokenizer_sha256
                or identity.chat_template_sha256 != binding.chat_template_sha256
            ):
                raise ModelProjectBindingError((
                    binding_diagnostic(
                        self._profile,
                        requirement,
                        ModelBindingDiagnosticCode.BINDING_PROVENANCE_DRIFT,
                        "model request tokenization identity does not match qualified model stack",
                    ),
                ))
            project_binding=project_binding_from_qualified(
                profile=self._profile,
                requirement=requirement,
                binding=binding,
                request_tokenization_digest=identity.digest(),
            )
            pool=materialize_qualified_replica_pool(
                profile=self._profile,
                requirement=requirement,
                bindings=self._bindings,
                replica_pool_factory=self._replica_pool_factory,
            )
            return _GenerationTransportClient(
                project_binding,requirement,pool,self._model_requests,tokenization
            )

        return self._generation_transport_cache.get_or_create(digest, build)

    def bind_capability(
        self,requirement: ModelCapabilityRequirement
    ) -> ProjectModelCapabilityClientPort:
        if not isinstance(requirement,ModelCapabilityRequirement):
            raise TypeError("project model requirement must be typed")
        digest=requirement.digest()

        def build() -> ProjectModelCapabilityClientPort:
            if requirement.capability_id=="generation":
                client=_GenerationCapabilityClient(
                    requirement,self._generation_transport(requirement)
                )
            elif requirement.capability_id=="structured-generation":
                if self._structured_decoder is None:
                    raise ModelProjectBindingError(self.diagnose(requirement))
                client=_StructuredGenerationCapabilityClient(
                    requirement,
                    self._generation_transport(requirement),
                    self._structured_decoder,
                )
            else:
                client=self._operations.bind_capability(requirement)
            return cast(ProjectModelCapabilityClientPort,client)

        return self._capability_cache.get_or_create(digest, build)



__all__=["QualifiedModelProjectProvider","ReplicaPoolFactory","QualifiedCapabilityCodec"]
