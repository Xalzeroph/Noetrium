import pytest
from noetrium_platform.research.experimentation.binding import ResearchBindingRequirements

def test_binding_participants_require_tuple() -> None:
    with pytest.raises(TypeError, match="participants must be ResearchParticipantRequirement"):
        ResearchBindingRequirements("trial", participants=[])
