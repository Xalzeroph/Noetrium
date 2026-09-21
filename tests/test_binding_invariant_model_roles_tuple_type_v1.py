import pytest
from noetrium_platform.research.experimentation.binding import ResearchBindingRequirements

def test_binding_model_roles_require_tuple() -> None:
    with pytest.raises(TypeError, match="model_roles must be ResearchModelRoleRequirement"):
        ResearchBindingRequirements("trial", model_roles=[])
