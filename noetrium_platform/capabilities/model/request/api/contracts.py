from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Protocol, runtime_checkable

from noetrium_platform.substrate.api import ArtifactBlobRef

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext, ImmutableModelIdentity, JsonInput, JsonObject, JsonValue, canonical_digest, freeze_json, require_sha256,
)


_MODEL_REQUEST_SCHEMAS = frozenset({"model-request.v1", "runtime-canary-request.v1"})
_MODEL_OPERATION_SCHEMAS = frozenset({"model-operation.v1", "runtime-canary-operation.v1"})


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _sha256(value: object, field: str) -> str:
    return require_sha256(value, field)


def _refs(values: object, field: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(item, str) or not item.strip() for item in values
    ):
        raise ValueError(f"{field} must be a tuple of non-empty strings")
    return values


@dataclass(frozen=True, slots=True)
class ModelRequestEnvelope:
    schema_version: str
    request_id: str
    context: ExecutionContext
    role: str
    model: ImmutableModelIdentity
    prompt_generation_id: str
    prompt_id: str
    prompt_digest: str
    request_body: ArtifactBlobRef
    compiled_prompt: ArtifactBlobRef | None = None
    tool_schema_bundle: ArtifactBlobRef | None = None
    source_artifact_refs: tuple[str, ...] = ()
    source_state_refs: tuple[str, ...] = ()
    envelope_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version not in _MODEL_REQUEST_SCHEMAS:
            raise ValueError("unsupported model request schema_version")
        _text(self.request_id, "model request_id")
        _text(self.role, "model request role")
        _text(self.prompt_generation_id, "model request prompt_generation_id")
        _text(self.prompt_id, "model request prompt_id")
        _sha256(self.prompt_digest, "model request prompt_digest")
        if not isinstance(self.context, ExecutionContext):
            raise ValueError("model request context must be an ExecutionContext")
        if not isinstance(self.model, ImmutableModelIdentity):
            raise ValueError("model request model must be an ImmutableModelIdentity")
        for field_name in (
            "logical_name", "model_id", "revision", "engine", "engine_version", "dtype"
        ):
            _text(getattr(self.model, field_name), f"model request model.{field_name}")
        if isinstance(self.model.context_length, bool) or not isinstance(self.model.context_length, int):
            raise ValueError("model request model.context_length must be an integer")
        if self.model.context_length <= 0:
            raise ValueError("model request model.context_length must be positive")
        if self.model.quantization is not None:
            _text(self.model.quantization, "model request model.quantization")
        if self.model.tokenizer_revision is not None:
            _text(self.model.tokenizer_revision, "model request model.tokenizer_revision")
        if not isinstance(self.request_body, ArtifactBlobRef):
            raise ValueError("model request request_body must be an ArtifactBlobRef")
        if self.compiled_prompt is not None and not isinstance(self.compiled_prompt, ArtifactBlobRef):
            raise ValueError("model request compiled_prompt must be an ArtifactBlobRef")
        if self.tool_schema_bundle is not None and not isinstance(self.tool_schema_bundle, ArtifactBlobRef):
            raise ValueError("model request tool_schema_bundle must be an ArtifactBlobRef")
        _refs(self.source_artifact_refs, "model request source_artifact_refs")
        _refs(self.source_state_refs, "model request source_state_refs")
        expected = canonical_digest({
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name != "envelope_digest"
        })
        if self.envelope_digest:
            _sha256(self.envelope_digest, "model request envelope_digest")
            if self.envelope_digest != expected:
                raise ValueError("model request envelope digest mismatch")
        object.__setattr__(self, "envelope_digest", expected)


