import pytest
from noetrium_platform.research.experimentation.binding import ResearchParticipantRequirement

def test_participant_treatment_id_is_nonempty() -> None:
    with pytest.raises(ValueError, match="treatment_id must be a non-empty string"):
        ResearchParticipantRequirement("agent","agent","method","")
