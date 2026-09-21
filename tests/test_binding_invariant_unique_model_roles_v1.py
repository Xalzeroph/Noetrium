import pytest
from noetrium_platform.research.experimentation.binding import ResearchBindingRequirements, ResearchModelRoleRequirement

def test_binding_requirements_reject_duplicate_model_roles() -> None:
    rows=(ResearchModelRoleRequirement("solver","m1"),ResearchModelRoleRequirement("solver","m2"))
    with pytest.raises(ValueError, match="model roles must be unique"):
        ResearchBindingRequirements("trial", model_roles=rows)
