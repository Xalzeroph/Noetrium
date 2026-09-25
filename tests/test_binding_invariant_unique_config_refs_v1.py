import pytest
from noetrium_platform.research.experimentation.binding import ResearchParticipantRequirement

def test_participant_requirement_config_refs_are_unique() -> None:
    with pytest.raises(ValueError, match="configuration refs must be unique"):
        ResearchParticipantRequirement("agent","agent","method","treatment",configuration_ref_ids=("cfg","cfg"))
