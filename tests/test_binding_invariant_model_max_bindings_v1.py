import pytest
from noetrium_platform.research.experimentation.binding import ResearchModelRoleRequirement

def test_model_role_max_bindings_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_bindings must be positive"):
        ResearchModelRoleRequirement("solver","model",max_bindings=0)
