from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from noetrium_platform.capabilities.model.api import (
    ModelCapabilityInput,
    ModelCapabilityInvocation,
    ModelCapabilityOutput,
    ModelCapabilityRequirement,
    ModelCapabilityResponse,
    ProjectModelBinding,
    ProjectModelClientPort,
    ProjectModelProviderPort,
    ProjectModelRequest,
    StructuredGenerationDecoderPort,
    StructuredGenerationInput,
    StructuredGenerationOutput,
)

InputT = TypeVar("InputT", bound=ModelCapabilityInput)
OutputT = TypeVar("OutputT", bound=ModelCapabilityOutput)


@dataclass(frozen=True, slots=True)
class FunctionalModelCapabilityClient(Generic[InputT, OutputT]):
    requirement: ModelCapabilityRequirement
    binding: ProjectModelBinding
    _handler: Callable[[InputT], OutputT]

    def __post_init__(self) -> None:
        if not isinstance(self.requirement, ModelCapabilityRequirement):
            raise TypeError("functional capability requirement must be typed")
        if not isinstance(self.binding, ProjectModelBinding):
            raise TypeError("functional capability binding must be typed")
        if self.binding.requirement_digest != self.requirement.digest():
            raise ValueError("functional capability binding requirement provenance drift")
        if self.binding.capability_id != self.requirement.capability_id:
            raise ValueError("functional capability binding capability provenance drift")
        if self.binding.input_schema_id != self.requirement.input_schema_id:
            raise ValueError("functional capability binding input schema drift")
        if self.binding.output_schema_id != self.requirement.output_schema_id:
            raise ValueError("functional capability binding output schema drift")
        if not callable(self._handler):
            raise TypeError("functional capability handler must be callable")

    def invoke(
        self, request: ModelCapabilityInvocation[InputT]
    ) -> ModelCapabilityResponse[OutputT]:
        if not isinstance(request, ModelCapabilityInvocation):
            raise TypeError("functional capability request must be typed")
        if request.requirement_digest != self.requirement.digest():
            raise ValueError("functional capability request requirement provenance drift")
        if request.capability_id != self.requirement.capability_id:
            raise ValueError("functional capability request capability drift")
        if request.input_schema_id != self.requirement.input_schema_id:
            raise ValueError("functional capability request input schema drift")
        output = self._handler(request.payload)
        if not isinstance(output, ModelCapabilityOutput):
            raise TypeError("functional capability handler returned an untyped output")
        if output.schema_id != self.requirement.output_schema_id:
            raise ValueError("functional capability handler output schema drift")
        return ModelCapabilityResponse(
            request_digest=request.request_digest,
            binding_digest=self.binding.digest(),
            output_schema_id=self.requirement.output_schema_id,
            output=output,
        )


@dataclass(frozen=True, slots=True)
class FunctionalModelCapabilityProvider(Generic[InputT, OutputT]):
    capability_id: str
    _binding_factory: Callable[[ModelCapabilityRequirement], ProjectModelBinding]
    _handler: Callable[[InputT], OutputT]

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not self.capability_id.strip():
            raise ValueError("functional capability_id must be non-empty")
        if not callable(self._binding_factory):
            raise TypeError("functional capability binding factory must be callable")
        if not callable(self._handler):
            raise TypeError("functional capability handler must be callable")

    def bind_capability(
        self, requirement: ModelCapabilityRequirement
    ) -> FunctionalModelCapabilityClient[InputT, OutputT]:
        if not isinstance(requirement, ModelCapabilityRequirement):
            raise TypeError("functional capability requirement must be typed")
        if requirement.capability_id != self.capability_id:
            raise ValueError("functional capability provider does not own requested capability")
        binding = self._binding_factory(requirement)
        if not isinstance(binding, ProjectModelBinding):
            raise TypeError("functional capability binding factory returned an untyped binding")
        return FunctionalModelCapabilityClient(
            requirement=requirement,
            binding=binding,
            _handler=self._handler,
        )


_INPUT_SCHEMA = "model.structured-generation.input.v1"
_OUTPUT_SCHEMA = "model.structured-generation.output.v1"


