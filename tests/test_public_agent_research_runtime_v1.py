from noetrium.platform import bind_agent_research_runtime
from noetrium_platform.capabilities.model.api import MultimodalPart
from noetrium_platform.capabilities.model.request.api import ContentRef
from noetrium_platform.capabilities.participant.agent.api import AgentObservation
from noetrium_platform.capabilities.participant.agent.runtime import (
    MultimodalAgentObservationPort,
)


def _ref(char: str) -> ContentRef:
    return ContentRef(char * 64, 1, "application/octet-stream")


def test_multimodal_observation_port_composes_arbitrary_capture() -> None:
    class Observation:
        def observe(self, context):
            return AgentObservation("obs", "g1", {"tick": 1})

    class Parts:
        def capture(self, context):
            return (
                MultimodalPart(
                    "sensor-a",
                    _ref("a"),
                    modality_id="paper/arbitrary-latent",
                    sequence_index=0,
                ),
            )

    result = MultimodalAgentObservationPort(Observation(), Parts()).observe(None)
    assert result.state["multimodal"]["part_count"] == 1
    assert result.state["multimodal"]["parts"][0]["modality_id"] == "paper/arbitrary-latent"
    assert "a" * 64 in result.artifact_refs


def test_public_agent_research_runtime_rejects_incomplete_composition() -> None:
    try:
        bind_agent_research_runtime(
            observation=object(),
            planner=object(),
            skills=object(),
            executor=object(),
            memory=object(),
            safety=object(),
            completion=object(),
            evidence=object(),
            progress=object(),
        )
    except TypeError as exc:
        assert "port is incomplete" in str(exc)
    else:
        raise AssertionError("incomplete agent runtime composition was accepted")

