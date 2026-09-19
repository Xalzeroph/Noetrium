from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from typing import Protocol, TypeVar, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import EffectClass, ExecutionContext, JsonObject, JsonValue

from .contracts import (
    CapabilityDescriptor,
    CapabilityProviderIdentity,
    CapabilityRequest,
    CapabilityResult,
    capability_request_digest,
)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def _sha256(value: object, field: str) -> str:
    digest = _text(value, field)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return digest


@runtime_checkable
class CapabilityInputCarrier(Protocol):
    @property
    def schema_id(self) -> str: ...

    def digest(self) -> str: ...


@runtime_checkable
class CapabilityOutputCarrier(Protocol):
    @property
    def schema_id(self) -> str: ...

    def digest(self) -> str: ...


InputCarrierT = TypeVar("InputCarrierT", bound=CapabilityInputCarrier)
OutputCarrierT = TypeVar("OutputCarrierT", bound=CapabilityOutputCarrier)


@runtime_checkable
class TypedCapabilityCarrierCodec(Protocol[InputCarrierT, OutputCarrierT]):
    input_schema_id: str
    output_schema_id: str
    codec_id: str
    implementation_digest: str
    media_type: str
    def encode_input(self, value: InputCarrierT) -> bytes: ...
    def decode_input(self, payload: bytes) -> InputCarrierT: ...
    def encode_output(self, value: OutputCarrierT) -> bytes: ...
    def decode_output(self, payload: bytes) -> OutputCarrierT: ...


@dataclass(frozen=True, slots=True)
class TypedCarrierReference:
    descriptor_digest: str
    schema_id: str
    semantic_digest: str
    content_digest: str
    content_size: int
    media_type: str
    codec_id: str
    codec_implementation_digest: str

    def __post_init__(self) -> None:
        _sha256(self.descriptor_digest, "typed carrier descriptor digest")
        _text(self.schema_id, "typed carrier schema id")
        _sha256(self.semantic_digest, "typed carrier semantic digest")
        _sha256(self.content_digest, "typed carrier content digest")
        if type(self.content_size) is not int or self.content_size < 0:
            raise ValueError("typed carrier content size must be a non-negative integer")
        _text(self.media_type, "typed carrier media type")
        _text(self.codec_id, "typed carrier codec id")
        _sha256(self.codec_implementation_digest, "typed carrier codec implementation digest")

    def as_json(self) -> JsonObject:
        return {
            "descriptor_digest": self.descriptor_digest,
            "schema_id": self.schema_id,
            "semantic_digest": self.semantic_digest,
            "content_digest": self.content_digest,
            "content_size": self.content_size,
            "media_type": self.media_type,
            "codec_id": self.codec_id,
            "codec_implementation_digest": self.codec_implementation_digest,
        }

    @classmethod
    def from_json(cls, value: JsonValue) -> "TypedCarrierReference":
        if not isinstance(value, Mapping):
            raise TypeError("typed carrier reference payload must be an object")
        expected = {
            "descriptor_digest", "schema_id", "semantic_digest", "content_digest",
            "content_size", "media_type", "codec_id", "codec_implementation_digest",
        }
        if set(value) != expected:
            raise ValueError("typed carrier reference fields are invalid")
        return cls(
            descriptor_digest=value["descriptor_digest"],
            schema_id=value["schema_id"],
            semantic_digest=value["semantic_digest"],
            content_digest=value["content_digest"],
            content_size=value["content_size"],
            media_type=value["media_type"],
            codec_id=value["codec_id"],
            codec_implementation_digest=value["codec_implementation_digest"],
        )


@runtime_checkable
class CapabilityCarrierTransportPort(Protocol):
    """Byte transport only; durable Artifact/Data authority remains outside Participant."""

    def publish(self, reference: TypedCarrierReference, payload: bytes) -> None: ...
    def load(self, reference: TypedCarrierReference) -> bytes: ...


def _verify_codec(
    descriptor: CapabilityDescriptor,
    codec: TypedCapabilityCarrierCodec[InputCarrierT, OutputCarrierT],
) -> None:
    if not isinstance(codec, TypedCapabilityCarrierCodec):
        raise TypeError("typed capability codec must satisfy TypedCapabilityCarrierCodec")
    if codec.input_schema_id != descriptor.request_schema:
        raise ValueError("typed capability codec input schema does not match descriptor")
    if codec.output_schema_id != descriptor.result_schema:
        raise ValueError("typed capability codec output schema does not match descriptor")
    _text(codec.codec_id, "typed capability codec id")
    _sha256(codec.implementation_digest, "typed capability codec implementation digest")
    _text(codec.media_type, "typed capability codec media type")


