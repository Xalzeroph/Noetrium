from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.model.request.api import ContentRef, ModelRequestEnvelope
from noetrium_platform.capabilities.model.request.prompt.api import PromptSelectionPort
from noetrium_platform.foundation.kernel.kernel import (
    ImmutableModelIdentity,
    JsonInput,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value


def _sha256(value: object, field_name: str) -> str:
    digest = _text(value, field_name)
    return require_sha256(digest, field_name)


def _tokens(values: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(sorted(_text(value, field_name) for value in values))
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class ModelCapabilityRequirement:
    """Project-owned requirement for one semantic model capability.

    Generation keeps exact prompt/tool provenance. Non-generation capabilities
    bind their semantic input/output schemas instead of fabricating prompt ids.
    """

    role: str
    prompt_generation_id: str | None = None
    prompt_id: str | None = None
    prompt_digest: str | None = None
    required_capabilities: tuple[str, ...] = ()
    minimum_context_tokens: int = 1
    tool_schema_sha256: str | None = None
    capability_id: str = "generation"
    input_schema_id: str = "model.generation.request.v1"
    output_schema_id: str = "model.generation.response.v1"

    def __post_init__(self) -> None:
        _text(self.role, "model requirement role")
        _text(self.capability_id, "model requirement capability_id")
        _text(self.input_schema_id, "model requirement input_schema_id")
        _text(self.output_schema_id, "model requirement output_schema_id")
        generation = self.capability_id in {"generation", "structured-generation"}
        prompt_fields = (self.prompt_generation_id, self.prompt_id, self.prompt_digest)
        if generation:
            _text(self.prompt_generation_id, "model requirement prompt_generation_id")
            _text(self.prompt_id, "model requirement prompt_id")
            _sha256(self.prompt_digest, "model requirement prompt_digest")
        elif any(value is not None for value in prompt_fields):
            raise ValueError("non-generation model requirements must not fabricate prompt identity")
        object.__setattr__(
            self,
            "required_capabilities",
            _tokens(self.required_capabilities, "model requirement capabilities"),
        )
        if type(self.minimum_context_tokens) is not int or self.minimum_context_tokens <= 0:
            raise ValueError("model requirement minimum_context_tokens must be positive")
        if self.tool_schema_sha256 is not None:
            if not generation:
                raise ValueError("tool schema identity is only valid for generation capabilities")
            _sha256(self.tool_schema_sha256, "model requirement tool_schema_sha256")

    @property
    def is_generation(self) -> bool:
        return self.capability_id in {"generation", "structured-generation"}

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class MultimodalContent:
    role: str
    content: ContentRef

    def __post_init__(self) -> None:
        _text(self.role, "multimodal content role")
        if not isinstance(self.content, ContentRef):
            raise TypeError("multimodal content must carry ContentRef")


@dataclass(frozen=True, slots=True)
class MultimodalInferenceInput:
    content: tuple[MultimodalContent, ...]
    instruction: str | None = None
    schema_id: str = field(init=False, default="model.multimodal.input.v1")

    def __post_init__(self) -> None:
        if not isinstance(self.content, tuple) or not self.content:
            raise TypeError("multimodal input content must be a non-empty tuple")
        if any(not isinstance(item, MultimodalContent) for item in self.content):
            raise TypeError("multimodal input must contain typed MultimodalContent values")
        if self.instruction is not None:
            _text(self.instruction, "multimodal instruction")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class MultimodalInferenceOutput:
    model_revision: str
    text: str | None = None
    content: tuple[MultimodalContent, ...] = ()
    schema_id: str = field(init=False, default="model.multimodal.output.v1")

    def __post_init__(self) -> None:
        _text(self.model_revision, "multimodal output model_revision")
        if self.text is not None:
            _text(self.text, "multimodal output text")
        if not isinstance(self.content, tuple) or any(
            not isinstance(item, MultimodalContent) for item in self.content
        ):
            raise TypeError("multimodal output content must be typed MultimodalContent values")
        if self.text is None and not self.content:
            raise ValueError("multimodal output must contain text or content references")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class StructuredGenerationInput:
    envelope: ModelRequestEnvelope
    body: Mapping[str, JsonInput]
    output_schema_sha256: str
    schema_id: str = field(init=False, default="model.structured-generation.input.v1")

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, ModelRequestEnvelope):
            raise TypeError("structured generation envelope must be ModelRequestEnvelope")
        if not isinstance(self.body, Mapping):
            raise TypeError("structured generation body must be a mapping")
        object.__setattr__(self, "body", freeze_json(self.body))
        require_sha256(self.output_schema_sha256, "structured generation output_schema_sha256")

    def digest(self) -> str:
        return canonical_digest({
            "envelope_digest": self.envelope.envelope_digest,
            "body": dict(self.body),
            "output_schema_sha256": self.output_schema_sha256,
        })




@dataclass(frozen=True, slots=True)
class ModelProjectDefinition:
    """Level-0 model declaration independent of provider and active prompt generation."""

    role: str
    capability_id: str = "generation"
    prompt_id: str | None = None
    required_capabilities: tuple[str, ...] = ()
    minimum_context_tokens: int = 1
    tool_schema_sha256: str | None = None
    input_schema_id: str = "model.generation.request.v1"
    output_schema_id: str = "model.generation.response.v1"

    def __post_init__(self) -> None:
        _text(self.role, "model project role")
        _text(self.capability_id, "model project capability_id")
        _text(self.input_schema_id, "model project input_schema_id")
        _text(self.output_schema_id, "model project output_schema_id")
        generation = self.capability_id in {"generation", "structured-generation"}
        if generation:
            _text(self.prompt_id, "model project prompt_id")
        elif self.prompt_id is not None:
            raise ValueError("non-generation model project must not declare prompt_id")
        object.__setattr__(
            self, "required_capabilities",
            _tokens(self.required_capabilities, "model project capabilities"),
        )
        if type(self.minimum_context_tokens) is not int or self.minimum_context_tokens <= 0:
            raise ValueError("model project minimum_context_tokens must be positive")
        if self.tool_schema_sha256 is not None:
            if not generation:
                raise ValueError("tool schema identity is only valid for generation projects")
            _sha256(self.tool_schema_sha256, "model project tool_schema_sha256")

    @property
    def is_generation(self) -> bool:
        return self.capability_id in {"generation", "structured-generation"}

    def digest(self) -> str:
        return canonical_digest(self)

    def requirement(
        self,
        prompt_selection: PromptSelectionPort | None = None,
    ) -> ModelCapabilityRequirement:
        if self.is_generation:
            if not isinstance(prompt_selection, PromptSelectionPort):
                raise TypeError("generation model project requires PromptSelectionPort")
            selection = prompt_selection.resolve_selection(self.prompt_id or "")
            if selection.prompt_id != self.prompt_id:
                raise ValueError("prompt selection changed requested prompt_id")
            if selection.role != self.role:
                raise ValueError("prompt selection role does not match model project role")
            return ModelCapabilityRequirement(
                role=self.role,
                prompt_generation_id=selection.generation_id,
                prompt_id=selection.prompt_id,
                prompt_digest=selection.prompt_digest,
                required_capabilities=self.required_capabilities,
                minimum_context_tokens=self.minimum_context_tokens,
                tool_schema_sha256=self.tool_schema_sha256,
                capability_id=self.capability_id,
                input_schema_id=self.input_schema_id,
                output_schema_id=self.output_schema_id,
            )
        if prompt_selection is not None:
            raise ValueError("non-generation model project must not consume prompt selection")
        return ModelCapabilityRequirement(
            role=self.role,
            required_capabilities=self.required_capabilities,
            minimum_context_tokens=self.minimum_context_tokens,
            capability_id=self.capability_id,
            input_schema_id=self.input_schema_id,
            output_schema_id=self.output_schema_id,
        )

    def contribution(
        self,
        prompt_selection: PromptSelectionPort | None = None,
    ) -> "ModelRequirementContribution":
        return ModelRequirementContribution(self.digest(), self.requirement(prompt_selection))


@dataclass(frozen=True, slots=True)
class ModelRequirementContribution:
    author_definition_digest: str
    requirement: ModelCapabilityRequirement

    def __post_init__(self) -> None:
        _sha256(self.author_definition_digest, "model contribution author digest")
        if not isinstance(self.requirement, ModelCapabilityRequirement):
            raise TypeError("model contribution requirement must be typed")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ModelProviderProfile:
    provider_id: str
    capabilities: tuple[str, ...]
    schema_version: str = "project-model-provider.v1"

    def __post_init__(self) -> None:
        _text(self.provider_id, "model provider_id")
        if self.schema_version != "project-model-provider.v1":
            raise ValueError("unsupported project model provider schema")
        object.__setattr__(
            self,
            "capabilities",
            _tokens(self.capabilities, "model provider capabilities"),
        )

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ProjectModelBinding:
    """Project-visible qualified model provenance with no route/process authority."""

    requirement_digest: str
    provider_id: str
    provider_profile_digest: str
    role: str
    model: ImmutableModelIdentity
    deployment_id: str
    deployment_generation: str
    model_stack_digest: str
    qualification_certificate_digest: str
    runtime_qualification_digest: str
    host_identity_digest: str
    prompt_generation_id: str | None
    prompt_id: str | None
    prompt_digest: str | None
    capabilities: tuple[str, ...]
    runtime_canary_evidence_digests: tuple[str, ...]
    capability_id: str = "generation"
    input_schema_id: str = "model.generation.request.v1"
    output_schema_id: str = "model.generation.response.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "requirement_digest",
            "provider_profile_digest",
            "deployment_generation",
            "model_stack_digest",
            "qualification_certificate_digest",
            "runtime_qualification_digest",
            "host_identity_digest",
        ):
            _sha256(getattr(self, field_name), f"project model binding {field_name}")
        for field_name in ("provider_id", "role", "deployment_id", "capability_id", "input_schema_id", "output_schema_id"):
            _text(getattr(self, field_name), f"project model binding {field_name}")
        generation = self.capability_id in {"generation", "structured-generation"}
        prompt_fields = (self.prompt_generation_id, self.prompt_id, self.prompt_digest)
        if generation:
            _text(self.prompt_generation_id, "project model binding prompt_generation_id")
            _text(self.prompt_id, "project model binding prompt_id")
            _sha256(self.prompt_digest, "project model binding prompt_digest")
        elif any(value is not None for value in prompt_fields):
            raise ValueError("non-generation model binding must not carry prompt identity")
        if not isinstance(self.model, ImmutableModelIdentity):
            raise TypeError("project model binding model must be ImmutableModelIdentity")
        object.__setattr__(
            self,
            "capabilities",
            _tokens(self.capabilities, "project model binding capabilities"),
        )
        if not isinstance(self.runtime_canary_evidence_digests, tuple):
            raise TypeError("project model binding canary evidence must be a tuple")
        for digest in self.runtime_canary_evidence_digests:
            _sha256(digest, "project model binding runtime canary evidence digest")
        if len(set(self.runtime_canary_evidence_digests)) != len(
            self.runtime_canary_evidence_digests
        ):
            raise ValueError("project model binding canary evidence must be unique")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ProjectModelRequest:
    requirement_digest: str
    envelope: ModelRequestEnvelope
    body: Mapping[str, JsonInput]
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha256(self.requirement_digest, "project model request requirement_digest")
        if not isinstance(self.envelope, ModelRequestEnvelope):
            raise TypeError("project model request envelope must be ModelRequestEnvelope")
        if not isinstance(self.body, Mapping):
            raise TypeError("project model request body must be a mapping")
        frozen_body = freeze_json(self.body)
        object.__setattr__(self, "body", frozen_body)
        object.__setattr__(
            self,
            "request_digest",
            canonical_digest(
                {
                    "requirement_digest": self.requirement_digest,
                    "envelope_digest": self.envelope.envelope_digest,
                    "body": dict(frozen_body),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ProjectModelResponse:
    request_digest: str
    binding_digest: str
    response_digest: str
    text: str
    tool_calls: JsonValue = ()
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        _sha256(self.request_digest, "project model response request_digest")
        _sha256(self.binding_digest, "project model response binding_digest")
        _sha256(self.response_digest, "project model response response_digest")
        _text(self.text, "project model response text")
        if self.finish_reason is not None and not isinstance(self.finish_reason, str):
            raise TypeError("project model response finish_reason must be text when provided")
        for field_name in ("input_tokens", "output_tokens"):
            value = getattr(self, field_name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"project model response {field_name} must be non-negative")


class ModelBindingDiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ModelBindingDiagnosticCode(StrEnum):
    CAPABILITY_MISSING = "MODEL_CAPABILITY_MISSING"
    QUALIFIED_BINDING_UNAVAILABLE = "MODEL_QUALIFIED_BINDING_UNAVAILABLE"
    CONTEXT_INSUFFICIENT = "MODEL_CONTEXT_INSUFFICIENT"
    BINDING_PROVENANCE_DRIFT = "MODEL_BINDING_PROVENANCE_DRIFT"
    CAPABILITY_PROTOCOL_UNSUPPORTED = "MODEL_CAPABILITY_PROTOCOL_UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class ModelBindingDiagnostic:
    code: ModelBindingDiagnosticCode
    severity: ModelBindingDiagnosticSeverity
    message: str
    requirement_digest: str
    provider_id: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.code, ModelBindingDiagnosticCode):
            raise TypeError("model diagnostic code must be typed")
        if not isinstance(self.severity, ModelBindingDiagnosticSeverity):
            raise TypeError("model diagnostic severity must be typed")
        _text(self.message, "model diagnostic message")
        _sha256(self.requirement_digest, "model diagnostic requirement_digest")
        _text(self.provider_id, "model diagnostic provider_id")
        if not isinstance(self.evidence_refs, tuple) or any(
            not isinstance(ref, str) or not ref.strip() for ref in self.evidence_refs
        ):
            raise TypeError("model diagnostic evidence_refs must be non-empty strings")


class ModelProjectBindingError(RuntimeError):
    def __init__(self, diagnostics: tuple[ModelBindingDiagnostic, ...]) -> None:
        if not diagnostics:
            raise ValueError("model binding error requires typed diagnostics")
        self.diagnostics = diagnostics
        super().__init__("; ".join(row.message for row in diagnostics))


@runtime_checkable
class ProjectModelClientPort(Protocol):
    @property
    def binding(self) -> ProjectModelBinding: ...

    def complete(self, request: ProjectModelRequest) -> ProjectModelResponse: ...


@runtime_checkable
class ProjectModelProviderPort(Protocol):
    @property
    def profile(self) -> ModelProviderProfile: ...

    def bind(self, requirement: ModelCapabilityRequirement) -> ProjectModelClientPort: ...

    def diagnose(
        self, requirement: ModelCapabilityRequirement
    ) -> tuple[ModelBindingDiagnostic, ...]: ...


__all__ = [
    "ModelBindingDiagnostic",
    "ModelBindingDiagnosticCode",
    "ModelBindingDiagnosticSeverity",
    "ModelCapabilityRequirement",
    "ModelProjectBindingError",
    "ModelProjectDefinition",
    "MultimodalInferenceOutput",
    "MultimodalInferenceInput",
    "MultimodalContent",
    "ModelRequirementContribution",
    "ModelProviderProfile",
    "ProjectModelBinding",
    "ProjectModelClientPort",
    "ProjectModelProviderPort",
    "ProjectModelRequest",
    "ProjectModelResponse",
    "StructuredGenerationInput",
]
