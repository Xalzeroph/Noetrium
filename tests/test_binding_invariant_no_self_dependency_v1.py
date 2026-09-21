import pytest
from noetrium_platform.research.experimentation.binding import ResearchParticipantRequirement

def test_participant_requirement_rejects_self_dependency() -> None:
    with pytest.raises(ValueError, match="cannot depend on itself"):
        ResearchParticipantRequirement("agent","agent","method","treatment",depends_on_roles=("agent",))