def _reference(
    *,
    descriptor: CapabilityDescriptor,
    schema_id: str,
    semantic_digest: str,
    payload: bytes,
    codec: TypedCapabilityCarrierCodec[InputCarrierT, OutputCarrierT],
) -> TypedCarrierReference:
    if not isinstance(payload, bytes):
        raise TypeError("typed carrier codec payload must be bytes")
    return TypedCarrierReference(
        descriptor_digest=descriptor.digest(),
        schema_id=schema_id,
        semantic_digest=_sha256(semantic_digest, "typed carrier semantic digest"),
        content_digest=hashlib.sha256(payload).hexdigest(),
        content_size=len(payload),
        media_type=codec.media_type,
        codec_id=codec.codec_id,
        codec_implementation_digest=codec.implementation_digest,
    )


def _verify_reference(
    reference: TypedCarrierReference,
    *,
    descriptor: CapabilityDescriptor,
    schema_id: str,
    codec: TypedCapabilityCarrierCodec[InputCarrierT, OutputCarrierT],
) -> None:
    if reference.descriptor_digest != descriptor.digest():
        raise ValueError("typed carrier reference does not match capability descriptor")
    if reference.schema_id != schema_id:
        raise ValueError("typed carrier reference schema does not match capability descriptor")
    if reference.media_type != codec.media_type:
        raise ValueError("typed carrier reference media type does not match codec")
    if reference.codec_id != codec.codec_id:
        raise ValueError("typed carrier reference codec id does not match codec")
    if reference.codec_implementation_digest != codec.implementation_digest:
        raise ValueError("typed carrier reference codec implementation does not match codec")


def _load_payload(
    reference: TypedCarrierReference,
    *,
    transport: CapabilityCarrierTransportPort,
) -> bytes:
    if not isinstance(transport, CapabilityCarrierTransportPort):
        raise TypeError("typed carrier transport must satisfy CapabilityCarrierTransportPort")
    payload = transport.load(reference)
    if not isinstance(payload, bytes):
        raise TypeError("typed carrier transport must return bytes")
    if len(payload) != reference.content_size:
        raise ValueError("typed carrier transport returned wrong content size")
    if hashlib.sha256(payload).hexdigest() != reference.content_digest:
        raise ValueError("typed carrier transport returned content with wrong digest")
    return payload


def make_typed_capability_request(
    *,
    descriptor: CapabilityDescriptor,
    payload: InputCarrierT,
    context: ExecutionContext,
    codec: TypedCapabilityCarrierCodec[InputCarrierT, OutputCarrierT],
    transport: CapabilityCarrierTransportPort,
    idempotency_key: str | None = None,
) -> CapabilityRequest:
    if not isinstance(descriptor, CapabilityDescriptor):
        raise TypeError("typed capability descriptor must be typed")
    if not isinstance(payload, CapabilityInputCarrier):
        raise TypeError("typed capability input must satisfy CapabilityInputCarrier")
    if payload.schema_id != descriptor.request_schema:
        raise ValueError("typed capability input schema does not match descriptor")
    if not isinstance(context, ExecutionContext):
        raise TypeError("typed capability context must be ExecutionContext")
    _verify_codec(descriptor, codec)
    encoded = codec.encode_input(payload)
    reference = _reference(
        descriptor=descriptor,
        schema_id=payload.schema_id,
        semantic_digest=payload.digest(),
        payload=encoded,
        codec=codec,
    )
    transport.publish(reference, encoded)
    return CapabilityRequest(
        descriptor.capability_id,
        reference.as_json(),
        context,
        idempotency_key,
    )