@dataclass(frozen=True, slots=True)
class QualifiedStructuredGenerationCapabilityClient:
    requirement: ModelCapabilityRequirement
    _client: ProjectModelClientPort
    _decoder: StructuredGenerationDecoderPort

    def __post_init__(self) -> None:
        if self.requirement.capability_id != "structured-generation":
            raise ValueError("structured generation client requires structured-generation capability")
        if self.requirement.input_schema_id != _INPUT_SCHEMA or self.requirement.output_schema_id != _OUTPUT_SCHEMA:
            raise ValueError("structured generation client requires canonical input/output schema ids")
        if not isinstance(self._client, ProjectModelClientPort):
            raise TypeError("structured generation client requires ProjectModelClientPort")
        if not isinstance(self._decoder, StructuredGenerationDecoderPort):
            raise TypeError("structured generation decoder must satisfy StructuredGenerationDecoderPort")
        binding = self._client.binding
        if binding.requirement_digest != self.requirement.digest():
            raise ValueError("structured generation binding requirement provenance drift")
        if binding.capability_id != self.requirement.capability_id:
            raise ValueError("structured generation binding capability provenance drift")
        if binding.input_schema_id != _INPUT_SCHEMA or binding.output_schema_id != _OUTPUT_SCHEMA:
            raise ValueError("structured generation binding schema provenance drift")

    @property
    def binding(self) -> ProjectModelBinding:
        return self._client.binding

    def invoke(self, request: ModelCapabilityInvocation[StructuredGenerationInput]) -> ModelCapabilityResponse[StructuredGenerationOutput]:
        if not isinstance(request, ModelCapabilityInvocation):
            raise TypeError("structured generation invocation must be typed")
        if request.requirement_digest != self.requirement.digest():
            raise ValueError("structured generation request requirement provenance drift")
        if request.capability_id != "structured-generation" or request.input_schema_id != _INPUT_SCHEMA:
            raise ValueError("structured generation request capability/schema drift")
        if not isinstance(request.payload, StructuredGenerationInput):
            raise TypeError("structured generation payload must be StructuredGenerationInput")
        project_request = ProjectModelRequest(
            requirement_digest=self.requirement.digest(),
            envelope=request.payload.envelope,
            body=request.payload.body,
        )
        raw = self._client.complete(project_request)
        if raw.request_digest != project_request.request_digest:
            raise ValueError("structured generation source response request provenance drift")
        if raw.binding_digest != self.binding.digest():
            raise ValueError("structured generation source response binding provenance drift")
        document = self._decoder.decode_and_validate(
            raw.text, schema_sha256=request.payload.output_schema_sha256
        )
        output = StructuredGenerationOutput(
            document=document,
            output_schema_sha256=request.payload.output_schema_sha256,
            model_revision=self.binding.model.revision,
            source_response_digest=raw.response_digest,
        )
        return ModelCapabilityResponse(
            request_digest=request.request_digest,
            binding_digest=self.binding.digest(),
            output_schema_id=_OUTPUT_SCHEMA,
            output=output,
        )


@dataclass(frozen=True, slots=True)
class QualifiedStructuredGenerationCapabilityProvider:
    _generation_provider: ProjectModelProviderPort
    _decoder: StructuredGenerationDecoderPort

    @property
    def capability_id(self) -> str:
        return "structured-generation"

    def bind_capability(self, requirement: ModelCapabilityRequirement) -> QualifiedStructuredGenerationCapabilityClient:
        if not isinstance(requirement, ModelCapabilityRequirement):
            raise TypeError("structured generation requirement must be typed")
        if requirement.capability_id != self.capability_id:
            raise ValueError("structured generation provider does not own requested capability")
        if requirement.input_schema_id != _INPUT_SCHEMA or requirement.output_schema_id != _OUTPUT_SCHEMA:
            raise ValueError("structured generation requirement must use canonical input/output schema ids")
        client = self._generation_provider.bind(requirement)
        return QualifiedStructuredGenerationCapabilityClient(requirement, client, self._decoder)


__all__ = [
    "FunctionalModelCapabilityClient",
    "FunctionalModelCapabilityProvider",
    "QualifiedStructuredGenerationCapabilityProvider",
    "QualifiedStructuredGenerationCapabilityClient",
]
