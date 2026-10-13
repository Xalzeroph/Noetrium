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


def _decision_constraint_index(facets: object) -> tuple[dict[str, JsonValue], ...]:
    """Compact method-facing index of source-owned decision constraints.

    Facets remain the durable/public evidence authority. This index only avoids
    rescanning every facet on each planner turn and is not a second truth store.
    """
    if not isinstance(facets, (tuple, list)):
        return ()
    rows: list[dict[str, JsonValue]] = []
    for facet in facets:
        if not isinstance(facet, Mapping):
            continue
        constraint = facet.get("decision_constraint")
        if not isinstance(constraint, Mapping) or not constraint:
            continue
        truth = facet.get("truth_class")
        source = facet.get("source")
        if not isinstance(truth, str) or not truth:
            continue
        if not isinstance(source, str) or not source:
            continue
        rows.append({
            "truth_class": truth,
            "source": source,
            "constraint": dict(constraint),
        })
    return tuple(rows)


def semantic_observation_payload(observation: Observation | None) -> JsonValue:
    if observation is None:
        return None
    if not isinstance(observation, Observation):
        raise TypeError("environment observation must be Observation")
    payload = observation.payload
    decision = payload.get("decision_view") if isinstance(payload, Mapping) else None
    facets = payload.get("agent_context_facets") if isinstance(payload, Mapping) else None
    if isinstance(decision, Mapping):
        projected = dict(decision)
        # An Environment Provider already owns and authorizes these facets.
        # Projecting only decision_view used to discard the grounded inventory,
        # local-world and action-feedback context before the Method saw it.
        if isinstance(facets, (tuple, list)):
            projected["agent_context_facets"] = facets
    else:
        projected = dict(payload) if isinstance(payload, Mapping) else payload
    if isinstance(projected, dict):
        constraints = _decision_constraint_index(facets)
        if constraints:
            projected["decision_constraints"] = constraints
    return {
        "observation_id": observation.observation_id,
        "generation": observation.generation,
        "payload": projected,
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
