import pytest
from noetrium_platform.research.experimentation.binding import ResearchBindingRequirements, ResearchModelRoleRequirement

def test_model_role_lookup_fails_closed_for_missing_role() -> None:
    requirements=ResearchBindingRequirements("trial",model_roles=(ResearchModelRoleRequirement("solver","model"),))
    with pytest.raises(KeyError, match="no unique model role"):
        requirements.model_role("critic")
