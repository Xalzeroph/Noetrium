import pytest

from noetrium_platform.research.experimentation.binding import ResearchBindingRequirements, ResearchParticipantRequirement


def _p(role: str) -> ResearchParticipantRequirement:
    return ResearchParticipantRequirement(role, "agent", "method", "treatment")


def test_binding_requirements_reject_duplicate_participant_roles() -> None:
    with pytest.raises(ValueError, match="participant roles must be unique"):
        ResearchBindingRequirements("trial", (_p("agent"), _p("agent")))
