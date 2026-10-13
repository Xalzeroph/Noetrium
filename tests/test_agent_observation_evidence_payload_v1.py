import pytest

from noetrium_platform.capabilities.participant.agent.api import AgentObservation
from noetrium_platform.foundation.kernel.kernel import canonical_bytes


def test_agent_observation_preserves_evidence_payload_without_mixing_it_into_state():
    state = {"position": [1, 2, 3], "ready": True}
    evidence = {"events": [{"kind": "observation", "sequence": 1}]}
    observation = AgentObservation(
        observation_id="obs-1",
        generation="env-1",
        state=state,
        evidence_payload=evidence,
    )

    assert canonical_bytes(observation.state) == canonical_bytes(state)
    assert canonical_bytes(observation.evidence_payload) == canonical_bytes(evidence)
    state["position"].append(4)
    evidence["events"][0]["kind"] = "caller-mutated"
    assert observation.state["position"] == (1, 2, 3)
    assert observation.evidence_payload["events"][0]["kind"] == "observation"
    assert "events" not in observation.state
    assert observation.state_digest


def test_agent_observation_rejects_non_mapping_evidence_payload():
    with pytest.raises(ValueError, match="evidence payload must be a mapping"):
        AgentObservation(
            observation_id="obs-1",
            generation="env-1",
            state={},
            evidence_payload=["invalid"],  # type: ignore[arg-type]
        )
