from __future__ import annotations

from collections.abc import Callable
from typing import Generic

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityCarrierTransportPort,
    CapabilityDescriptor,
    CapabilityProviderIdentity,
    CapabilityRequest,
    CapabilityResult,
    TypedCapabilityCarrierCodec,
    decode_typed_capability_input,
    make_typed_capability_result,
    require_pure_typed_descriptor,
)
from noetrium_platform.capabilities.participant.capability.api.typed import InputCarrierT, OutputCarrierT


class FunctionalTypedCapabilityProvider(Generic[InputCarrierT, OutputCarrierT]):
    """Stateless typed specialization of the canonical CapabilityExportSession authority."""

    def __init__(
        self,
        *,
        identity: CapabilityProviderIdentity,
        descriptor: CapabilityDescriptor,
        codec: TypedCapabilityCarrierCodec[InputCarrierT, OutputCarrierT],
        transport: CapabilityCarrierTransportPort,
        participant_role: str,
        handler: Callable[[InputCarrierT, ExecutionContext], OutputCarrierT],
    ) -> None:
        if not isinstance(identity, CapabilityProviderIdentity):
            raise TypeError("typed capability provider identity must be typed")
        if not isinstance(descriptor, CapabilityDescriptor):
            raise TypeError("typed capability provider descriptor must be typed")
        if not isinstance(participant_role, str) or not participant_role.strip():
            raise ValueError("typed capability provider participant_role must be non-empty")
        require_pure_typed_descriptor(descriptor)
        self._identity = identity
        self._descriptor = descriptor
        self._codec = codec
        self._transport = transport
        self._participant_role = participant_role
        self._handler = handler
        self._closed = False

    @property
    def identity(self) -> CapabilityProviderIdentity:
        return self._identity

    @property
    def descriptor(self) -> CapabilityDescriptor:
        return self._descriptor

    @property
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        return (self._descriptor,)

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        if self._closed:
            raise RuntimeError("typed capability provider is closed")
        if request.capability_id != self._descriptor.capability_id:
            raise ValueError("typed capability request does not match provider descriptor")
        payload = decode_typed_capability_input(
            request,
            descriptor=self._descriptor,
            codec=self._codec,
            transport=self._transport,
        )
        before_digest = payload.digest()
        result_payload = self._handler(payload, request.context)
        if payload.digest() != before_digest:
            raise ValueError("typed capability handler mutated its input carrier")
        generation = request.context.generation(self._participant_role)
        if generation is None:
            raise ValueError("typed capability context is missing participant generation")
        return make_typed_capability_result(
            descriptor=self._descriptor,
            payload=result_payload,
            request=request,
            provider_identity=self._identity,
            generation=generation,
            codec=self._codec,
            transport=self._transport,
        )

    def checkpoint(self) -> bytes:
        if self._closed:
            raise RuntimeError("typed capability provider is closed")
        return b""

    def restore(self, payload: bytes) -> None:
        if payload != b"":
            raise ValueError("stateless typed capability provider accepts only empty checkpoint")
        if self._closed:
            raise RuntimeError("typed capability provider is closed")

    def close(self) -> None:
        self._closed = True


__all__ = ["FunctionalTypedCapabilityProvider"]
