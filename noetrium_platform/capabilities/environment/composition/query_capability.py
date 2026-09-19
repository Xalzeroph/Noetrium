from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.environment.api import (
    EnvironmentQuery,
    EnvironmentQueryPort,
    EnvironmentQueryResult,
    Observation,
)
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
    capability_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import EffectClass, JsonInput, JsonValue

_REQUEST_SCHEMA = "noetrium.environment.query-capability.request.v1"
_RESULT_SCHEMA = "noetrium.environment.query-capability.result.v1"


def environment_query_capability_payload(
    query_type: str,
    payload: JsonInput,
) -> dict[str, JsonInput]:
    if not isinstance(query_type, str) or not query_type.strip():
        raise ValueError("environment query capability query_type must be non-empty")
    return {"query_type": query_type, "payload": payload}


def _observation_payload(observation: Observation | None) -> JsonValue:
    if observation is None:
        return None
    if not isinstance(observation, Observation):
        raise TypeError("environment query result observation must be Observation")
    return {
        "observation_id": observation.observation_id,
        "generation": observation.generation,
        "payload": observation.payload,
        "artifact_refs": observation.artifact_refs,
    }


class EnvironmentQueryCapabilityBinding:
    """Mechanical binding from native environment queries to CapabilityPort.

    This object owns no environment state and no observation authority. It only
    exposes an existing read-only EnvironmentQueryPort through the common
    capability execution surface used by MethodProgram.
    """

    def __init__(
        self,
        query: EnvironmentQueryPort,
        *,
        capability_id: str = "environment.query",
    ) -> None:
        if not isinstance(query, EnvironmentQueryPort):
            raise TypeError("environment query capability requires EnvironmentQueryPort")
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise ValueError("environment query capability_id must be non-empty")
        self._query = query
        self._descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            interface_version="1",
            request_schema=_REQUEST_SCHEMA,
            result_schema=_RESULT_SCHEMA,
            effect_class=EffectClass.PURE,
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
        payload = request.payload
        if not isinstance(payload, Mapping):
            raise TypeError("environment query capability payload must be a mapping")
        query_type = payload.get("query_type")
        if not isinstance(query_type, str) or not query_type.strip():
            raise ValueError("environment query capability requires query_type")
        if "payload" not in payload:
            raise ValueError("environment query capability requires payload")

        request_digest = capability_request_digest(request)
        query = EnvironmentQuery(
            query_id=f"environment-query:{request_digest[:24]}",
            query_type=query_type,
            payload=payload["payload"],
            context=request.context,
        )
        result = self._query.query(query)
        if not isinstance(result, EnvironmentQueryResult):
            raise TypeError("environment query port must return EnvironmentQueryResult")
        if result.query_id != query.query_id:
            raise ValueError("environment query result identity mismatch")

        observation = result.observation
        return CapabilityResult(
            capability_id=self._descriptor.capability_id,
            payload={
                "supported": result.supported,
                "payload": result.payload,
                "observation": _observation_payload(observation),
            },
            generation=None if observation is None else observation.generation,
            artifacts=() if observation is None else observation.artifact_refs,
            diagnostics=dict(result.diagnostics),
            request_digest=request_digest,
        )


__all__ = [
    "EnvironmentQueryCapabilityBinding",
    "environment_query_capability_payload",
]
