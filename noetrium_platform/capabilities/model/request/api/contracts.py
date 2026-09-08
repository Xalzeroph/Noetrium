from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext, ImmutableModelIdentity, JsonInput, JsonObject, JsonValue, canonical_digest, freeze_json, require_sha256,
)


_MODEL_REQUEST_SCHEMAS = frozenset({"model-request.v1", "runtime-canary-request.v1"})


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
class ContentRef:
    sha256: str
    size_bytes: int
    media_type: str

    def __post_init__(self) -> None:
        _sha256(self.sha256, "content sha256")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise ValueError("content size_bytes must be an integer")
        if self.size_bytes < 0:
            raise ValueError("content size_bytes must be non-negative")
        _text(self.media_type, "content media_type")


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
    request_body: ContentRef
    compiled_prompt: ContentRef | None = None
    tool_schema_bundle: ContentRef | None = None
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
        if not isinstance(self.request_body, ContentRef):
            raise ValueError("model request request_body must be a ContentRef")
        if self.compiled_prompt is not None and not isinstance(self.compiled_prompt, ContentRef):
            raise ValueError("model request compiled_prompt must be a ContentRef")
        if self.tool_schema_bundle is not None and not isinstance(self.tool_schema_bundle, ContentRef):
            raise ValueError("model request tool_schema_bundle must be a ContentRef")
        _refs(self.source_artifact_refs, "model request source_artifact_refs")
        _refs(self.source_state_refs, "model request source_state_refs")
        expected = canonical_digest({
            key: value
            for key, value in asdict(self).items()
            if key != "envelope_digest"
        })
        if self.envelope_digest:
            _sha256(self.envelope_digest, "model request envelope_digest")
            if self.envelope_digest != expected:
                raise ValueError("model request envelope digest mismatch")
        object.__setattr__(self, "envelope_digest", expected)


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
class ContentAddressedStorePort(Protocol):
    durability: str

    def put(self, payload: bytes, *, media_type: str) -> ContentRef: ...
    def get(self, ref: ContentRef) -> bytes: ...


@runtime_checkable
class ModelRequestLedgerPort(Protocol):
    durability: str

    def append(self, envelope: ModelRequestEnvelope) -> None: ...
    def get(self, request_id: str) -> ModelRequestEnvelope: ...


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

    def reconstruct(self, envelope: ModelRequestEnvelope) -> ReconstructedModelRequest: ...
    def reconstruct_request_body(self, envelope: ModelRequestEnvelope) -> JsonObject: ...
    def verify_visible_request(
        self, envelope: ModelRequestEnvelope, actual_body: Mapping[str, JsonInput]
    ) -> None: ...


__all__ = [
    "ContentAddressedStorePort",
    "ContentRef",
    "ModelRequestEnvelope",
    "ModelRequestLedgerPort",
    "ModelRequestRecorderPort",
    "ReconstructedModelRequest",
]
