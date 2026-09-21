import pytest
from noetrium_platform.research.experimentation.binding import ResearchModelRoleRequirement

def test_model_role_required_is_strict_boolean() -> None:
    with pytest.raises(TypeError, match="required must be boolean"):
        ResearchModelRoleRequirement("solver","model",required=1)