@dataclass(frozen=True, slots=True)
class ModelOperationEnvelope:
    """Provider-neutral scientific identity for any non-prompt model operation."""

    schema_version: str
    request_id: str
    context: ExecutionContext
    role: str
    model: ImmutableModelIdentity
    capability_id: str
    input_schema_id: str
    output_schema_id: str
    request_body: ArtifactBlobRef
    source_artifact_refs: tuple[str, ...] = ()
    source_state_refs: tuple[str, ...] = ()
    envelope_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version not in _MODEL_OPERATION_SCHEMAS:
            raise ValueError("unsupported model operation schema_version")
        for value, field in (
            (self.request_id, "model operation request_id"),
            (self.role, "model operation role"),
            (self.capability_id, "model operation capability_id"),
            (self.input_schema_id, "model operation input_schema_id"),
            (self.output_schema_id, "model operation output_schema_id"),
        ):
            _text(value, field)
        if not isinstance(self.context, ExecutionContext):
            raise ValueError("model operation context must be an ExecutionContext")
        if not isinstance(self.model, ImmutableModelIdentity):
            raise ValueError("model operation model must be an ImmutableModelIdentity")
        for field_name in (
            "logical_name", "model_id", "revision", "engine", "engine_version", "dtype"
        ):
            _text(
                getattr(self.model, field_name),
                f"model operation model.{field_name}",
            )
        if (
            isinstance(self.model.context_length, bool)
            or not isinstance(self.model.context_length, int)
            or self.model.context_length <= 0
        ):
            raise ValueError(
                "model operation model.context_length must be a positive integer"
            )
        if self.model.quantization is not None:
            _text(self.model.quantization, "model operation model.quantization")
        if self.model.tokenizer_revision is not None:
            _text(
                self.model.tokenizer_revision,
                "model operation model.tokenizer_revision",
            )
        if not isinstance(self.request_body, ArtifactBlobRef):
            raise ValueError(
                "model operation request_body must be an ArtifactBlobRef"
            )
        _refs(
            self.source_artifact_refs,
            "model operation source_artifact_refs",
        )
        _refs(
            self.source_state_refs,
            "model operation source_state_refs",
        )
        expected = canonical_digest({
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name != "envelope_digest"
        })
        if self.envelope_digest:
            _sha256(
                self.envelope_digest,
                "model operation envelope_digest",
            )
            if self.envelope_digest != expected:
                raise ValueError("model operation envelope digest mismatch")
        object.__setattr__(self, "envelope_digest", expected)


ModelEndpointEnvelope = ModelRequestEnvelope | ModelOperationEnvelope


@dataclass(frozen=True, slots=True)
class ReconstructedModelRequest:
    request_body: JsonObject
    compiled_prompt_text: str | None
    tool_schema_bundle: JsonValue | None

    def __post_init__(self) -> None:
        if not isinstance(self.request_body, Mapping):
            raise TypeError("reconstructed request body must be a mapping")
        object.__setattr__(self, "request_body", freeze_json(self.request_body))
        if self.tool_schema_bundle is not None:
            object.__setattr__(self, "tool_schema_bundle", freeze_json(self.tool_schema_bundle))


@runtime_checkable
class ModelRequestLedgerPort(Protocol):
    """Single durable ledger for generation requests and generic model operations."""

    durability: str

    def append(self, envelope: ModelEndpointEnvelope) -> None: ...
    def get(self, request_id: str) -> ModelEndpointEnvelope: ...


@runtime_checkable
class ModelRequestRecorderPort(Protocol):
    def record(
        self,
        *,
        request_id: str,
        context: ExecutionContext,
        role: str,
        model: ImmutableModelIdentity,
        prompt_generation_id: str,
        prompt_id: str,
        prompt_digest: str,
        request_body: Mapping[str, JsonInput],
        compiled_prompt_text: str | None = None,
        tool_schema_bundle: JsonInput | None = None,
        source_artifact_refs: tuple[str, ...] = (),
        source_state_refs: tuple[str, ...] = (),
    ) -> ModelRequestEnvelope: ...

    def record_operation(
        self,
        *,
        request_id: str,
        context: ExecutionContext,
        role: str,
        model: ImmutableModelIdentity,
        capability_id: str,
        input_schema_id: str,
        output_schema_id: str,
        request_body: Mapping[str, JsonInput],
        source_artifact_refs: tuple[str, ...] = (),
        source_state_refs: tuple[str, ...] = (),
    ) -> ModelOperationEnvelope: ...

    def reconstruct(self, envelope: ModelRequestEnvelope) -> ReconstructedModelRequest: ...
    def reconstruct_request_body(
        self, envelope: ModelEndpointEnvelope
    ) -> JsonObject: ...
    def verify_visible_request(
        self,
        envelope: ModelEndpointEnvelope,
        actual_body: Mapping[str, JsonInput],
    ) -> None: ...


__all__ = [
    "ModelEndpointEnvelope",
    "ModelOperationEnvelope",
    "ModelRequestEnvelope",
    "ModelRequestLedgerPort",
    "ModelRequestRecorderPort",
    "ReconstructedModelRequest",
]
