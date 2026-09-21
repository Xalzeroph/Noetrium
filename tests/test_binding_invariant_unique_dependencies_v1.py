import pytest
from noetrium_platform.research.experimentation.binding import ResearchParticipantRequirement

def test_participant_requirement_dependencies_are_unique() -> None:
    with pytest.raises(ValueError, match="dependency roles must be unique"):
        ResearchParticipantRequirement("agent","agent","method","treatment",depends_on_roles=("peer","peer"))
