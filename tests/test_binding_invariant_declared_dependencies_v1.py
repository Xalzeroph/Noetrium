import pytest

from noetrium_platform.research.experimentation.binding import ResearchBindingRequirements, ResearchParticipantRequirement


def test_binding_requirements_reject_undeclared_dependency() -> None:
    participant = ResearchParticipantRequirement("agent", "agent", "method", "treatment", depends_on_roles=("missing",))
    with pytest.raises(ValueError, match="dependency is undeclared"):
        ResearchBindingRequirements("trial", (participant,))
