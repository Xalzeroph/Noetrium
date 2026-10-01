from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.environment.api import Observation
from noetrium_platform.foundation.kernel.kernel import JsonValue


def raw_observation_payload(observation: Observation | None) -> JsonValue:
    if observation is None:
        return None
    if not isinstance(observation, Observation):
        raise TypeError("environment observation must be Observation")
    return {
        "observation_id": observation.observation_id,
        "generation": observation.generation,
        "payload": observation.payload,
        "artifact_refs": observation.artifact_refs,
    }


def semantic_observation_payload(observation: Observation | None) -> JsonValue:
    if observation is None:
        return None
    if not isinstance(observation, Observation):
        raise TypeError("environment observation must be Observation")
    payload = observation.payload
    decision = payload.get("decision_view") if isinstance(payload, Mapping) else None
    return {
        "observation_id": observation.observation_id,
        "generation": observation.generation,
        "payload": decision if isinstance(decision, Mapping) else payload,
        "artifact_refs": observation.artifact_refs,
    }


def observation_evidence(
    observation: Observation | None,
    *,
    schema: str,
) -> JsonValue:
    raw = raw_observation_payload(observation)
    if raw is None:
        return None
    return {"schema": schema, "observation": raw}


__all__ = [
    "observation_evidence",
    "raw_observation_payload",
    "semantic_observation_payload",
]
