import pytest
from noetrium_platform.research.experimentation.binding import ResearchParticipantRequirement

def test_participant_method_id_is_nonempty() -> None:
    with pytest.raises(ValueError, match="method_id must be a non-empty string"):
        ResearchParticipantRequirement("agent","agent","","treatment")
