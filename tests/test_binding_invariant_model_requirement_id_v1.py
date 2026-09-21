import pytest
from noetrium_platform.research.experimentation.binding import ResearchModelRoleRequirement

def test_model_requirement_id_is_nonempty() -> None:
    with pytest.raises(ValueError, match="requirement id must be a non-empty string"):
        ResearchModelRoleRequirement("solver","")
