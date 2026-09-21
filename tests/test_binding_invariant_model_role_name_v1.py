import pytest
from noetrium_platform.research.experimentation.binding import ResearchModelRoleRequirement

def test_model_role_name_is_nonempty() -> None:
    with pytest.raises(ValueError, match="role must be a non-empty string"):
        ResearchModelRoleRequirement("","model")
