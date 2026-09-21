import pytest
from noetrium_platform.research.experimentation.binding import ResearchParticipantRequirement

def test_participant_requirement_capabilities_are_unique() -> None:
    with pytest.raises(ValueError, match="capability requirements must be unique"):
        ResearchParticipantRequirement("agent","agent","method","treatment",capability_requirement_ids=("tool","tool"))
