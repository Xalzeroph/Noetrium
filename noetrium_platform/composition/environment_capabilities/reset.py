from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.environment.api import (
    EnvironmentResetPort,
    Observation,
)
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
    capability_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import EffectClass, JsonInput, JsonValue

_REQUEST_SCHEMA = "noetrium.environment.reset-capability.request.v1"
_RESULT_SCHEMA = "noetrium.environment.reset-capability.result.v1"


def environment_reset_capability_payload(
    metadata: Mapping[str, JsonInput] | None = None,
) -> dict[str, JsonInput]:
    if metadata is None:
        return {}
    if not isinstance(metadata, Mapping):
        raise TypeError("environment reset metadata must be a mapping")
    return {str(key): value for key, value in metadata.items()}


def _observation_payload(observation: Observation) -> JsonValue:
    if not isinstance(observation, Observation):
        raise TypeError("environment reset must return Observation")
    return {
        "observation_id": observation.observation_id,
        "generation": observation.generation,
        "payload": observation.payload,
        "artifact_refs": observation.artifact_refs,
    }


class EnvironmentResetCapabilityBinding:
    """Expose native task reset through the common MethodProgram capability ABI.

    The binding owns no environment state and never reopens provider sessions.
    It delegates reset truth to EnvironmentResetPort and records the caller's
    method-owned metadata only as request/result lineage.
    """

    def __init__(
        self,
        reset: EnvironmentResetPort,
        *,
        capability_id: str = "environment.reset",
    ) -> None:
        if not isinstance(reset, EnvironmentResetPort):
            raise TypeError("environment reset capability requires EnvironmentResetPort")
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise ValueError("environment reset capability_id must be non-empty")
        self._reset = reset
        self._descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            interface_version="1",
            request_schema=_REQUEST_SCHEMA,
            result_schema=_RESULT_SCHEMA,
            effect_class=EffectClass.IDEMPOTENT,
            deterministic=False,
        )

    @property
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        return (self._descriptor,)

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        if capability_id != self._descriptor.capability_id:
            raise KeyError(capability_id)
        return self._descriptor

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        if request.capability_id != self._descriptor.capability_id:
            raise KeyError(request.capability_id)
        if not isinstance(request.payload, Mapping):
            raise TypeError("environment reset capability payload must be a mapping")

        request_digest = capability_request_digest(request)
        observation = self._reset.reset(request.context)
        return CapabilityResult(
            capability_id=self._descriptor.capability_id,
            payload={
                "reset": True,
                "observation": _observation_payload(observation),
                "metadata": dict(request.payload),
            },
            generation=observation.generation,
            artifacts=observation.artifact_refs,
            diagnostics={"reset": True},
            request_digest=request_digest,
        )


__all__ = [
    "EnvironmentResetCapabilityBinding",
    "environment_reset_capability_payload",
]