def decode_typed_capability_input(
    request: CapabilityRequest,
    *,
    descriptor: CapabilityDescriptor,
    codec: TypedCapabilityCarrierCodec[InputCarrierT, OutputCarrierT],
    transport: CapabilityCarrierTransportPort,
) -> InputCarrierT:
    if request.capability_id != descriptor.capability_id:
        raise ValueError("typed capability request id does not match descriptor")
    _verify_codec(descriptor, codec)
    reference = TypedCarrierReference.from_json(request.payload)
    _verify_reference(
        reference,
        descriptor=descriptor,
        schema_id=descriptor.request_schema,
        codec=codec,
    )
    payload = codec.decode_input(_load_payload(reference, transport=transport))
    if not isinstance(payload, CapabilityInputCarrier):
        raise TypeError("typed capability codec returned invalid input carrier")
    if payload.schema_id != descriptor.request_schema:
        raise ValueError("decoded typed capability input schema does not match descriptor")
    if _sha256(payload.digest(), "decoded typed input digest") != reference.semantic_digest:
        raise ValueError("decoded typed capability input semantic digest does not match reference")
    return payload


def make_typed_capability_result(
    *,
    descriptor: CapabilityDescriptor,
    payload: OutputCarrierT,
    request: CapabilityRequest,
    provider_identity: CapabilityProviderIdentity,
    generation: str | None,
    codec: TypedCapabilityCarrierCodec[InputCarrierT, OutputCarrierT],
    transport: CapabilityCarrierTransportPort,
) -> CapabilityResult:
    if not isinstance(payload, CapabilityOutputCarrier):
        raise TypeError("typed capability output must satisfy CapabilityOutputCarrier")
    if payload.schema_id != descriptor.result_schema:
        raise ValueError("typed capability output schema does not match descriptor")
    _verify_codec(descriptor, codec)
    encoded = codec.encode_output(payload)
    reference = _reference(
        descriptor=descriptor,
        schema_id=payload.schema_id,
        semantic_digest=payload.digest(),
        payload=encoded,
        codec=codec,
    )
    transport.publish(reference, encoded)
    return CapabilityResult(
        capability_id=descriptor.capability_id,
        payload=reference.as_json(),
        generation=generation,
        provider_identity=provider_identity,
        request_digest=capability_request_digest(request),
    )


def decode_typed_capability_result(
    result: CapabilityResult,
    *,
    request: CapabilityRequest,
    descriptor: CapabilityDescriptor,
    codec: TypedCapabilityCarrierCodec[InputCarrierT, OutputCarrierT],
    transport: CapabilityCarrierTransportPort,
    expected_provider_identity: CapabilityProviderIdentity,
) -> OutputCarrierT:
    if result.capability_id != descriptor.capability_id:
        raise ValueError("typed capability result id does not match descriptor")
    if result.provider_identity != expected_provider_identity:
        raise ValueError("typed capability result provider identity does not match expected provider")
    if result.provider_identity is None:
        raise ValueError("typed capability result is missing provider identity")
    expected_request_digest = capability_request_digest(request)
    if result.request_digest != expected_request_digest:
        raise ValueError("typed capability result does not match canonical request provenance")
    _verify_codec(descriptor, codec)
    reference = TypedCarrierReference.from_json(result.payload)
    _verify_reference(
        reference,
        descriptor=descriptor,
        schema_id=descriptor.result_schema,
        codec=codec,
    )
    payload = codec.decode_output(_load_payload(reference, transport=transport))
    if not isinstance(payload, CapabilityOutputCarrier):
        raise TypeError("typed capability codec returned invalid output carrier")
    if payload.schema_id != descriptor.result_schema:
        raise ValueError("decoded typed capability output schema does not match descriptor")
    if _sha256(payload.digest(), "decoded typed output digest") != reference.semantic_digest:
        raise ValueError("decoded typed capability output semantic digest does not match reference")
    return payload


def require_pure_typed_descriptor(descriptor: CapabilityDescriptor) -> None:
    if descriptor.effect_class is not EffectClass.PURE:
        raise ValueError(
            "direct typed provider supports only PURE capabilities; "
            "effectful typed capabilities must use canonical DurablePreparedCapabilitySession"
        )


__all__ = [
    "CapabilityCarrierTransportPort",
    "CapabilityInputCarrier",
    "CapabilityOutputCarrier",
    "TypedCapabilityCarrierCodec",
    "TypedCarrierReference",
    "decode_typed_capability_input",
    "decode_typed_capability_result",
    "make_typed_capability_request",
    "make_typed_capability_result",
    "require_pure_typed_descriptor",
]
