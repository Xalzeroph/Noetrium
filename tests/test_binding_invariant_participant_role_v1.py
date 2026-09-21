import pytest
from noetrium_platform.research.experimentation.binding import ResearchParticipantRequirement

def test_participant_role_is_nonempty() -> None:
    with pytest.raises(ValueError, match="role must be a non-empty string"):
        ResearchParticipantRequirement("","agent","method","treatment")
